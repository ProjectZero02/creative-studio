# Studio fixes (plan)

## For the agent picking this up

You are implementing the fixes below in `ProjectZero02/creative-studio` (renamed from `genmedia-studio` on 2026-11-17; old URLs redirect). Work through the **Commits** list at the end, in order, one small commit each.

How to work:

1. Clone `https://github.com/ProjectZero02/creative-studio.git` and branch from `main` (e.g. `fix/studio-prompt-settings`). Push the branch and open a PR against `main`. Use one PR per group: commits 1–6 (prompt settings sync), 7–10 (Image Studio P1), 11–15 (the rest). Don't push to `main` directly. If you can't push to this repo, fork it and open the PR from your fork.
2. Read `AGENTS.md` first. The app lives in `src/`, so every path in this plan is under `src/`. Follow its rules on `ruff` (only files you touched, `--diff` first), `pytest`, `config/default.py` being a dataclass, and keeping upstream merges easy.
3. These parts of `AGENTS.md` are the owner's own tooling. Skip them: `core ...` commands, `bd` (beads), Website Maker, and deploying. Don't deploy. The owner deploys to Cloud Run after merging.
4. Before each commit, run the new tests plus the whole test file you touched: `PYTHONDONTWRITEBYTECODE=1 python -m pytest test/<file> -q -p no:cacheprovider`. About 9 tests across the suite need live GCP credentials and fail locally. That's expected, so don't "fix" them. Never commit with a test you caused to fail.
5. Commit 7 says to confirm the cause first. If you have no access to the Cloud Run logs, write the mocked-response test and make the guard defensive (skip only parts where `part.thought` is true). Say in the PR that it hasn't been confirmed live.
6. Line numbers are as of commit `ac37ddbe` and may have drifted. Search for the function names given.
7. Run the app locally with `uv run src/main.py` and check each UI change in a browser at 1440 px and 390 px, in light and dark. Put a screenshot in the PR description.
8. In each PR, list what you changed, the test output, and anything you skipped or couldn't verify.

---

Why this plan exists: the owner's live Cloud Run test of Image Studio and Video Studio (2026-11-17) turned up problems. The lead item, prompt settings sync, is shared across the studios. This lists the cause, the fix, the risk to upstream merges and the priority for each. Planning only: no code has changed yet.

**Read this first:** `/nano-banana` is rendered by `src/pages/gemini_image_generation.py`, not `src/pages/banana_studio.py`. Banana Studio is the separate `/banana-studio` route and is not in the nav. All line numbers below are under `src/`.

## Summary

| # | Issue | Confirmed? | Priority |
|---|---|---|---|
| 1 | **Settings typed in the prompt box never update the controls** (Image Studio *and* Video Studio): see the lead section below | Yes | **P1**: shared fix |
| 2 | Two near-identical images per run | Likely cause found (thought images saved as results) | **P1**: costs money, confuses users |
| 7a | Prompt templates loaded from Firestore on every render | Yes | **P1**: slow on every interaction |
| 7b | "Suggest edits" builds a broken GCS URI with signed URLs | Yes, depends on deploy mode | **P1** if the deploy uses signed URLs |
| 3 | "Keep going" presets don't fit the image | Yes | P2 |
| 4 | "Omni" button goes to a hidden page | Ruled out; real problem is a duplicate button | P3 |
| 6 | Recent captions cut off with no way to read the full prompt | Yes | P3 |
| 7c | Snackbar sleeps 3 s inside the generation handler | Yes | P3 |
| 5 | Clipped overlay in the bottom-right corner | Not from the app | none (verify only) |

---

## 1. Prompt settings sync, shared across studios (P1, lead item)

**What the owner saw.** In Image Studio, the prompt said "at 16:9" but the aspect-ratio chip stayed at `1:1`, so the result was 1024x1024 (screenshots 1–3). In Video Studio the prompt said "…8 seconds, 16:9, Generate audio on." The result was 16:9, 720p, 8 s on Gemini Omni 1.2 Flash, but only because those were already the defaults (screenshots 4–5). The typed text never touches the controls. Omni has no audio chip at all, so the owner couldn't tell whether "audio on" was honoured.

**Cause.** Every studio reads its settings only from its chips. Image Studio sends `state.aspect_ratio` as `image_config.aspect_ratio` (`pages/gemini_image_generation.py:1179`, `models/gemini.py:175`). Video Studio does the same with `aspect_ratio`, `resolution`, `video_length` and `generate_audio` from `PageState` (`pages/veo.py:524-604`). The model config always overrides the prompt, so words like "16:9" in the text do nothing. For Omni, `_veo_chips` returns before the audio chip because `supports_advanced` is false (`pages/veo.py:583-585`). Omni always makes sound, but the UI never says so.

### Inventory: which pages have which controls, and what people type

All four composer pages share `components/composer/composer.py` (prompt card) and `components/composer/chip_menu.py` (chips). Story Studio uses its own form.

| Page (file) | Controls | Likely to be typed in the prompt | Parse? |
|---|---|---|---|
| Image Studio (`pages/gemini_image_generation.py:293-386`) | Model, Aspect ratio (per model: 15 on 2.1), Image size `1K/2K/4K`, Number of images (shown only if `max_output_images > 1`; 2.1 = 1), Search toggle | "16:9", "square/landscape/portrait", "4K", "2 images / 3 options" | **Yes**: aspect, size, count |
| Video Studio (`pages/veo.py:524-604`) | Model, Aspect ratio, Resolution, Length, Number of videos (if `max_samples > 1`), Generate audio (Veo 3.x only), Advanced (seed, negative prompt, people) | "16:9 / 9:16", "720p / 1080p / 4K", "8 seconds / 8s", "2 videos", "with sound / no audio / silent" | **Yes**: aspect, resolution, duration, count, audio |
| Music (`pages/lyria.py:276-310`) | Model, Number of tracks (`sample_count`), Lyrics toggle (`show_lyrics`) | "2 tracks", "instrumental / no vocals" | **Yes**: count, instrumental → lyrics off |
| Voice (`pages/voice.py:203-291`) | Model, Voice(s), Language, Speaking style, Pace, Dialogue, Pronunciations, Direction | (the box *is the script*) | **No**: the text is spoken word for word, so removing "slowly" or "in Arabic" would change what gets said |
| Story Studio (`pages/story_studio.py:712-830`, own form) | Language, Who speaks, Scenes, Scene length, Aspect ratio, Camera motion, Style | "3 scenes", "16:9" in "Your idea" | Later (v2): same parser, different hook |

Models stay out of v1. Switching models from text ("use Veo 3") changes cost and quota, so it stays a chip-only choice.

### Recommended approach: (a), a shared deterministic parser on submit with an undo notice

- **(a) Parser plus notice (recommended).** It is instant, free and predictable, the result is visible, and it fixes what the owner hit. Tests can pin its behaviour.
- **(b) A hint under the box only.** It tells people to use the chips but still ignores what they typed, so this exact surprise keeps happening. Use it only as a supplement: change the composer hint to "Set size, length and sound with the chips below".
- **(c) Send it through the Gemini prompt rewrite.** It adds 1–3 s and a paid call to every submit, isn't deterministic, needs structured output plumbing, and can't be unit-tested reliably. Rejected.

### Rules

1. **When text and a chip disagree, the text wins**, but only for an explicit value the current model supports. The typed text is the newest and most specific thing the user asked for, and the run uses it right away. The notice names the change and the old value: "Made at **16:9** from your prompt (was 1:1) · Undo". **Undo** puts the chips back for the next run. It doesn't cancel the run in progress, which we say plainly.
2. **Values the model can't do are snapped to the nearest supported one and explained, never silently dropped.** Limits come from the existing per-model configs, not new tables: Video Studio's `limits(model, mode) -> StudioLimits` (`config/video_studio_models.py:~145`, with `durations`, `aspect_ratios`, `resolutions`, `max_samples`, `supports_audio_toggle`, built from `config/omni_models.py` min/max duration, resolutions and aspects). Image Studio uses `GeminiImageModelConfig` (`supported_aspect_ratios`, `supported_image_sizes`, `max_output_images`). Lyria uses its model config's `max_samples`. Examples:
   - "12 seconds" on Omni 1.2 Flash (3–10 s) → 10 s, "Omni 1.2 Flash goes up to 10 s".
   - "4K" on a 720p-only Omni model → left at 720p, "This model makes 720p only".
   - "2 images" on Nano Banana 2.1 (max 1) → 1, "This model makes one image at a time".
   - "with sound" on Omni → no change, "Omni always adds sound". "no audio" on Omni → "Omni can't make silent video".
3. **Strip the matched setting phrases from the prompt sent to the model; keep the box text as typed.** The config already carries those values, and leftover text can conflict with them (for example "16:9" left in the text while the config says 9:16 after an undo, or Image Studio's own "Give me N images" suffix). Only exact matched spans are removed, plus a tidy-up of dangling commas. The Library stores the prompt that was sent, as it does today (`MediaItem.prompt`). Recent and "reuse" keep the typed text.
4. **Avoid false positives.** Ratios match only as standalone tokens (`16:9`, `16x9`, `16 by 9`) bounded by start/end, punctuation, or the words "at", "in", "aspect (ratio)", and only when the ratio is one the model supports. Durations need a unit (`8s`, `8 sec`, `8 seconds`). Counts need the page's noun (`images/options/pictures`, `videos/clips`, `tracks/songs`). Audio needs a clear phrase ("audio on/off", "with/without sound", "no audio", "silent"). "A 16:9 TV on the wall" therefore doesn't match: it is followed by a noun, not a boundary. Undo covers what slips through.
5. **Parse on submit only** (Enter and the send button both run the same handler). Parsing on every keystroke would cost a server round trip per key in Mesop. Parsing on blur would miss Enter-to-send.

### Shared code (small hooks in each page)

- **`src/common/prompt_settings.py`** (new, pure Python, no Mesop):
  - `parse(text, kinds: set[str]) -> list[Match]`, where `Match(kind, value, span)` and kinds are `aspect`, `image_size`, `resolution`, `duration`, `count`, `audio`, `instrumental`.
  - `fit(matches, limits: SettingLimits) -> list[Applied | Skipped]` snaps values to the limits and writes the notice text.
  - `strip(text, matches) -> str`.
  - `SettingLimits` is a small dataclass, with converters `from_studio_limits(StudioLimits)` and `from_image_config(GeminiImageModelConfig)`. It sits next to the configs so nothing in `config/` changes shape.
- **Composer** (`components/composer/composer.py`): add optional `notice: str = ""` and `on_notice_undo` params that render a small chip under the box where the hint sits now (`:169-171`). The change is additive with default-off behaviour, so other pages are unaffected.
- **Per-page hook** (about 10 lines each, in the submit handler before the existing generate call): `_generate_and_save` (`pages/gemini_image_generation.py:1148`), `on_click_veo` (`pages/veo.py:1061`), and `on_click_lyria` (`pages/lyria.py`). Each one builds `SettingLimits` from its config, calls `parse → fit`, writes the applied values into its own `PageState` fields, keeps the previous values in a `settings_undo_json` string field for Undo, sets `notice`, and passes `strip(...)` to the model.
- **Omni sound is now visible:** in `_veo_chips`, before the `supports_advanced` early return (`pages/veo.py:583`), render a disabled, checked "Sound: always on" chip for Omni (`chip_menu(kind="toggle", checked=True, disabled=True)`). This needs no new component.

**Upstream risk.** Low to medium. The parser and the composer params are new or additive. The per-page hooks are about 10 lines in the submit handlers that upstream also edits, so expect small, easy conflicts. No config files change shape.

**Tests (`test/test_prompt_settings.py`).** Ratio forms and boundaries, including the "16:9 TV" false positive. Durations with and without units. Counts per noun. Audio on, off and silent. Snapping against Omni Flash, Omni 720p-only, Veo 3.x and Nano Banana 2.1 limits, built from the real configs. Stripping keeps the rest of the sentence intact. Kinds the page doesn't ask for are ignored, so Voice never parses. Per AGENTS.md, patch `cfg` as a callable where needed.


## 2. Two near-identical images per run (P1)

**Cause.** The run used the defaults: Nano Banana 2.1, count "Auto" (`num_images_to_generate = 0`, `pages/gemini_image_generation.py:143`), and `candidate_count=1` (`:1182`). The count chip is hidden because the model config sets `max_output_images=1` (`config/gemini_image_models.py:165`, check at `pages/gemini_image_generation.py:336-337`). So the UI never asks for two images. The parser in `models/gemini.py:252-281` handles a part's `thought` flag only for text. Its `if part.inline_data:` branch (`:262`) runs for **every** image part, including the interim "thinking" images that Gemini 3-family image models send before the final one (2.1 has `supports_thinking=True`). The interim draft and the final image both get saved to GCS and Firestore and shown as two results. That fits what the owner saw: two almost identical frames.

**How to confirm before fixing.** Cloud Run logs print `generate_image_from_prompt_and_images: N parts` (`models/gemini.py:249`). Log the `thought` flag of each image part once, or run `scripts/spikes/` style probes. If the second image is not a thought part, the model is returning two finals for "Auto". In that case use fallback (b) below.

**Fix.**
- (a) In `models/gemini.py`, skip `inline_data` parts where `part.thought` is true (keep the thought text in `all_thoughts`). This is a one-line guard. It is an upstream bug too, so offer it upstream.
- (b) Make the page default `num_images_to_generate` to `1`, not `0`/Auto, whenever `max_output_images == 1`. If the model still returns more than the requested count, keep the last image and drop the rest (`pages/gemini_image_generation.py:1225`).
- Add a test in `test/` that mocks a response with a thought image followed by a final image and asserts only one URI is returned.

**Upstream risk.** Low. The guard is small, sits in shared model code, and upstream would want it.

## 7a. Templates loaded from Firestore on every render (P1)

**Cause.** `_render_next_steps` calls `get_all_image_presets()` on every render (`pages/gemini_image_generation.py:517`), and so does every preset click (`:1050`). That function calls `prompt_template_service.load_templates(...)` (`:99`), which reads the JSON file and runs a Firestore query (`common/prompt_template_service.py:~84-90`). Mesop re-renders on every `yield`: each progress step, the snackbar's two yields, every chip change. So one generation triggers about 8 Firestore queries plus file reads, all while the user waits.

**Fix.** Cache `get_all_image_presets()` at module level with a short TTL (about 60 s), or load it once in `on_load` into state, as `pages/banana_studio.py:1372-1383` already does. The TTL cache is the smaller change and keeps admin-added templates appearing within a minute.

**Upstream risk.** Low. The change is page-local and about 10 lines.

## 7b. "Suggest edits" builds a GCS URI by string replace (P1 if signed URLs)

**Cause.** `on_suggest_transformations_click` builds `gs://` + `display_url.replace('/media/', '')` (`pages/gemini_image_generation.py:1030`). That only works when `USE_MEDIA_PROXY=true`. With signed `storage.googleapis.com` URLs (`common/utils.py:177-186`) the URI is garbage and the user sees "Failed to get suggestions". It also always uses image `[0]`, not the selected image.

**Fix.** Use `https_url_to_gcs_uri(state.selected_image_url or state.generated_image_urls[0])`, the same helper the rest of the page uses. Check which mode the Cloud Run service uses, so you know whether the owner is hitting this now.

**Upstream risk.** Low. It is a one-line change.

## 3. "Keep going" presets don't fit the image (P2)

**Cause.** `_render_next_steps` (`pages/gemini_image_generation.py:515-539`) shows **every** preset from `config/banana_presets.py` (`IMAGE_ACTION_PRESETS`: edit and creative), merged with `config/image_prompt_templates.json` and Firestore templates. There is no filtering. Person-only actions (hairstyle-bob, 80's highschool headshot, professional headshot, labubu, trollify, restore & colorize) appear on a coffee cup.

**Fix (recommended, cheap and no extra model call).**
- Add an optional `subject` tag to presets (`"person"`, `"any"`; default `"any"`) in our copies of `banana_presets.py` and `image_prompt_templates.json`, plus an optional `subject: str | None = None` field on `PromptTemplate` (`common/prompt_template_service.py:34`).
- Show only `edit` actions plus a short `creative` set by default. Put the rest, including all `person` presets, behind a "More styles" expander (`me.expansion_panel`). This stays useful without detecting anything.
- Optional later step: decide "has a person" from the caption the model already returns, or from one cheap Gemini Flash classification run once per image and cached by URL, then show person presets inline only when true. Leave this out of the first pass.

**Upstream risk.** Medium. The config files and the template schema are upstream-owned. Adding an optional field and the expander keeps the diff additive, and merges will only conflict if upstream edits the same preset lists.

## 4. "Omni" button (ruled out; P3 follow-up)

**Finding.** `components/omni_button/omni_button.py:26` sends the user to Video Studio (`VIDEO_STUDIO_PATH = "/veo"`, `config/video_studio_models.py:37`) with `veo_model=<omni>` preselected. It does **not** go to the hidden `/gemini-omni` page, so nothing breaks.

**Real problem.** "Omni" and "Veo" are two buttons that both open Video Studio, just with different models preselected. "Omni" means nothing to a client.

**Fix.** Replace both with one "Make a video" button that opens Video Studio with the default model, in the page at `:512-513`, or relabel them "Video (Omni)" and "Video (Veo)". Check that Video Studio still honours `veo_model=` when `SHOW_LEGACY_PAGES` is off.

**Upstream risk.** Low. The change is page-local and the components stay untouched.

## 6. Recent captions are cut off (P3)

**Cause.** `.prompt` in `components/result_grid/result_card.js:216-219` clamps captions to 2 lines with no tooltip and no expand.

**Fix.** In the shared card, set `title=` (the full prompt) on the caption and show the full prompt under the image in the lightbox (`pages/gemini_image_generation.py:688-701`). The card's "reuse" action already copies the prompt. Because the card is shared, this fixes every studio that uses `result_grid`.

**Upstream risk.** Low. `result_card` is our own fork component.

## 7c. Snackbar sleeps 3 s inside the generation handler (P3)

**Cause.** `show_snackbar` calls `time.sleep(3)` (`pages/gemini_image_generation.py:1126`), and it is `yield from`-ed at the end of `_generate_and_save` (`:1267`, `:1293`). The generation handler stays busy for 3 s after the image appears, and Mesop queues the user's next click behind it. Per-image C2PA reads and `get_image_resolution` (`:1228-1236`) also run synchronously before the result shows.

**Fix.** Drop "Automatically saved to library." (the Done step of the progress card already says it), or make the snackbar dismiss on the next interaction instead of sleeping. Show the image before reading C2PA and the resolution: yield once after `generated_image_urls` is set.

**Upstream risk.** Low.

## 5. Clipped overlay in the bottom-right corner (no app fix)

**Finding.** The app's only toast is `components/snackbar.py`, which is fixed at bottom-centre with a light `on-surface-variant` background. The only other fixed layers are dialogs, the lightbox and the `.gm-aurora` backdrop (`assets/ui/studio.src.css:673`). No app component renders a dark-blue panel with an orange icon at the right edge. Screenshot 2 is also cropped narrower (1298 px) than the others, which explains why the page "looks shifted". This is most likely a browser extension or OS notification.

**Action.** Reload the live page in a clean browser profile at 1440 px and confirm the panel is gone. No code change.

## Also checked

- **Layout at 390 px:** `.gm-latest-split` is one column below 1100 px (`assets/ui/studio.src.css:557-565`), and presets wrap. No obvious overflow in code. After the fixes, run `audit_page` on `/nano-banana` at 390 and 1440 in light and dark (Website Maker loop) as proof.
- `pages/banana_studio.py` has its own copies of the presets and count code. Leave it alone, since it is not in the nav.

## Commits (in order, each small and tested)

Prompt settings sync (lead):

1. `feat(common): prompt_settings parser with per-model limits`: `src/common/prompt_settings.py` (parse, fit, strip, `SettingLimits` converters) plus `test/test_prompt_settings.py`. No UI yet.
2. `feat(composer): optional notice chip with undo under the prompt box`: additive params, off by default.
3. `feat(image-studio): apply aspect, size and count typed in the prompt`: hook in `_generate_and_save`, undo state, stripped prompt to the model.
4. `feat(video-studio): apply aspect, resolution, length, count and sound typed in the prompt`: hook in `on_click_veo`.
5. `feat(video-studio): show "Sound: always on" for Omni`: disabled chip in `_veo_chips`.
6. `feat(music): apply track count and "instrumental" typed in the prompt`: hook in `on_click_lyria`.

Image Studio:

7. `fix(gemini): skip thought images when parsing image responses`: guard in `models/gemini.py` plus a test with a mocked thought and final part. (Confirm in logs first.)
8. `fix(image-studio): default to one image when the model returns one`: count defaults to 1 and extra parts are dropped.
9. `perf(image-studio): cache prompt presets instead of loading them on every render`: TTL cache around `get_all_image_presets()`.
10. `fix(image-studio): suggest edits uses the selected image's real GCS URI`
11. `feat(image-studio): show core presets first, more styles behind an expander`: optional `subject` tag and expander.
12. `refactor(image-studio): one "Make a video" button instead of Omni and Veo`
13. `fix(result-card): full prompt on hover and in the lightbox`
14. `perf(image-studio): show the result before C2PA and resolution reads; no 3 s snackbar sleep`
15. Docs: the feature test plan says "set the chip to 16:9" and adds a "typed settings" check per studio.

Later (v2): the same hook in Story Studio's "Your idea" (scenes, scene length, aspect).

After 1–10 are merged, the owner redeploys and re-runs: "…8 seconds, 16:9" in Video Studio on a 9:16 / 4 s setup should switch the chips and show the notice; Image Studio should make one image per run at the typed ratio; "Suggest edits" should work.
