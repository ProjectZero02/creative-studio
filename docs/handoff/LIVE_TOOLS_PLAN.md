# Live agent: music, voice and Story Studio tools

Repo: `ProjectZero02/creative-studio`. Branch from the latest `main` (`git fetch origin && git checkout -b feat/live-media-tools origin/main`). Copy this file into `docs/handoff/LIVE_TOOLS_PLAN.md` in your first commit.

## Where things stand

The Live voice agent (the mic button on every page) is built for **images and videos only**. See `docs/LIVE_AGENT_PLAN.md` for how it works. In short:

| File | Role |
|---|---|
| `src/services/live_jobs.py` | Background jobs, one thread each, spoken names ("image 1"), a per-person limit, mock and real runners. `KINDS = ("image", "video")`. |
| `src/services/live_agent.py` | Tool declarations, system prompt, `LiveCall` (one method per tool: `_tool_<name>`), and the typed `ScriptedAgent` for offline demos and tests. |
| `src/routers/live_router.py` | `WebSocket /api/live`: the Gemini Live session, relays audio, sends job results back with `WHEN_IDLE`. |
| `src/components/live_agent/live_agent.js` | `window.gmLive`: mic, speaker, call dock, captions, job tray, result viewer (image or video only), cursor overlay. |
| `test/test_live_agent.py` | Offline tests for jobs, tools and the WebSocket route. |

Job tools are `NON_BLOCKING`: they start a job and the agent keeps talking; the result arrives when the job finishes. Screen tools (`open_page`, `show_job`, `download`, `end_call`) run in the browser.

## What is missing (your job)

1. **Music** (Lyria): `generate_music`.
2. **Voice** (TTS): `generate_voice`.
3. **Story Studio**: start a film from an idea and move it along by voice.
4. The tray, result viewer and download for **audio** results, and story results.
5. Offline (`ScriptedAgent`) and mock support for all of the above, so it demos with `?live=offline` and `GENMEDIA_MOCK_GENERATION=true` at no cost.

## Files: what you may touch

Someone else is working on Story Studio at the same time (the timeline editor and the Story pages). To avoid merge conflicts:

**Yours (edit freely):**
- `src/services/live_jobs.py`
- `src/services/live_agent.py`
- `src/routers/live_router.py` (only if needed)
- `src/components/live_agent/live_agent.js` and `live_agent.py`
- `test/test_live_agent.py`
- New files you create, e.g. `src/services/live_story.py`, `test/test_live_story.py`
- `docs/LIVE_AGENT_PLAN.md` (update its status and tool table at the end)

**Shared (add lines only, in the Live block, nothing else):**
- `src/config/default.py`: new settings go in the "Live voice agent" block (next to `LIVE_MODEL`). Do not reorder or reformat other lines.
- `docs/environment_variables.md` and `docs-site/src/content/docs/core/installation/environment_variables.md`: rows in the "Live voice agent" section only.

**Do not edit (read them, call their public functions):**
- Anything Story Studio: `src/pages/story_studio.py`, `src/services/story_*.py`, `src/components/story_studio/*`, `src/state/story_state.py`, `src/assets/ui/story.css`, `test/test_story_*.py`.
- The studio pages: `src/pages/lyria.py`, `src/pages/voice.py`, `src/pages/banana_studio.py`, `src/pages/veo.py`. Mirror what they do in your runners instead.
- `src/components/page_scaffold.py`.

If you need a change in a "do not edit" file (for example a new public helper in `story_jobs.py`), don't make it: write it under "Needs from Story Studio" in the PR description and work around it.

## Steps (one commit each)

### 1. Music jobs
- `live_jobs.py`: add `"music"` to `KINDS`. A real runner `_real_music` that calls `models.lyria.generate_music_with_lyria(prompt, model_name=Default().LYRIA_MODEL_VERSION, lyrics=...)`, stores and records the result the way `pages/lyria.py` does (around lines 700 to 850: GCS path, `MediaItem` with `mime_type="audio/wav"`, `add_media_item_to_firestore`). A mock runner using `common.mock_generation.fake_wait` and `sample_audio(index)`.
- Handles read "music 1", "music 2". Check `LiveJobs.resolve` and `job.handle` handle the new kind.
- `live_agent.py`: declare `generate_music(prompt, lyrics?)` as a job tool (`NON_BLOCKING`), add `"music": "/lyria"` to `JOB_PAGE`, and `_tool_generate_music`. Tell the agent in `SYSTEM_PROMPT` when to use it.
- Tests: a music job runs in parallel with an image job; the tool returns a deferred result; mock runner gives a playable URL.

### 2. Voice jobs
- `live_jobs.py`: add `"voice"`. Real runner builds a `models.voice.VoiceRequest` (engine, text, voice, language_code; use the same defaults as `pages/voice.py`), checks it with `models.voice.validate`, calls `synthesize_voice`, saves with `common.storage.store_to_gcs` (folder `voice-audio`, `audio/wav`) and a `MediaItem`, like `pages/voice.py` (around line 650). Mock runner: `sample_audio`.
- `live_agent.py`: `generate_voice(script, voice?, language?)` job tool, `"voice": "/voice"` in `JOB_PAGE`. List the allowed voice names in the tool description (from the voice config the Voice page uses) and fall back to the default on an unknown name instead of failing.
- Tests as in step 1.

### 3. Audio in the browser
- `live_agent.js`: the job tray card and result viewer show an `<audio controls>` player for `audio/*` results (today they only know `<img>` and `<video>`, around line 320). Download works for audio (`.wav` name).
- `show_job` for music and voice opens `/lyria` or `/voice`; the page does not need to show the job (v1 rule: no studio page changes). The viewer overlay plays it.
- Check it in the browser in offline mode (`?live=offline`, mock generation on): "make some calm piano music", "say welcome to the demo in a warm voice", play both from the tray, download one.

### 4. Story Studio tools (`src/services/live_story.py`)
Story Studio has its own job system (`services/story_jobs.py`: `start_scenario`, `start_set`, `start_storyboard`, `start_video`, `start_music`, `start_export`, `job_snapshot`, `wait`, `get_store`). Wrap it; do not copy or change it.

- A live job kind `"story"` whose runner calls one `story_jobs.start_*` function, then `story_jobs.wait(job.id, owner, timeout=...)` in a loop until the story job is done or failed, and reports the result (story id, step, film URL when there is one). Handles: "story 1".
- Tools (job tools unless marked):
  - `create_story(idea, length?, aspect_ratio?, style?, language?)`: save a new `Story` for the owner (fill settings from `services.story_autoset.infer_settings(idea)`, then the given arguments win), then start the scenario. Read `pages/story_studio.py` (`on_generate_scenario` and the Create step) to set the same fields the page sets.
  - `continue_story(story?)`: run the next step the page would run. Read the page's step order and approval rules (scenario, approve, set, storyboard, scenes, render) and mirror them: approve the scenario, build the set, paint the storyboard, then render the film. One step per call, so the presenter stays in control.
  - `render_film(story?)`: `start_video` (only when every scene has a frame; otherwise say which step is missing).
  - `story_status(story?)` (server, not a job): current step, the running job's progress from `job_snapshot`, and whether a film exists.
  - `open_story(story?, step?)` (screen tool): navigate to `/story?id=<id>&step=<step>`.
- "The story" means the latest story of this call; also accept a story title.
- Mock mode: Story Studio already has a demo backend (`STORY_STUDIO_MOCK=true`), so the same code path works offline. Use it in tests with the stores pointed at a temp dir (see how `test/test_story_studio.py` sets up `story_store.set_store`; copy the fixture, don't import from that file).
- Tests: create a story offline, continue it step by step to a film, status answers at each step, open_story sends the right URL, errors are plain ("Every scene needs a storyboard frame first.").

### 5. Offline agent
- `ScriptedAgent.handle`: understand "music of/about ...", "say ...", "make a story about ...", "next step", "render the film", "story status". Keep the existing phrases working.
- Update the offline help line.

### 6. Docs
- `docs/LIVE_AGENT_PLAN.md`: status line, the file table, the tool table, the demo lines.
- New settings (if any) in both environment variable docs, Live section.

## Rules
- Small commits, one per step above, conventional messages: `type(scope): summary` plus a short body (e.g. `feat(live): add music jobs`).
- Run tests with a venv outside the repo (see `AGENTS.md`, "Testing"). Run `test/test_live_agent.py` and your new test files in full. Run `ruff format` and `ruff check` only on files you changed, and apply only hunks on lines you changed.
- No paid calls in tests; mock every model.
- No deploys.
- **When done, push the branch and open a pull request into `main`.** Describe what changed, the test counts, what you checked in the browser, and anything under "Needs from Story Studio".
- **Do not add Claude (or any AI tool) as a co-author or contributor**: no `Co-Authored-By:` trailer for an AI, and no "Generated with ..." line in commits or the PR.

## Done when
- By voice (or typed in offline mode) you can: make an image and some music at the same time; make a voice line; start a story from an idea, move it to a finished film one step at a time, and open it on screen.
- Audio results play and download from the tray.
- All tests pass and the PR is open against `main`.
