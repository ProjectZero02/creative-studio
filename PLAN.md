# PLAN: GenMedia Studio (client-demo fork)

**Goal.** A faster, more polished GenMedia Creative Studio that is easy to deploy to Cloud Run and show to clients. It should still merge upstream fixes cleanly.

**Not in scope now.** Deploying to Cloud Run. The owner will set up GCP later. Rewriting the app off Mesop.

## Research (cited)

- **Krea** ([docs](https://www.krea.ai/docs/user-guide/features/krea-image.md)): prompt box at the bottom with the model picker in it. Settings change with the model. Each prompt gets a row of results with hover actions (retry, reuse settings, download).
- **Adobe Firefly** ([help](https://helpx.adobe.com/firefly/web/unified-generation-and-editing-experience/generate-and-edit-content.html)): one central action bar. Clicking a past result loads its prompt and settings back.
- **Runway** ([help](https://help.runwayml.com/hc/en-us/articles/37425232841875-Getting-Started-with-Generative-Video)): every generation goes into a session, so outputs stay organised.
- **Mesop** ([performance guide](https://mesop-dev.github.io/mesop/guides/performance/)): all state is sent on every event, and base64 media in state is the main cause of slowness. Keep media in GCS and keep only URLs in state. Every `me.theme_var()` is a CSS variable (`--sys-*`), so **one stylesheet can restyle every page**. Mesop's docs say it is no longer maintained as of 2026-09-30, so keep changes in a thin layer that a later front-end rewrite can reuse.
- **Cloud Run** ([request timeout](https://docs.cloud.google.com/run/docs/configuring/request-timeout), [session affinity](https://docs.cloud.google.com/run/docs/configuring/session-affinity), [IAP on Cloud Run](https://docs.cloud.google.com/run/docs/securing/identity-aware-proxy-cloud-run), [tips](https://docs.cloud.google.com/run/docs/tips)): use session affinity (Mesop keeps state per session), startup CPU boost, a long timeout for Veo, and IAP so only invited clients can sign in.

**Decision.** Stay on Mesop. Restyle everything from shared places: the theme stylesheet, page scaffold, side nav, header and home. Don't edit each of the ~30 pages. This keeps upstream merges cheap.

## Steps

1. **Theme layer** (`assets/ui/studio.css`, `common/ui_theme.py`). Inject one stylesheet and the Google Sans font into every `@me.page`. Override the `--sys-*` palette in light and dark: calm graphite surfaces and one blue accent. No gradient text or glows. Also: one radius family, thin modern scrollbars, visible focus rings, 150–200 ms transitions, and `prefers-reduced-motion`.
2. **Shell.** A cleaner side nav (grouped, labelled, clear active item, no gradient logo) and a page header with a one-line purpose. On a phone, the side nav becomes an off-canvas menu so the content gets the full width.
3. **Home.** A short hero ("Google's generative media on Vertex AI: image, video, music, speech") and a grid of capability cards with video previews and a one-line description. Videos load lazily and play on hover. Cards are sized to use the width at 1440 and stack at 390.
4. **Speed.**
   - Lazy-load the home videos (`preload="none"`, poster frame, play on hover or when visible).
   - Hide test and dev pages unless `SHOW_DEV_PAGES=true`.
   - Run gunicorn with a worker count from `WEB_CONCURRENCY`.
   - Tune the Dockerfile: smaller layers, `uv sync --frozen --no-dev`, and cached dependency layers.
5. **Cloud Run, ready to deploy** (`deploy/quickstart/`). One script for Cloud Shell. It turns on the APIs, creates the bucket, the Firestore database and a service account, then runs `gcloud run deploy --source .` with session affinity, CPU boost, `--timeout=3600`, scale-to-zero by default, and an optional IAP flag. It ships with a README. Nothing is deployed in this session.
6. **Audit.** Website Maker `audit_page` on home, a generation page (Imagen/Veo) and the library, at 1440 and 390 in light and dark. Fix the top items, re-audit, and record before → after counts below.
7. **Ship.** One commit per logical change, pushed to `ProjectZero02/genmedia-studio`.

## Phase 2: features that sell (researched 2026-11-15)

Every leading studio pairs generation with a shot list or timeline, reusable characters and one-click continuation: [Google Flow](https://labs.google/fx/en-gb/tools/flow/faq) (Scenebuilder: Extend / Jump To), [LTX Studio](https://ltx.studio/blog/top-ltx-studio-features) (script → storyboard, @Elements), [Higgsfield](https://geo.higgsfield.ai/task/blog/what-is-higgsfield-ai-complete-guide-cinematic-creative-studio) (camera-motion presets, Soul ID), [Invideo AI](https://invideo.io/agents/chatgpt/) (one prompt → film, then chat edits), [Freepik](https://www.freepik.com/ai/faq/clip-editor) (timeline clip editor with lip sync).

| # | Upgrade | Why clients care | How | Effort |
|---|---|---|---|---|
| 1 | **Film Builder**: shot list → per-shot Veo → continuity (last frame → next clip, or [Veo Extend](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/video/extend-a-veo-video), up to 37 s) → stitch with crossfades → Lyria music + TTS voiceover → trim/reorder | Idea to finished film in one page. This is the "open-source Higgsfield" | Server-side MoviePy/ffmpeg job (both already in the repo, MIT). Shot list in Mesop state, media in GCS. Reuse the upstream `experiments/veo3-character-consistency` logic | L |
| 2 | **Camera-motion and look presets** (dolly, orbit, crash zoom, FPV, plus a few visual looks) on Veo | Instant wow, Higgsfield's selling point | Prompt templates and a preset card grid | S |
| 3 | **Characters and products library**: save reference images and tag `@name` in any shot | Consistency across shots, like LTX Elements | Firestore plus [Veo reference images](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/video/use-reference-images-to-guide-video-generation) | M |
| 4 | **Auto-captions, burned in** | Finished-looking output | Gemini/Chirp transcription, then ffmpeg subtitles | S–M |
| 5 | **Script → storyboard → film**: Gemini writes shots and stills, the user approves, then the Film Builder renders | Invideo/LTX-style flow | Chain the existing Storyboarder into #1 | M |
| 6 | **Background removal** for stills | Polishing tool | [rembg](https://github.com/danielgatis/rembg) (MIT) in the Cloud Run image | M |

**Not now.** Embedding a full JS timeline editor. [Remotion](https://www.remotion.dev/license) and designcombo need paid licences for companies. Twick has a non-standard licence. OpenCut is a whole app that is being rewritten. A simple trim/reorder list in Mesop is enough for demos. Revisit [ffmpeg.wasm](https://github.com/ffmpegwasm/ffmpeg.wasm) for live preview later.

**Pitch angle.** Native audio per shot, Extend, and everything running in the client's own GCP project (their data stays in their cloud).

**Guardrail.** Veo calls cost money, so cap shots and resolution for each demo film (config value).

Phase 2 needs a GCP project to test against real Vertex AI. The code can be built with mocked tests first.

## Built so far (2026-11-15)

- **Shell:** theme, side nav (floating menu button on phones), page header, home with quick starts.
- **Sign-in** (`AUTH_MODE=session`): split-screen `/login`, signed session cookie, scrypt passwords, admin and user roles, `/admin/users`, avatar menu. Users in Firestore `studio_users`.
- **Story Studio** (`/story`, Phase 2 #1, #2 and #5): Stories → Create → Scenario → Storyboard → Editor → Video, live progress per scene, camera presets, MoviePy stitching with music and voiceover. Demo mode runs locally with no cloud calls.
- **Image Studio and Video Studio** (`/nano-banana`, `/veo`): prompt composer with setting chips, stage-by-stage progress, result cards with actions.
- **Cloud Run quickstart:** `deploy/quickstart/` (not run).
- **Ten-item menu** (customer audit, 2026-11-15): Create (Image Studio, Video Studio, Story Studio, Voice, Music), Industry demos (Fashion, Product 360, Interiors, Brand kit), Library. About and Settings live in the avatar menu. Merged and older pages stay reachable but hidden; `SHOW_LEGACY_PAGES=true` shows them.
- **Video Studio** runs Gemini Omni 1.2 Flash by default, Veo 3.1 as an option; `/gemini-omni` redirects there.
- **Fashion** (`/fashion`) combines Virtual try-on and Shop the look; `/vto` and `/shop_the_look` still work.
- **Voice** (`/voice`) combines Gemini 3.8 Flash TTS and Chirp 3 HD; `/gemini-tts` and `/chirp-3hd` redirect there.
- **Removed:** the retired Imagen 3/4 and Imagen upscale pages, models and tests (Google retired them 2026-06-30).

## First live test (after the owner deploys)

1. Sign in as the bootstrap admin, add a user, sign out and in as that user.
2. Image Studio: generate, edit with a reference image, send to Video Studio.
3. Video Studio: text, image, first + last frame and references modes; extend.
4. Story Studio, real mode: a 3-scene film end to end (Gemini scenario, storyboard frames, Veo clips, Lyria, voiceover, stitch, library).
5. Library shows everything; the credential-dependent tests pass with ADC.

## Follow-ups

- Self-host Lit instead of loading it from jsdelivr: the chip menus paint late on a cold phone load (Video Studio lab LCP 4.2–4.6 s at 390 px; 1 s on desktop).
- Story Studio jobs live in memory on one instance: move to Cloud Tasks or a job record in Firestore before heavy use.
- Change-password-on-first-sign-in; session expiry while a page is open shows an error until reload.
- Virtual Try-On (`virtual-try-on-001`) retires 2027-03-15: move Fashion's try-on to Nano Banana before then.
- Omni's "typical time" on the progress bar is a 90 s guess: replace with measured times after the first live runs.
- Hidden legacy pages are still imported at start-up; drop the ones nobody opens after the first demos to cut cold-start time.
- Phase 2 #3 (characters library), #4 (captions), #6 (background removal).

## Needs the owner later

- A GCP project with billing, for a real end-to-end test (Vertex AI, Firestore, GCS). Core has a pending `gcp` request. Until then, generation can't be tested. Only the UI is checked locally.

## Audit log

| Page | Before | After |
|---|---|---|
| /home | 3 errors, 2 warnings; 390 px rendered blank | 0 errors; left: no `<main>` landmark (Mesop can't set roles), lab LCP |
| /veo (Video Studio) | 3 errors | 0 errors on desktop; phone lab LCP 4.2–4.6 s (see Follow-ups) |
| /nano-banana (Image Studio) | 1 error, 2 warnings | 0 errors, 1 warning (no `<main>`) |
| /story | 1 error, 2 warnings | 0 errors, 1 warning (no `<main>`); Video step: Tab gets stuck in the native player |
| /login | 1 warning (small show-password button) | 0 warnings |
| /lyria | 0 errors, 4 warnings; cards squeezed side by side at 390 | 0 errors, 3 warnings; cards stack, full width on phones |
| /library_v2 | 0 errors, 2 warnings; filters ran off-screen at 390 | 0 errors, 2 warnings; filters wrap, empty state with next step |

All pages: on phones (≤600 px) the nav rail is replaced by a floating menu button.
