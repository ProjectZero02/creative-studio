# Story Studio v6 plan: do only the work the film needs

Status: plan (2026-11-25). Fixes all 29 problems in
[STORY_STUDIO_PROBLEMS.md](STORY_STUDIO_PROBLEMS.md) (numbers below are from that file).

## Goal

- Nothing finished is thrown away unless something it used really changed.
- A render runs only the steps this film needs. A 30 s one-take film with no
  music shows: video clip → saving. No stitch, no per-scene voiceover.
- Going back through the steps and forward again never asks for a re-render.
- The film type (one take or shots, who speaks) is a visible Setup choice, not a
  keyword guess.

## The core change: a film key instead of `clear_films()` everywhere

Today a film is "stale" when `final_uri == ""`, and about 20 handlers call
`clear_films()` by hand, some on every blur (#1, #2). Replace this with a key:

- `Story.film_key()` hashes only what the stitched film is made of: each
  scene's clip URI and trim, voice file URIs, music URIs and volumes, the
  normalized timeline, logo/brand content (hashed, not the raw JSON string),
  aspect and resolution.
- The render stores it as `final_key` (and `final_alt_key`).
- "Needs a render" = `film_key() != final_key`. Change something and change it
  back: the film is current again, with no AI call.
- Handlers stop calling `clear_films()`. They clear only the input they made
  stale (a clip, a voice line, the music), and the key does the rest.
- The editor shows *why* it is out of date ("Music changed", "Shot 2 changed"),
  by comparing per-part keys.

Same idea for the parts:

- **Voice:** `Scene.voice_uri` + `voice_key` (text, voice, style, language).
  Reuse when the key matches (#7).
- **Music:** `music_key` (prompt, length). A blur with the same prompt keeps it (#1).
- **Clips:** already keyed by frame/extends; keep.

Old stories have no `final_key`: treat their film as current until an input
changes (fill the key on first load from the current inputs).

## Milestones

Each milestone is one PR on `main`, tested with pytest (mocks) and a mock-mode
browser walk of the three test films: (a) the v5 one-take prompt, 30 s,
(b) a 4-shot narrated story, (c) music only, narrator off.

### M1. Stop throwing away work (small, ship first)

Quick fixes that don't need the film key yet.

1. **Guard every field save** (#1, #2): `_set_story_field` and `_update_scene`
   return early when the value is unchanged. Compare stripped to stripped;
   compare the music prompt with the effective prompt (`music_prompt or
   default_music_prompt`). Strip text when the AI first stores it. Check
   `on_track_prompt` and the Voice select too.
2. **A music change clears only the music**, not the film's clips; the header
   says "Update film" (re-mix), not "Make film".
3. **Unlock steps by takes, not shots** (#15): `reachable_steps` uses
   `frames_ready(story)` (`story_models.py:2648`).
4. **Save Set edits before rendering** (#4): `on_render` and
   `on_paint_all_frames` call `_save_draft()`. Delete the dead handlers
   (`on_to_storyboard`, `on_to_editor`, `on_approve`, `on_back_*`).
5. **One heavy job per story** (#5): disable "Write breakdown" for any running
   job (`BUSY_KINDS`), and `_new_job` refuses a second heavy job server-side.
6. **Export Retry keeps its settings** (#21): pass `job.params["options"]`.
7. **Shortened lines drop the old translation** (#22): `_fit_voice_lines`
   clears `narration_alt` for each line it rewrites.
8. **Empty idea** (#25): "Write breakdown" disabled until there is an idea.

Tests: blur with no change keeps `final_uri` and `music_uri`; a multi-shot take
reaches `editor`; export retry options; fit clears `narration_alt`.

### M2. Render only what changed

1. **Film key** as described above; migrate handlers off `clear_films()`.
2. **Voice cache** (#7): `voice_uri` + `voice_key` per scene; skip TTS and the
   fit step when no line changed. Retry reuses finished lines.
3. **Build the task list from the film** (#6): a small `render_plan(story)`
   returns the steps this film needs; `start_video` adds only those tasks.
   - One segment, no voice, no music track, no titles: the clip is the film
     (stream copy with the logo as an overlay only if a logo is set; loudness on
     the audio only).
   - Otherwise stitch as today, but run `frame_changes` once and share it
     between `seam_check` and `take_cuts`; `seam_check` returns before decoding
     when there are no cuts.
   - Label: "Joining the takes" for one-take joins, "Crossfades and mix" only
     when a fade is above zero.
4. **Second-language film is its own job** (#8): translate → alt voice → alt
   clips → alt stitch → alt save. The main film is left alone.
5. **Paid redo is visible** (#10): the seam/turn redo gets its own step
   ("Remaking turn 3 · smoother join") and counts in the progress. Raise the
   cut-detector threshold for continuous takes with camera motion (tune on the
   v5 test prompt).
6. **One library item per film** (#11): update the story's item by story id
   instead of adding one per render; record the model that made the clips.
7. **Cancel really cancels** (#20): run ffmpeg through `Popen` and kill it on
   cancel; check `cancel_event` before saving the film.

Tests: `render_plan` per film type; voice reuse on a second render; alt job
leaves `final_uri` unchanged; cancelled job doesn't set `final_uri`.

### M3. Right film type

1. **Setup gets two plain choices** (#12, #13):
   - **Shots:** One take / Several shots. Autoset fills it (Gemini
     `live_settings` returns it, any language); the keyword regex stays as a
     fallback; the user can override.
   - **Speech:** On camera / Narrator / None. "None" writes empty lines, sets
     `voice_on` off, and the script prompt stops asking for a line per scene.
2. **Script prompt** lets story-driven cuts replace "exactly N scenes" when
   Shots is "Several".
3. **Single take shows one voice turn per line that exists**, not empty turns;
   Frames hides "Voiceover:" when speech is off (#13).
4. **Blueprint matches the breakdown** (#14): takes/shots come from the same
   function the breakdown uses; no Voice cost line when speech is None.
5. **Lean set job** (#9): make only the views frames use (front, face, plate,
   item) and voice samples only for a narrator or on-camera speaker; other
   views are made on demand. Confirm with `frame_refs` before cutting.

Tests: autoset with an Arabic one-take idea; Speech=None gives no voice tasks;
set job task list per film.

### M4. Steps stay in sync

1. **Setup has a safe way forward** (#3): fields that don't need a rewrite
   (aspect, resolution, engine, language, style, brand, Arabic) save on change.
   "Write breakdown" shows only when idea, length, shots or speech changed, and
   asks before replacing shots once a film exists; otherwise the button is
   "Continue".
2. **Out-of-date banner in Edit & Export** (#16): from the film key, e.g.
   "Music changed · Update film".
3. **Reload opens your step** (#17): read `story.step` when still reachable;
   the stepper keeps `?step=` in the URL.
4. **Reuse the story's set** (#18): write the built set id to
   `create_set_id`; rewrite reuses it unless the user picks another.
5. **Auto-settings respect hand-set values** (#19): store pinned fields on the
   story; drop `live_settings` replies whose text no longer matches the box;
   cache by idea text.
6. **Multi-instance safety** (#23): `_outputs_ready` compares the film key and
   job start time, not just `final_uri`; add cases for set, music and translate.
   (Proper fix is moving job state to Firestore; file it as a follow-up.)

### M5. Progress and wording

1. **One progress number** (#26): percent = finished steps / steps, both from
   the same list; hide "· 0s" times.
2. **Banners per step** (#27): the job panel shows only on Takes and Edit; "Your
   film is ready" only on Edit, without "below".
3. **Copy** (#28): remove "Go to Director's Desk" (use "No film yet" + "Make
   film"), "generated in parallel, then stitched", "Next: the set and start
   frames are made for you."; fix "1 shots" and "Turns | No cuts found". Music
   lives in one place: the Music step; Edit links to it.
4. **Export defaults** (#24): size defaults to the film's resolution; the
   Arabic price uses the same estimate as Setup.
5. **Exact length** (#29): check why 30 s comes out 29 s (turn trim vs
   `clip_in`) and fix the trim.

## Order and size

| Milestone | Problems | Size | Why this order |
| --- | --- | --- | --- |
| M1 | 1, 2, 4, 5, 15, 21, 22, 25 | small | stops the money and work loss today |
| M2 | 6, 7, 8, 10, 11, 20 | large | the film key underpins M4 |
| M3 | 9, 12, 13, 14 | medium | needs M2's `render_plan` |
| M4 | 3, 16, 17, 18, 19, 23 | medium | needs the film key |
| M5 | 24, 26-29 | small | polish |

After M2 and M3, one live test of the v5 prompt at 360p (owner's yes first;
the owner deploys). Expected render list: "Scene 1 · video clip" (turns),
"Saving to your library", nothing else.

## Tracking

One `bd` issue per milestone, with the problem numbers in the description;
close each in its PR. Follow-up issue: job state in Firestore (#23 full fix).

## References

Patterns from editors that only re-render what changed (from product
knowledge; re-check before building M4's banner):

- Adobe Premiere Pro: the timeline render bar marks only changed sections as
  needing a render; smart rendering copies untouched clips without re-encoding.
- DaVinci Resolve: render cache keeps finished segments until their inputs
  change.
- Final Cut Pro: background rendering redoes only the changed parts, and
  undoing a change brings back the cached render.
