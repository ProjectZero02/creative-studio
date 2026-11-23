# Story Studio v4 plan: one continuous film, simpler studio

Purpose: make Story Studio produce films with no visible or audible cuts between generated clips, and make it easy to use. Written 2026-11-23 after the first live test of v3 (story `59600908a51d`, project `mikel-testing`).

## 1. What went wrong in the live test

Test: "one guy on a stage talking about Gemini Enterprise for 30 seconds, the camera pans left to right slowly." Omni 1.2 Flash, 4 shots × 8 s.

Measured on the exported film (ffmpeg scene score per frame, median 0.0005):

| Time | Score | What you see | Cause |
|---|---|---|---|
| 8.0 s | 0.018 (≈35×) | small jump in framing, pose and light | stitcher switches files |
| 16.0 s | 0.017 (≈33×) | same | stitcher switches files |
| 24.0 s | 0.343 | different venue, different camera | shot 4 was not extended |
| 0–24 s | n/a | camera pans left, not right | prompts fight each other |

Audio level stays steady at every join (no dropout). The cut you hear is the sound changing source.

### Cause 1: the stitcher re-cuts a take that was already seamless

Omni's extend returns the whole video so far plus the new seconds. Clip 3 is one 24 s file that holds shots 1–3, and it has no seams inside (its largest frame change is 0.010). But `build_stitch_plan` (`src/services/story_models.py`, the `extended` branch) builds the film from clip 1 [0–8] + clip 2 [8–16] + clip 3 [16–24]. Each file re-encodes the earlier seconds slightly differently (clip 1 vs clip 3's first 8 s: PSNR 41 dB, min 34 dB), so every file switch shows a jump. `render_args` (`src/services/story_timeline.py`) also fades the audio out and in at each one (`JOIN_FADE`).

### Cause 2: the take stops at 30 s, and the next shot starts from a painted picture

`Story.continues_take` (`story_models.py`) extends only while `take + next ≤ STORY_TAKE_MAX_SECONDS` (30, `src/config/default.py`). 24 + 8 = 32, so shot 4 became a fresh clip animated from its own painted frame, in a different-looking venue. Continuous takes also only run when both shots are "spoken on camera" (`_spoken_pair`).

Omni on Vertex actually returns up to 40 s per extension and only reads the last 30 s of the input ([Vertex extend doc](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/video/extend-a-veo-video)). So a single file can hold up to about 40 s. Longer takes need rolling extension (section 3, item A3).

### Cause 3: prompts pull the camera in different directions

- `pan_right` becomes "smooth horizontal camera pan right across the scene" in the video prompt only (`clip_prompt`). Keyframe prompts have no camera text.
- Each shot's keyframe is written and painted on its own, with its own subject position ("slightly right of center", later "left of center"). On every continuing turn the request attaches that shot's frame and says "Start exactly on the attached image" (`story_service.py` ~2491), which can pull the camera back.
- The model also writes a free `motion_prompt` next to the preset, which can describe a different move.
- In script mode, cameras cycle through a list that includes `pan_left`, ignoring the story's camera (`story_director.py` ~600).
- "Pan right" is ambiguous for these models. Guides recommend stating the camera path and the subject path separately, with speed ([HackerNoon](https://hackernoon.com/stop-letting-the-model-pick-the-camera-heres-the-camera-direction-workflow-i-run-for-every-ai-shot), [Kling](https://kling.ai/blog/kling-ai-camera-control-video-guide)).

### Cause 4: UI friction

- Setup has 13 controls; several are auto-derivable (scenes, scene length) or belong in the prompt (camera, who speaks). Style tiles are cartoon SVGs that don't show the style.
- Frames must be painted by hand (`Paint all frames`); there is no "redo this frame because…" box.
- Director's Desk hides the path forward in three sub-tabs.
- Player swaps between 3 `<video>` elements and seeks into each clip, so it stutters at joins; there is no fullscreen.
- Download is a plain link; export is fixed at 1280 px MP4.

## 2. What the best tools do (research)

| Tool | Pattern worth copying |
|---|---|
| [Kling](https://kling.ai/quickstart/kling-4-model-user-guide) | Duration 3–30 s, resolution 720p/1080p/4K; multi-shot split decided by the model; references tagged `@Image1`, `@Voice1` and given a role in the prompt |
| [Higgsfield Cinema Studio](https://higgsfield.ai/creator-hub/help-center/tools/how-do-i-use-cinema-studio) | One canvas; "+" reference picker over uploads, saved Elements and past generations; reusable cast; presets for genre, palette, lighting, lens |
| [LTX Studio](https://ltx.io/blog/ltx-storyboard-generator-update) | Script → shots → stills; characters, objects, locations pulled out automatically as Elements; regenerate one panel without touching others |
| [Google Flow](https://support.google.com/flow/answer/16935718?hl=en) | Extend continues from the end of the clip; "Jump to" starts a new shot from the last frame; edits by chat with a version history |
| [Sora storyboard](https://techwiser.com/how-to-use-the-storyboard-feature-on-sora-what-we-found/) | Credit estimate before generating |
| [CapCut export](https://www.capcut.com/help/export-videos-in-capcut) | Export menu with resolution, frame rate, format; captions as SRT |

Open source: nothing is mature enough to embed in a Mesop app. [ViMax](https://github.com/HKUDS/ViMax) (MIT, Idea2Video / Script2Video) is a useful reference for pipeline and prompts; FilmAgent and MovieAgent are research projects. Decision: keep building our own, borrow ideas.

Google's prompt guidance ([Veo prompting guide](https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-veo-3-1), [Omni doc](https://aistudio.google.com/docs/omni)):
- Layout: cinematography + subject + action + context + style; audio as quoted dialogue, `SFX:`, `Ambient noise:`; optional timestamped beats.
- Omni may cut on its own: say "single continuous shot, no scene cuts".
- No negative-prompt field: put negatives in the text.
- Re-state set and subject in every extension, and pass the same reference images (Omni Flash on Vertex: up to 2).
- Keep dialogue near the end of each part if speech must continue across an extension.

Note: "we may be over-complicating it" is partly right. Most of the cuts come from our own stitching and per-shot keyframes, not from the model. v4 removes machinery for continuous takes rather than adding it.

## 3. Plan

### Phase A: seamless engine (do first)

Status (2026-11-23): all of Phase A is built.

- **Re-stitch of the live test film with A1:** the join change at 8 s and 16 s dropped from 0.018 to 0.0009 (normal motion; the film's median is 0.0006), and the sound runs through.
- **A3:** rolling takes up to `STORY_TAKE_ROLLING_MAX_SECONDS` (300). There is one change of file per extra extension, with a `STORY_ROLL_CROSSFADE` (0.17 s) crossfade inside the overlap.
- **A6:** the check now judges only joins meant to be seamless. A jump remakes the clip after it once (`STORY_SEAM_RETRIES`); this is skipped in demo mode.
- **A7:** sound crosses at cuts instead of dipping. Same-place frame references are part of Phase C.
- **Still to do:** the live re-test (section 5, tests 2–4).

A1. **One take = one file.** In `build_stitch_plan`, collapse an extension chain into a single segment that uses the last extension's file whole (start at the chain head, trim 0, full length, its own audio). Merge only between separate clips. Player and export use the same rule.

A2. **Takes up to 40 s in one file.** Raise `STORY_TAKE_MAX_SECONDS` to 40 for Omni (env-driven, per model in `config/omni_models.py`). Allow continuous takes for any shots, not only spoken pairs.

A3. **Longer takes by rolling extension.** Past 40 s, keep extending the latest file (Omni reads its last 30 s). Each new file overlaps the previous one. Join inside the overlap at the best-matching frame pair (search the overlap, lowest frame difference), with a 2–4 frame blend and a 30–50 ms audio crossfade. This is the "match the last frames of one clip to the first frames of the next" idea, done where the content really is the same. Window sizes are tuning values for A6.

A4. **No painted frames inside a take.** A take has one start frame. Continuing turns send no new image, only the text and the same reference images. Frames are painted only where a take starts.

A5. **Structured prompts.** One template for every clip and turn, in this order:
- Shot: "Single continuous shot, no scene cuts."
- Camera: path, direction, speed in plain words ("the camera moves slowly to the right; the stage slides left through the frame").
- Subject: who, where in frame at the start and at the end of this part.
- Action and dialogue.
- Set and light: re-stated each time from the set bible.
- Style.
- Audio: dialogue, `Ambient noise:`.
- Avoid: cuts, new locations, camera reversing.

Each part's start state is the previous part's end state. Remove the free `motion_prompt` contradiction and the script-mode camera cycling. Pass set and character reference images on every turn. Test "pan right" wording with a fixed seed before shipping (section 5).

A6. **Seam check and auto-retry.** After each take or join, measure the frame change at the boundary (ffmpeg scene score, as used above). If it is more than about 5× the clip's median, regenerate that part with a new seed, at most 2 times, then flag it in the UI. Show the check result per join.

A7. **Real cuts done well.** When the user wants a new angle, start the next shot from the previous shot's last frame (or a first-and-last-frame bridge), never from a picture painted from text alone. Lay a continuous room-tone/ambience bed under the whole film and use short audio crossfades or J/L cuts at real cuts.

### Phase B: Setup (one screen)

| Keep | Change | Remove |
|---|---|---|
| Idea / script box | Duration: optional text box ("30s", "2 min"); blank = Gemini decides | Try chips |
| Video engine | Style: free text box with preset chips; presets fill real style text; tiles show real sample frames made from that text | Who speaks (Gemini decides from the idea) |
| Aspect ratio | Add Resolution (720p, 1080p, 4K where the engine allows) | Camera (say it in the idea) |
| Language | Pacing: keep as a simple chip row (Calm, Normal, Fast) | Scenes, Scene length (auto from duration) |

**References first**, above the idea:
- Set picker: the existing saved sets.
- An "Add reference" menu: Character, Object or product, Location, Voice, Brand. Each item gets a role tag and can be @-mentioned in the idea (Kling pattern).
- Brand becomes a dropdown of saved brands plus "New brand". This needs `common/brand_kit.py` to store more than one brand per owner.

**Live blueprint** that updates as you type (input-level updates, not on blur):
- Length.
- Takes and cuts ("1 continuous take", or "3 takes, 2 cuts").
- Shots.
- Resolution.
- Estimated cost, from `config/pricing.py` (Omni video $0.40/s today, plus frames, voice and music). Example: about $13 of video for 32 s; check whether extension bills only the new seconds and correct the estimate.
- Estimated time.

### Phase C: guided flow, fewer clicks

- After Setup, the steps run on their own: write breakdown → paint start frames automatically → show the shot strip for review → Make film. Each step's button says what happens next.
- Director's Desk becomes one canvas: a strip of takes and shots on top; select one to open a side panel with its frame, prompt, camera, length and a **"Redo with note"** box for both the frame and the clip. Use Omni's multi-turn edit (`previous_interaction_id`, clips up to 15 s) for small clip fixes.
- Cast and Set move into the References tray; the Animatic is a "Preview" button, not a tab.
- Each take shows a "continuous" badge and its seam-check result.

### Phase D: player and export

- Preview plays one rendered proxy file (fast, low bitrate, rebuilt after each edit) instead of swapping clip elements, so playback is smooth. Clip-level scrubbing stays in the editor.
- Fullscreen button and keyboard shortcuts (space, F, arrows).
- One clear **Export** button that opens a menu:
  - Resolution: up to the generated resolution, with upscale marked.
  - Format: MP4 (H.264), MOV, WebM.
  - Subtitles: none, burned-in (style), or SRT file.
  - Audio only: MP3 or WAV.
  - Download.

## 4. Order of work

1. Phase A (A1, A2, A4, A5, A6 first; then A3, A7). This alone should remove the cuts in the test film.
2. Phase D player proxy and export menu.
3. Phase B Setup and live blueprint.
4. Phase C guided flow and single canvas.

Each phase is its own PR with tests. A1 is testable offline: re-stitching story `59600908a51d` from clip 3 alone should give zero jumps from 0 to 24 s.

## 5. Live tests (cost money, owner approves each)

1. Re-stitch the existing test film with A1 (no generation cost).
2. Camera wording test: two 8 s Omni clips with a fixed seed ("pan right" vs the explicit wording in A5). About $6.40 of video.
3. Repeat the 30 s single-take test after Phase A. About $13 of video plus frames and voice.
4. A 60 s single take to prove rolling extension (A3). About $25+ of video.

Pass criteria:
- No boundary scores above 5× the median inside a take.
- Camera moves the requested way.
- Same venue throughout.
- No audible change at joins.
