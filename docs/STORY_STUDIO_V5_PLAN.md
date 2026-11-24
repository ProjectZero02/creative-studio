# Story Studio v5 plan: one continuous take that works

Status: plan for review (2026-11-24), audited once against the code. Nothing is
built yet.

## Goal

The test prompt, used for every test until this works:

> i want one shot, with the character talking, one guy on a stage talking about
> Gemini enterprise for 30 seconds. the camera pans from left to right slowly
> throughout that time

Done means:

- The film is **one generated video of 30.0 s** (within one frame), with **no
  cut** in it.
- The presenter, outfit, stage and voice stay the same from start to end.
- The speech is clean: no hiss or crowd under it, no dead air mid-sentence.
- The same engine can later join continuous takes into a long scene (for
  example 5 minutes) with no visible join.
- The flow is simple: every step shows in the top bar, and each step does one
  thing.

## What went wrong (2026-11-24 test)

Measured on "The Power of Gemini Enterprise" against the last good run, "Work
Made Simple":

1. **No set.** The one-screen Setup went from breakdown straight to start
   frames, and Set defaulted to "No set". Gemini wrote a presenter, but it was
   never built into a set, so Omni had no presenter or stage reference.
2. **Nobody named on later turns.** Without a set, the prompt said "the same
   person ( )". Each turn re-sent the scene description, with new positions,
   backdrop and lighting.
3. **A forced pan on a speaker standing still.** "Camera, for the whole clip:
   pan right… avoid the camera stopping" panned away from him. Omni then cut back
   to him at 8.42 s and 24.33 s, inside its own single 32 s video.
4. **Too many pieces.** At least 3 scenes, at 8 s each, turned a one-shot into 4
   scenes and 4 turns, and 32 s instead of 30.
5. **The cut check looked in the wrong place.** It checks only ±0.09 s around
   joins between files. A single file has none.

The stitcher and mixer were not the cause.

## What already exists (we keep it)

- A scene of up to 30 s is already **one Omni thread**: a first clip, then
  extension turns with the script split at sentence ends. The code paths are
  `generate_clip`, `clip_parts`, `split_narration_parts` and `_lengthen` in
  `story_service.py`.
- Omni returned the **whole video so far** on each turn on our project, so a take
  is one file.
- The music track already holds several clips with start, in, out, gain and
  ducking (`story_timeline.py`).

So the core fix is mostly planning and prompts. It needs no new data model:
**a take is a Scene.**

## Facts we design around

- Omni 1.2 Flash, per Google's docs
  ([Gemini API Omni docs](https://aistudio.google.com/docs/omni.md.txt)):
  - a single generation is 3 to 15 s;
  - an extension is 3 to 10 s per turn;
  - a chain is at most **30 s**;
  - an extension reads the **last 10 s**;
  - 360p, 720p, 1080p and 4K.
  - Our Vertex run made a 32 s chain, so Vertex may allow more, but we stay at
    30.
- Extensions on our live path are **chat follow-ups**, using
  `previous_interaction_id`:
  - The API rejects a video task on that path (`omni.py`).
  - The path carries at most 2 images and drops the rest.
  - The "6 references on extension" in Google's docs applies to the extend
    task, which is only our fallback.
  - The code also records that a painted frame on a later turn "made the camera
    jump back".
  - So we **don't** send pictures on later turns until a test says it helps
    (M2).
- Price: on the Gemini API list, 360p is about $0.023/s and 720p about $0.07/s
  ([Gemini API pricing](https://aistudio.google.com/docs/pricing)). Our
  blueprint assumes $0.40/s. The Usage page (billing catalog, PR #40) will tell
  us the real Vertex rate.

## M1: prove continuity (first milestone)

**Done when:** one live run of the test prompt gives a 30.0 s file with no cut
peak anywhere in it, steady presenter and voice. About $2 to $12, depending on
the real rate.

1. **One take for a one-shot.**
   - Make the scene minimum 1. It lives in 5 places, all changed together:
     - `STORY_MIN_SCENES` in `default.py`;
     - `apply_caps` in `story_models.py`;
     - `story_autoset.py`;
     - `studio_options.py`;
     - the "exactly N scenes" prompt and schema in `story_models.py`.
   - Breakdown rule: an idea that says "one shot", "continuous", "single take",
     "no cuts" or "throughout" is **1 scene of the asked length**. Otherwise
     scenes are cut only where the story cuts. Continuous stretches are never
     split just to fill a count.
2. **Even turns.** `clip_parts(30)` becomes 10 + 10 + 10 (today it is 15 + 8 +
   7). Turns are even 10 s parts, matching Omni's default and its 10 s context.
   The script is split at sentence ends to match.
3. **Exact length.**
   - Duration text is exact, and the blueprint says "30 s", not "≈ 32 s".
   - The stitch trims the take to the asked length (generation can be off by a
     frame or two).
   - Take cap: `STORY_TAKE_MAX_SECONDS` 40 → 30. `STORY_TAKE_CONTEXT_SECONDS`
     stays 30 for now: it drives how old multi-scene takes join.
4. **The set always comes first.**
   - Setup's Set field: saved sets, plus **New set** as the default. "No set" is
     removed.
   - After the breakdown, the job builds the set (`start_set`) **before**
     painting the start frame (`start_storyboard`). It builds from the cast the
     breakdown wrote. If that cast can't be used, it makes one Gemini casting
     call, and the set step says so.
   - The start frame is painted from the set: presenter front plus stage wide.
5. **Continuation prompts that only continue.** Each later turn sends:
   - "Continue this exact shot from its last frame, one continuous shot, no
     cuts."
   - Who, from the set, never blank: "the same man (mid-40s, navy blazer, white
     shirt)", plus the same stage, lighting, camera height and camera move.
   - This turn's lines, word for word, and at most one action.
   - Sound: "same voice, quiet room tone, no music, applause or crowd".
   - It no longer sends the scene's full description or framing words. The
     first turn sends that once. This follows Google's "one continuous shot… no
     jump cuts"
     ([DeepMind guide](https://deepmind.google/models/gemini-omni/prompt-guide/))
     and third-party advice to repeat a few anchors and change one thing per
     turn
     ([Atlas Cloud](https://www.atlascloud.ai/blog/tips/gemini-omni-flash-1.1-video-extension)).
   - The turn-history replay keeps turn 1's pictures, so later turns still "see"
     the references without sending them again.
6. **A camera that keeps the subject in frame.**
   - The softer, pre-Phase-A camera wording comes back: "a slow pan to the
     right, following the presenter". The "for the whole clip / never stop"
     wording goes.
   - Breakdown rule: in a long take with a moving camera, the subject moves with
     it. He walks across the stage while the camera tracks him. One camera move
     per take.
7. **Turn records and a whole-take cut scan.**
   - Add `Scene.turns`: per turn, seconds, lines, interaction id, offset and the
     prompt sent. It's an optional field, so old stories still load.
   - After the take is made, scan the **whole file** for frame-change peaks. A
     peak of 30 times the take's median or more is a cut, and is mapped to the
     turn it falls in by the turn offsets. That catches 8.42 s even though it
     isn't on a boundary.
   - In M1 the scan **reports** in the job log and on the take card. Redo comes
     in M2.
8. **Narrator off for on-camera films.** When every scene is spoken on camera,
   `voice_on` is forced off and the switch is hidden.
9. **Cheaper drafts, no new pipeline.** Story Studio draft resolution comes from
   `STORY_VIDEO_RESOLUTION`, which we set to 360p for testing. That is about a
   third of 720p on the API list. Changing it needs no code.
10. **Clip gain cap.** The mix's clip gain is capped at 1.15. The last film was
    pushed 1.3 times into the limiter.

Tests for M1:
- The planner gives 1 × 30 s for the test prompt.
- `clip_parts(30) == [10, 10, 10]`.
- A continuation prompt has no blank "( )", no framing words and no "whole clip"
  wording.
- A set is built before frames.
- No "No set" option.
- Narrator off for on-camera films.
- The cut scan flags a cut in an ffmpeg-made clip with a cut, and passes a clean
  one.
- The trim lands on the exact length.
- The mock `extend_clip` returns the whole video and writes turn records.

## M2: make it self-correcting

1. **Reference A/B test, before building.** One turn at 360p, made three ways:
   (a) a thread with no pictures, (b) a thread with the references sent again,
   (c) the extend task with references and no thread. That's about $1 at the API
   rate. Keep the winner.
2. **Redo a turn.**
   - Redoing turn k calls Omni again from turn k-1's interaction. Turns after k
     are dropped and remade, because each turn holds the whole video so far.
   - If the interaction has expired, it falls back to the extend task.
   - The cut scan from M1 triggers at most **one redo per take per run**. At the
     blueprint rate, redoing turn 2 of 3 costs about $8, or under $1 at 360p.
   - "Redo this turn" on the take card does the same by hand.

## M3: the steps and screens

1. **Every step at the top, in order:** Stories, Setup, Script, Set, Frames,
   Takes, Music, Edit & Export.
   - Set comes **after** Script, because it is built from the cast the script
     names. It is marked done when you picked a saved set.
   - New step ids get names that don't clash with saved ones; today `video`
     means Edit. Old saved steps map to the new ones on load.
2. **Setup:**
   - Set (saved or New set), Brand, the idea, and exact duration.
   - Speech (On camera or Voiceover). The narrator switch only shows for
     Voiceover.
   - Resolution (Draft 360p or 720p).
   - Arabic version, showing its cost (see M4).
   - Blueprint: `30 s · 1 continuous take`, then `Video 1 × 30 s (3 turns of
     10 s)`. The cuts line only shows when there are cuts. The cost follows.
3. **Split the Director's Desk:**
   - **Script:**
     - The brief first, in a box that grows to 8 lines.
     - Then one card per take, with a large script box per turn (0 to 10 s, 10
       to 20 s, 20 to 30 s).
     - The camera move and one action.
   - **Set:** the presenter and place images, each with redo.
   - **Frames:** per take, the first frame, plus the last frame only when the
     next take must match it.
   - **Takes:** one row per take showing its turns as they render, with a
     player, the cut-scan result and "Redo this turn".
4. **Remove the four switches:**
   - "Continuous takes": always on.
   - "Match colour at cuts": automatic, only at real cuts.
   - "Start each cut from the last frame" (`continuity`) and "Straight cuts
     between matching shots" (`seamless_joins`): the engine picks the join.
     `build_stitch_plan` reads both today, so they become fixed settings.
   - "Also make an Arabic version": moved to Setup and Export.

## M4: music, Arabic, long scenes, final quality

1. **Music step** after Takes, open while the video renders. The length is known
   because durations are exact.
   - One track for the whole film is the default; LTX does the same
     ([LTX](https://ltx.io/studio/platform/script-to-video)).
   - "+ Add track" covers chosen takes and is stored as `music_tracks_json`.
     `build_timeline` places the tracks with crossfades; the existing music
     track and ducking do the mixing.
2. **Arabic version** in Setup and Export.
   - For on-camera speech it is a second full Omni render, so it doubles the
     cost. Both places show that cost.
   - Choosing it on export starts a video job.
3. **Final quality:** export upscales a 360p draft with Omni upscale, after
   checking it accepts a 30 s input; otherwise it re-renders at 720p.
4. **Long continuous scenes** (5 min is about 10 takes of 30 s):
   - Each next take starts from the last frame of the one before, with the set
     references.
   - Joins sit at sentence ends, with a short crossfade and the room sound
     crossing.
   - Each join is checked and redone once.
   - This is several generations, so a join can still show. We say that.
   - It builds on the rolling-take code that exists.
5. Sound checks: turn loudness within 4 dB of the take, and a hiss flag.

## How others do it

Higgsfield, LTX and Kling make the cast and places first and reuse them as
"Elements". Each shot or take then gets one card with its image
([Higgsfield](https://higgsfield.ai/creator-hub/help-center/tools-and-workflows/how-do-i-use-cinema-studio),
[LTX storyboard](https://ltx.io/blog/how-to-storyboard),
[Kling elements](https://kling.ai/quickstart/klingai-element-library-3-user-guide)).
Flow extends one clip at a time, with a duration, a note and up to 3 images
([Flow help](https://support.google.com/flow/answer/16935718?hl=en)).

## Each milestone

Unit tests, then a mock-mode browser check (1440 and 390 px, light and dark),
then push. Then you run the test prompt live. Live runs and the M2 A/B test cost
money, so each waits for your yes.
