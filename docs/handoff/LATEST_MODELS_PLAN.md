# Plan: use the newest Google models across GenMedia (retire Veo)

For: Matheo's Claude. Written 2026-11-18 from the owner's session.
Repo: `ProjectZero02/creative-studio` (public fork of `GoogleCloudPlatform/genmedia-creative-studio`). The core app lives in `src/`.

## The ask

The owner said:

> "we should use the latest of all google models for this software, if omni is the newest and best we should use that and retire veo. same with the image and rest of the AI suite"

So: for every AI job in the app, use the newest and best Google model on Vertex AI, and make Gemini Omni the video model everywhere instead of Veo.

## Who owns what (avoid merge conflicts)

| Work | Owner | Branch |
|---|---|---|
| Story Studio (`/story`) on Omni, the two audio types, the timeline editor | the owner's session | `feat/story-studio-sound-and-editor` (+ `claude/story-omni-*`, `claude/story-editor-*`) |
| Site-wide button, outline and layout consistency | the owner's session | `claude/ui-consistency-*` |
| **Everything in this file** | **you** | branch off `main`, e.g. `feat/latest-models` |

**Do not edit these:**
- `src/services/story_*.py`
- `src/pages/story_studio.py`
- `src/components/story_studio/*`
- the `STORY_*` fields in `src/config/default.py`
- the shared theme files (`src/assets/ui/studio*.css`)

If you need `config/default.py`, keep your hunks small and away from the `STORY_*` block.

## Where things stand

### Already on Omni

- `INTERIOR_DESIGN_VIDEO_MODEL` and `OBJECT_ROTATION_VIDEO_MODEL` default to `gemini-omni-1.2-flash`. Routing happens in `src/models/workflow_video.py`.
- `OMNI_MODEL_ID` / `DEFAULT_OMNI_MODEL_NAME` is `gemini-omni-1.2-flash`, and the registry is `src/config/omni_models.py`. Omni 1.2 Flash supports these modes:
  - t2v, i2v, first/last frame, ref2v (up to 10 images), edit, extend, upscale;
  - clip length 3–15 s; 16:9 and 9:16; 360p to 4k.

### Still on Veo

From `src/config/default.py` and grep:
- `DEFAULT_VEO_MODEL_NAME`, `VEO_MODEL_ID`, `VEO_EXP_MODEL_ID`, `VEO_EXP_FAST_MODEL_ID` (`veo-3.1-*`), with the registry in `src/config/veo_models.py`.
- `CHARACTER_CONSISTENCY_VEO_MODEL` = `veo-3.1-fast-generate-001`.
- Code that calls Veo:
  - `src/models/veo.py`, `src/services/veo_service.py`, `src/pages/veo.py`;
  - `src/models/storyboard_video.py` and `src/pages/storyboarder.py`;
  - `src/models/shop_the_look_handlers.py`;
  - `src/models/character_consistency.py`;
  - `src/services/live_agent.py` and `src/services/live_jobs.py` (`DEFAULT_VEO_VERSION_ID`);
  - `src/pages/portraits.py`;
  - `src/pages/home.py` / `src/pages/welcome.py` / `src/pages/library_v2.py` (labels and links).
- `src/config/navigation.json` has no Veo entry by name. Check which pages it routes to `pages/veo.py`.

### Other models to check

| Job | Config | Current default |
|---|---|---|
| Text / chat | `MODEL_ID` | `gemini-3.5-flash` |
| Live (voice agent) | `LIVE_MODEL` | `gemini-3.8-live` |
| Image | `GEMINI_IMAGE_GEN_MODEL`, `INTERIOR_DESIGN_IMAGE_MODEL`, `OBJECT_ROTATION_IMAGE_MODEL` | `gemini-nano-banana-2.1` |
| Audio analysis | `GEMINI_AUDIO_ANALYSIS_MODEL_ID` | `gemini-3.1-flash-lite` |
| Writers workshop | `GEMINI_WRITERS_WORKSHOP_MODELS` / `_MODEL_ID` | `gemini-4-argon`, `gemini-3.8-flash` |
| Storyboarder narrative | `GEMINI_STORYBOARDER_NARRATIVE_MODELS` / `_MODEL_ID` | `gemini-3.8-flash`, `gemini-4-argon`, `gemini-3.5-flash-lite` |
| Critique | `GEMINI_CRITIQUE_MODEL_ID` | `gemini-3-flash-preview` |
| Music | `LYRIA_MODEL_VERSION` | `lyria-002` |
| Virtual try-on | `VTO_MODEL_ID` | `virtual-try-on-001` |
| TTS (story only, not yours) | `STORY_TTS_MODEL` | `gemini-2.5-flash-tts` |

The newest models were **not verified** for any row. Check each one against the current Vertex docs and Model Garden. Cite the page and confirm the ID is served in the app's region before switching. In particular:
- `gemini-3-flash-preview` and `gemini-3.1-flash-lite` look old next to the 3.8 / 4 models;
- `lyria-002` may have a newer Lyria;
- the TTS models may have newer Gemini TTS versions.

### A partial start you can reuse

A session began this work and was stopped. Its uncommitted diff is in `docs/handoff/latest-models-partial.patch`, applied against `main`; apply it with `git apply`. It does three things:
1. Adds `SHOW_VEO_MODELS` (default false) to hide Veo from the video model pickers while keeping it available.
2. Switches `CHARACTER_CONSISTENCY_VEO_MODEL` to `gemini-omni-1.2-flash`, and routes `models/character_consistency.py` through `models/workflow_video.generate_workflow_image_to_video` when the name is an Omni model (Veo path kept for `veo-*` names).
3. Edits `models/workflow_video.py`. Review that part; the patch shows the hunks.

## Research you can rely on (cited)

- **Omni vs Veo for consistent speech.** Nothing documented makes Veo keep one voice across clips:
  - the Veo extend docs say nothing about voice ([Vertex: extend a Veo video](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/video/extend-a-veo-video));
  - a third-party test found no voice consistency even with a fixed seed ([ndurner](https://ndurner.substack.com/p/google-veo-31)).
- **Omni multi-turn keeps the voice.** Continuing a generated video with `previous_interaction_id` is documented as supporting voice-preserving extension ([Gemini API Omni docs](https://aistudio.google.com/docs/omni)).
- **Omni limits:**
  - extension adds 3–10 s per turn and uses the last 10 s of input;
  - total length is up to 30 s (Gemini API docs) or 40 s on Vertex ([Vertex extend](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/video/extend-videos.md.txt));
  - stored interactions last 7 days ([Vertex text-to-video](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/video/generate-videos-from-text.md.txt));
  - first clips are 3–15 s on 1.2 Flash ([references](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/video/generate-videos-from-references.md.txt)).
- **Omni API quirk (verified live in this repo).** The Interactions API rejects `previous_interaction_id` together with a video `task` ("previous_interaction_id is not allowed when video task is set"). See the comment in `src/models/omni.py`.
- **Omni seed.** `generation_config.seed` is supported ([Vertex video overview](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/video/overview)), but `models/omni.py` does not pass it yet.
- **Voice references.** Omni voice or audio references exist only on Vertex, and appear to be allowlist-gated (unconfirmed) ([Omni 1.2 launch post](https://blog.google/innovation-and-ai/technology/developers-tools/introducing-gemini-omni-1-2-flash/)). Don't build on them.

## Plan

1. **Inventory and verify.**
   - For every row above and every Veo call site, record the job, the current model, the newest Google model for that job, and a source link.
   - Put the table in the PR description.
   - Probe only with free calls (metadata or list-models). Ask the owner before any paid generation.
2. **Video → Omni.** For each Veo call site, route through `models/workflow_video.py` (or `models/omni.generate_omni_video`) when the configured model is an Omni name. Keep the Veo branch for `veo-*` names so upstream merges stay easy.
   - Map modes: t2v → `t2v`, image → `i2v`, first/last frame → `first_last`, reference → `ref2v`, extend → `extend`.
   - Omni durations differ from Veo's 4/6/8; use `config.omni_models.clamp_duration`.
   - Change the `*_VEO_MODEL*` defaults to `gemini-omni-1.2-flash`. Leave the env-var names alone, so existing Cloud Run env still works.
   - Point the `/veo` page and the Live agent's video tool at Omni (or hide the Veo page behind `SHOW_VEO_MODELS` / `SHOW_LEGACY_PAGES`). Update home and welcome cards and labels that say "Veo".
3. **Image, text, music, try-on.** Switch each default to the verified newest model. Update model pickers that list choices, such as the workshop and storyboarder tuples.
4. **Docs.** Follow AGENTS.md "Adding or Changing an Omni Model" for every place an ID lives. Update `docs/environment_variables.md`, and the docs-site pages when defaults change.
5. **Tests.**
   - Update tests that assert old defaults (remember `Default` is a dataclass; assert on `Default.__dataclass_fields__[name].default`).
   - Add mocked tests for the new Omni routing.
   - Run from a venv outside the repo with `PYTHONDONTWRITEBYTECODE=1 ... -m pytest -q -p no:cacheprovider`.
6. **Check in the browser.** Open one page per changed model in mock or demo mode (`.claude/launch.json` has launch configs; `GENMEDIA_MOCK_GENERATION=true`).

## Rules (from the owner)

- Commit as **ProjectZero02**, with no Claude or AI co-author lines and no "Generated with" footer.
- Ruff only on files you changed, using `ruff check --select F,E9,B <files>` and `ruff format --diff` first. Never run ruff on `.`.
- Don't deploy; the owner deploys to Cloud Run. Ask the owner before anything that costs money (paid model calls, min instances, GPUs).
- UI copy is short and plain. Sibling controls are the same size. Use tonal buttons, not bright outlines.
- Push the branch and open a PR into `main` of `ProjectZero02/creative-studio`.

## Done means

- Every AI job runs on a verified newest model, with a cited table in the PR.
- Veo is no longer a default anywhere, but is still available behind config.
- Tests are green, and ruff passes on changed files.
- Changed pages are checked in mock mode.
- The PR is open.
