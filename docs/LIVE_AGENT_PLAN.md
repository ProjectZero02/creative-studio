# Live Agent: a voice orchestrator on the home page

Status (2026-11-17): **v1 built.** It passes the unit tests and an offline browser run of the full demo script. It has not been tried against real Gemini Live yet; that happens on Cloud Run.

## What v1 is (lean cut of the design below)

To keep the build short, v1 drops two things from the full plan:
- **No changes to studio pages.** The agent's jobs run in a new job service and show in their own job tray and result viewer, drawn over the page. The studios' own Generate buttons work exactly as before.
- **Images and videos only.** Music and voice are left for later.

| File | What it does |
|---|---|
| `src/services/live_jobs.py` | Runs each job in its own thread, so jobs run side by side and survive page changes. Jobs have spoken names ("image 1", "video 1"), a limit of 4 running per person, and save to GCS and the Library like the studios. Mock mode gives instant placeholders. |
| `src/services/live_agent.py` | The tools, the agent's instructions, the per-call tool logic, and a typed offline agent for demos without a model. |
| `src/routers/live_router.py` | `WebSocket /api/live`. Holds the Gemini Live session on Vertex with the app's own credentials. Relays audio and transcripts. Job tools are `NON_BLOCKING`, and each result is sent back at the next pause (`WHEN_IDLE`). Reconnects with session resumption. Checks identity and origin itself. Falls back to the typed offline agent if Live can't be reached. |
| `src/components/live_agent/` | `window.gmLive`, attached to `document.body`, so the call survives `me.navigate`. It runs the mic (16 kHz) and speaker (24 kHz), the call dock with mute, typed requests and hang-up, live captions, the job tray, the result viewer with Download, and the on-screen cursor that types the prompt into the studio's box and points at Generate. One invisible bridge per page (`page_scaffold.py`) handles navigation. The big **Talk to the studio** button is on Home. |
| `test/test_live_agent.py` | 24 offline tests: parallel jobs, the job limit, handles, every tool, the WebSocket route in offline mode, and a fake Live session that checks the `WHEN_IDLE` reply. |

Settings are in `docs/environment_variables.md` under "Live voice agent". Try it without a model: add `?live=offline` to any page URL and type requests.

### First run on Cloud Run (checklist)

1. Deploy as usual. No new APIs are needed (`aiplatform.googleapis.com` is already on), and the deploy already sets a 60-minute timeout and session affinity, which WebSockets need.
2. Open Home, click **Talk to the studio**, and allow the microphone.
3. Say the demo lines from the top of this doc and watch the tray.
4. If the call drops straight into "Offline mode", the Live model isn't reachable. The Cloud Run logs say why. Usual fixes: set `LIVE_MODEL` to a Live model the project can use (for example `gemini-live-2.5-flash-native-audio`) or change `LIVE_LOCATION`.
5. If the agent goes quiet while a job runs and only speaks when it's done, set `LIVE_ASYNC_TOOLS=false`.

## The demo we are building

The presenter clicks **Call** on the home page and talks:

> "Make an image of a red fox in a snowy forest, cinematic."
> "While that's going, start a video of waves crashing on black rocks at sunset."
> "Go back to the image. Nice. Make it night time with northern lights."
> "Download that to my laptop."

The agent answers by voice. The audience watches the app move by itself: it opens Image Studio, the prompt types itself into the box, a cursor glides to Generate, and then the app switches to Video Studio while the image keeps rendering. A tray in the corner shows every running job. When the image is ready the agent says so at the next pause, goes back to it, edits it, and the file lands in the laptop's Downloads folder.

What it must do:

1. Talk with barge-in (you can cut it off mid-sentence).
2. Move around the app visibly (pages, prompt box, buttons, results).
3. Run several generations at once, all surviving page changes.
4. Remember what "the image" and "that" refer to.
5. Download to the presenter's machine.

## Research: how others do it

| Reference | What it shows | What we take |
|---|---|---|
| **Google `adk-samples` / `core/python/adk-voice-agent`** (Apache-2.0, official recipe; cloned for reading) | A Gemini Live voice agent on Vertex (ADC, Cloud Run) that starts slow background work and keeps talking. Results are spoken at the next pause. A `navigate` tool moves the React UI, and the browser reports back what is on screen. | The whole pattern: `app/voice/non_blocking.py` (slow tools reply `SILENT` at once, real result `WHEN_IDLE`), `focus.py` (server knows what is on screen), `web/src/lib/navigation.ts` (navigate runs in the browser), `live-audio-client.ts` (mic and speaker). Closest match to our case. |
| **WebClaw** (`nzaghaventures/webclaw`, README says MIT but the repo has no LICENSE file, so we copy ideas only) | A voice agent that operates any website. A FastAPI gateway holds the Live session and forwards tool calls to an embed script, which clicks and types. Each result comes back with an `action_id`. A glowing marker flies to each target. | The browser executor shape (`embed/src/dom-actions.ts`, `element-finder.ts`), the flying-cursor and highlight look (`action-visualizer.ts`), and request/response ids for UI tools. |
| **`google-gemini/live-api-web-console`** (Apache-2.0) | A React starter: AudioWorklets for 16 kHz mic capture and 24 kHz playback, and client-side tool-call events. | Audio worklet code, if the ADK sample's client doesn't fit. |
| LiveKit Agents + Gemini Live | The agent calls RPC methods registered in the browser. | Confirms the same split: the server brokers and the browser does the visible work. We don't need WebRTC or LiveKit. |

Upstream `genmedia-creative-studio` has no live or voice agent. Its `experiments/mcp-genmedia` Go MCP servers give useful tool names and argument shapes (`nanobanana_image_generation`, `veo_t2v`, `veo_i2v`, `lyria_generate_music`, `gemini_audio_tts`).

### Gemini Live facts that shape the design

- **Model on Vertex:** `gemini-3.8-live` (GA), or `gemini-live-2.5-flash-native-audio` (GA) as the fallback. Both do function calling, VAD and transcription. Audio goes in as 16-bit PCM at 16 kHz and comes out at 24 kHz.
- **Parallel tools:** async function calling is the default on Vertex (`NON_BLOCKING`). Each `FunctionResponse` has `scheduling`: `SILENT` (just note it), `WHEN_IDLE` (say it at the next pause) or `INTERRUPT`. This is what lets the agent keep talking while images and videos render.
- **Browser auth:** ephemeral tokens exist only on the Developer API, not Vertex, so the browser can't connect straight to Vertex with our ADC. **We need a server proxy.**
- **Session length:** one connection lasts about 10 minutes and gets a `goAway` 60 s before it ends. Turn on session resumption and context-window compression and a demo can run as long as needed.
- **Cost:** roughly $0.005/min of audio in and $0.018/min out (third-party numbers, still to check against Google's price page). A 10-minute demo costs cents. The image and video generations cost what they cost today.

Sources: [Vertex Live API](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/live-api), [sessions](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/live-api/start-manage-session), [async function calling](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/live-api/asynchronous-function-calling), [ephemeral tokens](https://aistudio.google.com/docs/live-api/ephemeral-tokens), [ADK streaming guide](https://adk.dev/streaming/dev-guide/part1), [WebClaw write-up](https://dev.to/zaghadon/building-webclaw-a-personal-live-ai-support-agent-that-actually-operates-websites-4238), [LiveKit tool forwarding](https://docs.livekit.io/agents/logic/tools/forwarding/).

## What the app does today (and why parallel doesn't work)

- **Image, image edit, music and voice** run inside the page's Mesop click handler (`pages/banana_studio.py:1204`, `pages/lyria.py:667`, `pages/voice.py:654`). `me.navigate` drops the page and stops the handler, so a job dies the moment you leave the page. That is why tasks can't run in parallel today.
- **Veo video** already runs in a background thread with a Firestore job (`common/veo_utils.py`, `services/veo_service.py`) and survives navigation. Omni video uses a one-worker pool inside the handler, so it does not survive.
- **Story Studio** has a real in-memory job system (`services/story_jobs.py`: `Job`/`Task`, `_spawn`, `job_snapshot`, `wait`) and a page poller (`story_ticker`). It relies on Cloud Run session affinity, which `deploy.sh` already turns on. **This is the model to copy.**
- There is no microphone, WebSocket or Live code anywhere yet.
- The app is FastAPI with Mesop mounted at `/`, served by gunicorn with Uvicorn workers, so a WebSocket route can sit beside Mesop. The CSP (`main.py:336`) allows `connect-src 'self'`, and a same-origin `wss://` should pass (to confirm in the spike).
- Pages already take prefill from the URL: `?prompt=` (`common/prompt_prefill.py`), `?image_uri=` and `?veo_model=`.
- Download already works: `/api/get_signed_url` returns a 15-minute signed URL, and `download_button.js` turns it into a file download.
- The user is known on every request (`scope["MESOP_USER_EMAIL"]`), so a WebSocket can be tied to the signed-in user.

## Design

```
 Browser (one tab)                                   Cloud Run (same service)
 ┌──────────────────────────────────────┐            ┌────────────────────────────────────┐
 │ Mesop pages (Home, Image, Video, …)  │            │ FastAPI  /api/live  (WebSocket)    │
 │   ▲ me.navigate(route, ?job=…)       │            │   LiveBridge per call:             │
 │   │                                  │  audio +   │   google-genai aio.live.connect    │
 │ live_bridge web component ──events──►│◄──JSON────►│   (Vertex, ADC, gemini-3.8-live)   │
 │   │ (one per page, thin)             │            │   ├─ UI tools → forward to browser │
 │ window.gmLive  (singleton, survives  │            │   └─ job tools → MediaJobs         │
 │   navigation; owns mic, speaker,     │            │                                    │
 │   socket, call pill, job tray,       │            │ services/media_jobs.py             │
 │   captions, cursor overlay)          │            │   per-user jobs in threads →       │
 └──────────────────────────────────────┘            │   models/* → GCS + Firestore       │
                                                     └────────────────────────────────────┘
```

### 1. Media job service (the parallel part)

A new `services/media_jobs.py`, built on `story_jobs.py`:

- Job kinds: `image` (and edit, which is image with input images), `video` (Veo, or Omni), `music`, `voice`.
- Each job runs in its own thread and calls the existing model functions:
  - `models/gemini.generate_image_from_prompt_and_images`
  - `models/veo.generate_video` / `image_to_video`
  - `models/omni.generate_omni_video`
  - `models/lyria.generate_music_with_lyria`
  - `models/voice.synthesize_voice`

  It then saves through `store_to_gcs` and `add_media_item_to_firestore`, exactly as the pages do, so results show up in the Library.
- State per job: `queued → running → done | failed`, plus prompt, settings, result URIs, error, start and end times. Jobs are kept per user in memory and mirrored to the `MediaItem` status field in Firestore.
- A cap of about 4 running jobs per user, so a demo can't run up a bill.
- Each job has a short handle for speech: "image 1", "video 1", "image 2 (edit of image 1)".
- `subscribe(user)` gives an asyncio queue of job events for the Live bridge.
- **The studios use it too.** Image, Music, Voice and Omni video submit to the service instead of generating inside the click handler. Each page shows its jobs from the service through a small poller (the `story_ticker` pattern). Then leaving a page no longer kills a job, even without the agent. This is the one change that edits several pages. It is about 10–20 lines per page, kept in one helper (`components/job_panel.py`) to keep upstream merges small.

### 2. Live bridge (server)

A new `routers/live_router.py` with `WebSocket /api/live`, tied to the user from the auth middleware:

- One Live session per call: `google-genai` `client.aio.live.connect(model=cfg.LIVE_MODEL, config=…)`. Settings:
  - native audio out, one voice (configurable)
  - input and output transcription on (for captions)
  - session resumption and context compression on
  - the tools listed below
- Messages to and from the browser are JSON frames: `audio` (base64 PCM chunks), `text`, `tool_call` with `call_id`, `tool_result` with `call_id`, `screen` (what page and job are open), `job_event`, `transcript`.
- **UI tools** (`BLOCKING`, run in the browser): the bridge forwards the call and waits up to about 8 s for `tool_result` with the same `call_id` (the WebClaw pattern).
- **Job tools** (`NON_BLOCKING`): the bridge submits to `MediaJobs` and replies at once with `{job: "image 1", status: "started"}` and `SILENT`. When the job finishes it sends one more message (`WHEN_IDLE`): "image 1 is ready" plus a short description. That is the `non_blocking.py` pattern from the ADK sample. While a job is running the bridge stays quiet. It only speaks if a job fails or is still running after about 60 s.
- **Grounding "that looks nice":** when an image finishes, the bridge sends the image (a small JPEG) into the session as context, so the agent has actually seen it when it says "looks great" or plans an edit.
- **On-screen focus:** the browser sends `screen` after every page change, so the agent knows what the presenter sees (from the ADK sample's `focus.py`).
- New config in `config/default.py`: `LIVE_MODEL` (default `gemini-3.8-live`), `LIVE_LOCATION` (`us-central1`), `LIVE_VOICE`, `LIVE_MAX_JOBS`, and `LIVE_AGENT_ENABLED` (feature flag, default off until it is demo-ready).

### Tools the agent gets

| Tool | Where it runs | What it does |
|---|---|---|
| `generate_image(prompt, aspect_ratio?, count?)` | server, non-blocking | New image job, then opens it on screen |
| `edit_image(source, instruction)` | server, non-blocking | Edits "image 1", "the last image" or the one on screen |
| `generate_video(prompt, from_image?, seconds?, aspect_ratio?, with_sound?)` | server, non-blocking | Veo or Omni job (image-to-video when `from_image` is set) |
| `generate_music(prompt, instrumental?)` / `generate_voice(script, voice?)` | server, non-blocking | Lyria / TTS job |
| `list_jobs()` | server | What is running and what is done, by handle |
| `open_page(page)` | browser | Home, Image, Video, Music, Voice, Library |
| `show_job(job)` | browser | Opens the studio for that job and scrolls to its result |
| `type_prompt(text)` + `press_generate()` | browser | Show-only: types into the visible prompt box and moves the cursor to Generate. The real work is the server job, so a failed animation never loses a job. |
| `download(job_or_media)` | browser | Signed URL → file saved to Downloads |
| `end_call()` | browser | Hangs up |

The system prompt keeps spoken replies short ("On it. Starting the video now."). The agent never waits silently for a job; it confirms and moves on. When a request is ambiguous it picks the job on screen, and it says which job it is acting on.

### 3. Browser side

- **`window.gmLive` singleton** (`assets/live/gm-live.js`). Loaded once and attached to `document.body` outside Mesop's render tree, so it **survives `me.navigate`**. It owns:
  - the WebSocket
  - the mic, through an AudioWorklet that turns 48 kHz into 16 kHz PCM
  - the speaker queue at 24 kHz, which stops instantly on barge-in
  - all overlays
- **`live_bridge` web component**, which every page renders through `page_scaffold.py`. It is thin: it registers with `gmLive` and turns UI tool calls into Mesop events. `open_page` and `show_job` become a Python handler calling `me.navigate(route, query_params={"job": …, "prompt": …})`. On each mount it sends `screen`.
- **Overlays:**
  - a call pill at the top (mic level, mute, hang up, a "listening / thinking / speaking" state)
  - live captions of both sides, which help the audience
  - a **job tray** with one card per job, showing a spinner and elapsed time, then a thumbnail. Clicking a card opens the job.
  - a **flying cursor and highlight ring**, styled like WebClaw's marker, used for `type_prompt` / `press_generate` / `show_job`
- **Home page as the orchestrator:**
  - The hero gets a large **Call** button next to the existing composer.
  - Text typed into the home composer while a call is on goes to the same agent as a text turn. That is the fallback for a noisy room or a blocked mic.
  - With no call, the composer works exactly as it does today.
- **Studio pages and `?job=`:** a page opened with `?job=<id>` fills its prompt box from the job, shows that job's progress card and result, and keeps polling until it finishes. This is the same helper the studios use for their own jobs.
- **Download:** reuse the `download_button.js` code (fetch the signed URL, blob, `<a download>`). Chrome allows the first scripted download and asks "allow multiple downloads?" on the second. Click Allow once before the demo.

## Build order

Each phase ends with tests passing and a localhost check in the browser. Phases 1 and 2 can run in parallel in separate sessions, because they touch different files.

| # | Phase | Done when |
|---|---|---|
| 0 | **Spike (½–1 day), throwaway branch.** Prove the four risky things: (a) `aio.live.connect` on Vertex with ADC and `gemini-3.8-live` in our region, voice both ways, through a FastAPI WebSocket behind our auth middleware; (b) a `NON_BLOCKING` tool with `SILENT` then `WHEN_IDLE` works on google-genai 2.22.0 (or find the version that does); (c) a `document.body` singleton keeps the call alive across `me.navigate`; (d) same-origin `wss://` passes the CSP and Cloud Run. | All four are yes, or we have a decided fallback for each |
| 1 | **Media job service** + unit tests (mocked models): parallel jobs, cap, handles, failure path, Firestore status | `pytest test/test_media_jobs.py` passes; two jobs run at once in a script |
| 2 | **Studios on jobs**: Image, Music, Voice and Omni submit to the service; `job_panel` helper; `?job=` support; Veo keeps its own runner but shows in the same tray | Start an image, leave the page, come back: it finished. An image and a music track started back to back both finish |
| 3 | **Live bridge**: router, tool schemas, UI-tool relay with `call_id`, job events → `WHEN_IDLE`, image grounding, session resumption, config flags | A text-only test client can run the demo script against the bridge |
| 4 | **Browser client**: `gmLive`, `live_bridge`, call pill, captions, job tray, cursor overlay, home Call button, text fallback, download | The full demo script works on localhost, by voice |
| 5 | **Demo polish**: Website Maker audit (call pill, tray, overlays at 1440/390, light/dark, AR); failure lines (job fails, mic denied, socket drops and resumes); a rehearsal script in `docs/` | Two clean run-throughs end to end; audit has no high items |
| 6 | **Ship**: push to `main`; the owner deploys to Cloud Run; I test the demo on the live URL | Demo works on the real URL |

## Risks and fallbacks

- **Mesop re-renders could drop the singleton.** Fallback: the browser reconnects after each page change using the session-resumption handle (about 1 s gap, audio buffered meanwhile). The spike decides which one we use.
- **Async tool scheduling differs by model or SDK version.** Fallback: plain blocking tools that return in under 1 s with a job id, plus bridge-injected text turns (`[JOB DONE] image 1`) when jobs finish. This is how the ADK sample's cascaded mode works.
- **Mesop maintenance:** the research pass reports Mesop is no longer maintained after 2026-09-30 (unconfirmed). Everything live is plain JS plus FastAPI, so it would move with the app if the UI framework ever changes.
- **Cold start in front of an audience:** open the app 1 minute before. `min-instances=1` would remove this, but it costs money, so the owner decides.
- **Cost guard:** the per-user job cap plus a per-call limit (e.g. 20 jobs) on the bridge.
- **Upstream merges:** the new code lives in new files (`services/media_jobs.py`, `routers/live_router.py`, `components/live_bridge/`, `components/job_panel.py`, `assets/live/`). Existing files only get small hooks (scaffold, home hero, one submit call per studio).

## Open questions (with the answer I'll use unless told otherwise)

1. Voice for the agent: a neutral Gemini Live voice, configurable later.
2. Languages: English first. Arabic speech works with the same model and gets tested in phase 5.
3. Where it shows: every page has the call pill, and the Call button is on Home only.
4. Feature flag off in production until phase 5 passes.
