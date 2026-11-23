# Plan: Home chat fixes (owner feedback, 2026-11-23)

The One Studio redesign works, but the owner found nine problems. This plan fixes all of them in the shared Home code (`src/components/home_chat/*`, `src/components/chat_nav/*`, `src/services/studio_options.py`, `src/services/live_jobs.py`, `src/services/studio_chat.py`). The studio pages keep their routes.

## References

- **Claude (desktop and claude.ai):** below the prompt box sits one row of small quiet dropdowns (place, folder, model, effort). The `+` opens a menu: add files, then extra tools, and a submenu for plugins. Settings that matter right now sit in view; rare ones live behind `+`.
- **ChatGPT:** `+` opens attach plus tools (image, deep research, canvas). Picking a tool puts a removable chip in the box, and the box changes to fit that tool.
- **Gemini app:** "Tools" menu (Deep Research, Canvas, Image, Video). A picked tool shows as a chip with an ×. The thinking panel ("Show thinking") streams its steps while it works.

What we take: Claude's row of dropdowns under the box, ChatGPT/Gemini's removable mode chip, Gemini's live list of thinking steps.

## Causes found

| # | Problem | Cause |
|---|---|---|
| 1 | New chat shows twice in Recents | `_persist()` in `home_chat.js` runs on a 700 ms timer after every message change. The first save is a POST that creates the chat. If that POST hasn't returned when the reply arrives, the second save also sees no `_chatId` and POSTs again, which makes a second chat. |
| 2 | Industry demos showing | The code default is already off (`common/app_settings.py`, `show_demos: False`), so the switch is on in the deployed Firestore doc `app_settings/global`, or demos show somewhere that ignores the switch. |
| 3 | Missing options | Home exposes about a third of the studio controls. The full list is under step 3. Some are also silently wrong: image search grounding is off on Home (on in the studio), the music default differs (Lyria 2 against Lyria 3 Pro), the voice model is fixed, and Veo "people" is hard-coded. |
| 4 | No visible steps | Home jobs only have queued/running/done/failed. The studios used `generation_progress` (stages, timer, estimate bar, skeletons). `LiveJob.progress()` exists but nothing reports stages through it. |
| 5 | Image off-centre, plain audio player | The job card is `width: fit-content` and left-aligned, so it doesn't line up with the box. Audio uses the browser's own `<audio controls>`. |
| 6 | Dropdowns broken | The settings use native `<select>` inside the Lit shadow root. Windows draws its own white list in the wrong place, it ignores the dark theme, and the image model labels are confusing ("Gemini 3 Pro" for an image model). Still to confirm in the browser: whether a picked value is lost on the next render (`.value` plus `?selected`), and whether the Mesop selects on the studio pages also broke. |
| 7 | Type buttons under the box | Placed there by phase 4 of One Studio. |
| 8, 9 | Box should feel like Claude's; `+` only attaches a picture | Not built yet. |

## Steps (one commit each, in this order)

### 1. Fix the double chat (#1)
- `home_chat.js`: keep one save promise (`this._saving`). `_persist()` waits for a save already running, and the "create" path runs once, so later saves PATCH.
- On the server (`routers/chats_router.py`): the client sends a `client_id` (uuid made at the first message) with POST, and a repeat POST with the same id returns the same chat. This guards against double clicks and a second tab.
- Test: send two messages fast with the POST slowed down → one chat in Recents. Add a pytest for the repeat-POST case.

### 2. Demos off everywhere (#2)
- Grep every place a demo shows (chat_nav, Home tiles, Library filters, the chat's tools, Live agent tools, the Settings copy) and make each one follow `show_demos`.
- Add `SHOW_DEMOS` to `config/default.py` (default false) as the seed. On deploy, a stored `true` that an admin never set is reset. In the deploy guide, tell the owner to check Settings > Admin > Show demos.

### 3. Bring back every option (#3)
`services/studio_options.py` gets each field's `tier`: `main` (dropdown under the box), `advanced` (behind `+`), or `input` (a file slot). The runners in `live_jobs.py` read every field and pass it on, the same way the studio pages do.

| Type | Under the box | Behind `+` (advanced) | File slots |
|---|---|---|---|
| Image | Model, Shape, Quality | Brand colours toggle, Search grounding (on), Number of images (when a model allows >1), Thinking level | Up to 14 references |
| Video | Mode (Text, Image, First + last, References, Edit, Extend, Upscale; per model), Model, Shape, Resolution, Length, Sound | Number of videos (Veo), Negative prompt, Seed, People, Let Veo improve the prompt | First frame, last frame, up to 10 references + style, input video |
| Music | Model (default Lyria 3 Pro, same as the studio), Tracks (Lyria 2) | Lyrics on/off with a lyrics field and "Write lyrics", Instrumental | Reference image (Lyria 3) |
| Voice | Model (Gemini TTS / Chirp 3 HD), Voice, Language, Style, Pace | Two speakers (names + voices), Direction notes, Pronunciations (Chirp) | – |
| Film | Length (30 s to 10 min, Custom), Style, Shape, Language | From script, Video engine, Pacing, Who speaks, Camera, Scenes / scene length | – |

- Fix the image model labels: "Nano Banana Pro (Gemini 3 Pro Image)" and similar, taken from the registry.
- Attachments go to the right slot (first frame, reference, input video) and are no longer cut to the first file.
- After a result: image presets and "Suggest edits", Extend for videos, and the music critique as an action on the card.
- Test: `test/test_studio_options.py` checks every studio control appears in `fields()`, and each runner passes each setting (mocked model calls).

### 4. Show the thinking (#4), the main demo point
Two layers, both drawn live in the thread:
1. **Chat thinking.** `studio_chat.py` returns a `trace` as it works: "Reading your message" → "Picked Image · Nano Banana 2.1, 16:9" → "Wrote the prompt" (the final prompt shown) → "Started image 1". Shown as a "Thinking" block that is open while it runs and folds into one line ("Thought for 3 s") when done, like Gemini. Typed settings found in the prompt ("16:9", "4K") show as steps too.
2. **Job steps.** `LiveJob` gets `stages`, `stage`, `started_at`, `typical_seconds`, and the runners call `job.progress(i)` at the same points the studios used:
   - Image: Preparing prompt / Reading references → Sending to Gemini → Generating image → Saving to library → Done
   - Video: Enhancing prompt → Sending to Omni/Veo → Generating / Extending / Editing video → Saving → Done
   - Music: Preparing → Sending to Lyria → Composing → Saving → Done (then Analysing the track, if on)
   - Voice: Preparing → Sending to {engine} → Speaking → Saving → Done
   - Film: the `story_jobs` task list (Scenario, Set, Storyboard frames per scene, Clips per scene, Music, Voice-over, Stitch), with "X of Y" and the elapsed time.

   `GET /api/chat/jobs` returns these. The job card shows the steps (done ✓, now with a pulse, next greyed), an elapsed timer and an estimate bar, and a skeleton in the target shape. It reuses the look of `generation_progress.js`, so Home and the studios match.
- Mock mode gets the same stages with `fake_wait` split across them, so the demo shows the full flow with no cloud.

### 5. Cards and players that look right (#5)
- One thread width shared by the messages, the cards and the box (same max-width and the same left edge as the text). Media is centred in a card that fills that width, with the shape kept and no blank right side.
- A custom `<gm-audio>` player (Lit): play/pause, a waveform drawn from the audio (Web Audio peaks, cached), the time, speed (voice) and download. Used in the thread, the jobs panel, and Library audio tiles. Keyboard and screen-reader labels, light and dark.
- Video: the same frame, a poster from the first frame, and our controls row (play, time, mute, full screen).

### 6. One dropdown that works everywhere (#6)
- Swap every native `<select>` on Home for the existing `components/composer/chip_menu.js` (or a small `gm-menu` built from it): it opens below or above as space allows, uses the theme tokens, works with arrow keys, Enter and Esc, and closes on an outside click.
- Click through every Mesop `me.select` on the studio pages and Settings in the browser. If they broke too, find the shared cause (likely the theme CSS in `studio.src.css` or the overlay z-index from the perf change b3da4846) and fix it once.

### 7. Types in the side menu, and live mode detection (#7)
- **Side menu (`chat_nav`):** a "Create" group under New chat: Image, Video, Music, Voice, Film. On Home, a click sets the mode in place (window event `gm-pick-kind`). On other pages it opens `/home?mode=video`. The current mode is highlighted. Remove the buttons under the box.
- **Detect while typing (client side, no round trip):** `detectKind(text)` runs on input (debounced ~120 ms) with a weighted word list per type in English and Arabic:
  - image: image, photo, picture, poster, logo, render, صورة
  - video: video, clip, animate, footage, shot, فيديو
  - music: music, song, beat, track, jingle, soundtrack, موسيقى
  - voice: voice, voice-over, narrate, say, read aloud, صوت
  - film: film, short film, ad, commercial, story, trailer, فيلم

  It also handles negation ("no music") and the order of words ("a video of a photo shoot" → video, because the first media word that is a verb's object wins). When the score passes a threshold, the box switches at once: a mode chip with × appears in the box, the dropdowns slide in, and the placeholder changes.
- **Who wins:** a mode picked by hand (side menu or chip) stays until the person removes it. A detected mode follows the text and can be dismissed (×), and a dismissed mode stays off for that message. With no mode the box stays a chat (Auto), and the server chat can still pick. When the chat picks a type, it uses the same settings the dropdowns show.
- Test: a table of ~60 sample prompts (EN + AR) in `test/js` or a Node script → expected mode.

### 8. A Claude-style box (#8)
- Inside the box: the text, attachment chips, the mode chip, then a bottom row with `+` on the left and Enhance, mic and Send on the right.
- Below the box, one row of quiet dropdown pills for the current mode, like Claude's "This computer ▾ · Creative Studio ▾ … Model ▾". Main fields on the left, Model on the right. Same height, tonal fill, no outlines (UI rules). In Auto mode the row shows only the chat model.
- On phones the row scrolls sideways and the `+` menu becomes a bottom sheet.

### 9. A `+` menu that does something (#9)
- Opens a menu like Claude's:
  - **Add files or photos** (Ctrl+U): images, plus video and audio where the mode takes them.
  - **From Library**: pick earlier media.
  - **Use as…**: first frame, last frame, reference, input video (only in Video mode).
  - **Advanced ›**: a submenu with the mode's advanced fields from step 3 (switches and small fields inline). A dot on `+` shows when an advanced setting is changed from its default.
  - **Open full studio**: the old page, with the prompt carried over.
- Keyboard: arrows, → opens the submenu, Esc closes.

## Checks before push
- `pytest` for studio_options, live_jobs stages, chats_router dedupe; the mode-detection script; `ruff` on changed Python files only.
- Browser on localhost (mock mode), at 1440 and 390, light and dark, EN and AR: new chat (one Recents row), each mode from the side menu and from typing, every dropdown and the `+` menu, steps shown for each type, the audio player, and the centring.
- Push to `main`, then a short deploy guide for the owner (including the demo switch).

## Order and size
1–2 are small fixes (ship first). 6 and 8 are one piece of UI work (the new menu and box). 3 and 9 go together (fields and the advanced menu). 4 is the largest (server stages plus the card). 5 and 7 are separate. Steps 1–2, 4 (server side) and 5 can run in parallel; 3, 6, 8 and 9 all touch `home_chat.js` and run in sequence.
