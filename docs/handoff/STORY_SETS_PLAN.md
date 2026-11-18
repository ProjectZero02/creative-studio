# Plan: Sets for Story Studio (reusable characters, voices and locations)

For: Matheo's Claude. Written 2026-11-18 from the owner's session.
Repo: `ProjectZero02/creative-studio`. The core app lives in `src/`; read `AGENTS.md` first.
Branch from `main`. It already has Story Studio on Gemini Omni (PR #7) and the newest models (PR #8).

## The ask

From the owner:

> "Clients that generate stories would want some consistency / repetition, not just in one video … but by multiple. And they might want multiple different 'sets'. … Before the video gets made, any and all assets that have to stay consistent between videos/clips get made first and stored in a 'set' list: reference images of the character, their voice, the background(s), etc. This way, before the video gets made, they can modify how the characters or specific things look. … If they don't select a set, the studio does it automatically."

**Verdict: yes, build it.** It is how the leading tools work:
- **Google Flow** has "Ingredients".
- **LTX Studio** has "Elements", which it auto-extracts from the script.
- **Kling** has an "Element Library", with a voice bound to each character.

It also attacks our stitching problem at the root. Today, clips stay consistent mainly by chaining (the last frame of one clip starts the next, plus Omni threads for speech), so drift builds up the longer the film gets. With a set, every clip is anchored to the same reference images, so clip 20 sees the same face and room as clip 1. The voice is still the weakest link; see "Voice" below.

## How it works today (so you know what you're replacing)

- `Story` in `src/services/story_models.py` has one `reference_uri` (a character image), one `character` text, `speaker_voice` (text describing the on-camera voice), `voice_name` (narrator TTS voice) and `style`.
- If there is no reference, `story_jobs.py` uses the first storyboard frame as the reference (around the line `reference = story.reference_uri`).
- `story_service.clip_inputs()` makes a clip as Omni `ref2v` from `[storyboard frame, story.reference_uri]`, or as `i2v` from a continuity frame.
- `clip_prompt()` repeats the character text and voice description in every clip. Back-to-back spoken scenes continue one Omni thread (`previous_interaction_id`) to keep the voice (see `extend_clip`, `take_history`).
- Nothing is reusable across stories: there's no multi-character support, no locations and no props.

## What other products do (cited)

| Product | An asset holds | Created from | Voice |
|---|---|---|---|
| [Google Flow Ingredients](https://support.google.com/flow/answer/16353334?hl=en) | A reference image or video of a subject, object, location or style | Upload or project assets; Google suggests making them with Nano Banana ([blog](https://blog.google/innovation-and-ai/technology/ai/veo-3-1-ingredients-to-video/)) | Omni Flash ingredient voices: a preset plus a name and performance description, single speaker |
| [LTX Studio Elements](https://help.ltx.io/hc/en-us/articles/33578393195922-Introduction-to-Elements) | A character, location, prop, or style/brand asset | Made by hand **or auto-pulled from the script** when the storyboard is made | Picked from a library and linked to the character ([blog](https://ltx.studio/blog/getting-started-with-elements)) |
| [Kling Element Library](https://kling.ai/quickstart/klingai-element-library-3-user-guide) | A character, item, costume or scene, as multiple images or a 3–8 s video | Upload | Bound per character ([API `element_voice_id`](https://kling.ai/document-api/api/video/4-0/elements.md)) |
| [Higgsfield Soul ID](https://higgsfield.ai/creator-hub/help-center/ai-models/how-do-i-create-and-use-a-soul-id-character) | A trained identity | 5+ photos | — |

They share one pattern: a **named, typed asset** with several images, a voice only on characters, and the asset named in the prompt. Our "auto if none chosen" behaviour copies LTX's script extraction.

## Design

### Naming and placement in the app

- A **Set** is a named, reusable collection of **characters, locations, props** and a **style**.
- Sets live in a library the user can reuse across stories. Each story uses at most one set.
- Add a new Story Studio step **"Set"** between Scenario and Storyboard. `STEPS` in `story_models.py` becomes: Stories → Create → Scenario → **Set** → Storyboard → Scenes → Edit.
- In the Create step, a "Set" picker offers **None (make one from my story)** plus the user's saved sets. Pick a saved set and the scenario writer gets its cast and locations so the story uses them.
- Keep copy short and controls the same size (owner rules: `memory/genmedia-ui-rules.md` in the owner's Claude project, summarised under "Rules" below).

### Data model

Add a new module `src/services/story_sets.py`:

```python
@dataclass
class SetImage:
    view: str          # "front" | "three_quarter" | "profile" | "face" | "plate" | "angle" | "item"
    uri: str           # gs:// or local:// (never bytes)
    prompt: str = ""
    locked: bool = False   # regenerate-all skips locked images

@dataclass
class Voice:
    tts_voice: str = "Kore"   # Gemini TTS prebuilt voice (voiceover / narrator)
    style: str = ""           # TTS style prompt, e.g. "warm, unhurried, slight smile"
    description: str = ""     # on-camera voice description used in Omni prompts
    sample_uri: str = ""      # a short TTS sample so the user can hear it
    # Reserved, empty until access is confirmed (see Voice section):
    chirp_cloning_key: str = ""
    omni_voice_ref: str = ""

@dataclass
class Character:
    id: str; name: str; description: str; outfit: str = ""
    images: list[SetImage]    # front, three_quarter, profile, face
    voice: Voice
    narrator: bool = False    # the off-screen narrator is a character with no images

@dataclass
class Location:
    id: str; name: str; description: str; time_of_day: str = ""
    images: list[SetImage]    # one wide empty "plate" + 1-2 "angle"

@dataclass
class Prop:
    id: str; name: str; description: str
    images: list[SetImage]    # one "item" on a plain background

@dataclass
class StorySet:
    id: str; owner: str; name: str
    style: str                # one of STYLES ids
    style_notes: str = ""
    characters: list[Character]; locations: list[Location]; props: list[Prop]
    created_from: str = "manual"   # "manual" | "auto"
    version: int = 1               # bumped on every change; stories record the version they rendered with
    created_at: str = ""; updated_at: str = ""
```

**Story changes** (`story_models.py`):
- `Story.set_id: str = ""` and `Story.set_version: int = 0`.
- `Scene.cast: list[str]` (character ids on screen), `Scene.location_id: str = ""` and `Scene.prop_ids: list[str]`.
- `Scene.speaker_id: str = ""` (which character says the spoken line).

**Storage:**
- Firestore collection `story_sets`, with `STORY_SETS_COLLECTION_NAME` in `config/default.py`, plus a `LocalSetStore` (JSON file) for demo mode.
- Model both on `services/story_store.py` (`LocalStoryStore` / `FirestoreStoryStore`).
- Store images with `common/storage.store_to_gcs` under `story_sets/<set_id>/`.

**Access is owner-only.** Follow the `common/authz.authorize_read` rules in AGENTS.md "Security"; never pass `allow_shared`.

**Migration:** when an old story with `reference_uri` / `character` / `speaker_voice` is opened, build a one-character set from those fields lazily. Don't run a batch job.

### Generation recipes (Nano Banana 2.1 for images, Gemini TTS for voices)

1. **Auto-build from the story** (the "no set chosen" path):
   - One Gemini JSON call (`STORY_SCENARIO_MODEL_ID`) reads the idea and scenario. It returns characters (name, look, outfit, voice description, TTS voice choice from `VOICES`), locations, props, and per-scene `cast` / `location_id` / `prop_ids` / `speaker_id`.
   - Then run the recipes below for each asset.
   - Put the parser next to the scenario parser in `story_models.py` and reuse its retry/ScenarioError pattern.
2. **Character:**
   1. Generate the **front, full body, plain neutral background** image first.
   2. Feed it back as a reference to make **three-quarter**, **profile** and **face close-up**, prompted with "same person, same outfit, preserve identity".
   3. That's 4 images per character. One consistent look and lighting across all of them.
3. **Location:** one **wide, empty establishing plate** (no people), then 1–2 **angles** generated from the plate as a reference.
4. **Prop:** one image on a plain background.
5. **Voice:**
   - Pick a Gemini TTS voice and a style prompt.
   - Make a ~5 s `sample_uri` so the user can hear it (reuse `generate_voiceover`).
   - Write `description` for the on-camera voice: age, gender, accent, pace and timbre, fixed wording.
6. Every image job goes through `StoryBackend` (add `generate_set_image(set, prompt, refs) -> uri`). The mock backend draws placeholder images like `MockStoryBackend.generate_frame`.
7. Run images in parallel with `STORY_MAX_PARALLEL`. Show progress with the existing job/task system in `story_jobs.py` (a new job kind `"set"`, like `"music"` / `"export"`).

### The Set step UI (`pages/story_studio.py` + a component under `components/story_studio/`)

- Three sections, **Characters**, **Locations** and **Props**, with one card per asset.
- Each card shows:
  - its images in a row;
  - name, description and outfit fields;
  - per-image **Regenerate** and **Lock** controls;
  - **Upload** (replace with your own image, via `save_upload`) and **From library**.
- Character cards also show the voice select, the style field and a **Play sample** button.
- Actions: **Add character / location / prop**, **Save as new set**, **Update set**, plus a header button **Make set** (auto-build), equal size and 40 px.
- Editing a description doesn't regenerate anything until the user presses Regenerate. Locked images are never replaced.
- Changing a set bumps `version`. Stories rendered with an older version show "Set changed since this film was made".

### Using the set when rendering

- **Storyboard frames** (`generate_frame` / `frame_prompt`):
  - Pass refs to Nano Banana: the scene's cast **face + front**, the location **plate**, and props.
  - Name them in the prompt: "Use the reference images for Maya (woman, red coat) and the café".
- **Clips** (`story_service.clip_inputs`):
  - Build `r2v_references` from: the storyboard frame first, then the cast faces/fronts, then the location plate, then props.
  - Cap it at the model's `max_reference_images` from `config/omni_models.py`; drop props first, then extra character views.
  - Google's Vertex page doesn't state Omni's cap ([refs page](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/video/generate-videos-from-references)). Our registry says 10 for 1.2 Flash, but third parties say 5–7, so add `STORY_MAX_CLIP_REFERENCES` (default 6) and test it.
  - Say "Use the images as references" in the prompt, and name each one.
  - The continuity path (`i2v` from the last frame) and the Omni thread for spoken takes stay the same. A new take after the 30 s cap re-anchors on the set refs, which is exactly where drift used to creep in.
- **Prompts** (`clip_prompt`):
  - Replace the single `story.character` text with the scene's cast descriptions.
  - For spoken scenes, use the speaker character's `voice.description`, word for word, every time.
  - The narrator's voiceover uses the narrator character's `tts_voice` + `style`.

### Voice: what's realistic today

| Option | Status | Use |
|---|---|---|
| Gemini TTS preset + identical style prompt | Works now ([docs](https://docs.cloud.google.com/text-to-speech/docs/gemini-tts)) | Narrator voiceover. Consistent across films if model, voice and style are pinned. |
| On-camera: a fixed `voice.description` in every Omni prompt + one Omni thread per take | Works now, but only a best effort between takes | People speaking on screen |
| Chirp 3 Instant Custom Voice | Allow-listed via Google Cloud sales; needs a ≤10 s sample plus a consent recording ([docs](https://docs.cloud.google.com/text-to-speech/docs/chirp3-instant-custom-voice)) | A client's real brand voice for voiceover. Keep the field; build it later if the owner gets access. |
| Omni voice references (audio in) | Shown in Flow; not in the Vertex docs we could reach, probably allow-listed | Would truly lock on-camera voices. Keep `omni_voice_ref`; don't build until confirmed. |

So:
- **Sets fully fix look consistency.**
- **For voices,** they fix the narrator and make on-camera voices much steadier (same description, same thread per take), but they can't guarantee an identical on-camera voice across takes until Omni voice references are available on Vertex.
- Say this plainly in the PR. Don't invent a workaround such as dubbing; the owner rejected TTS dubbing over on-camera speech.

## Steps (one logical commit each)

1. `services/story_sets.py`: dataclasses, local and Firestore stores, owner checks, and the to/from dict helpers. Unit tests.
2. `Story` / `Scene` fields, plus lazy migration of old stories. Tests.
3. The auto-build JSON prompt and parser (cast/locations/props plus per-scene ids). Tests with fixed JSON.
4. The backend `generate_set_image` (Vertex = Nano Banana via `models.gemini.generate_image_from_prompt_and_images`, plus mock), and the `"set"` job kind in `story_jobs.py` with retry. Tests with the mock backend.
5. The Set step UI, the Create-step set picker, and the Sets library (rename / duplicate / delete with a confirm dialog).
6. Use sets in `frame_prompt` / `generate_frame`, `clip_inputs` and `clip_prompt`. Tests for reference ordering and the cap.
7. Docs:
   - `docs/environment_variables.md` (new `STORY_SETS_COLLECTION_NAME`, `STORY_MAX_CLIP_REFERENCES`);
   - a short section in `docs/STORY_STUDIO_V2_PLAN.md`;
   - Firestore index if listing by owner + `updated_at` needs one (check `deploy/` for how indexes are declared).

## Testing

- Use pytest from the venv. AGENTS.md "Testing" explains `PYTHONDONTWRITEBYTECODE=1` and the `Default` dataclass gotcha.
- Mock every Vertex call. Run the Story suites: `test/test_story_studio.py`, `test/test_story_timeline.py`, `test/test_storyboard_video.py`, plus a new `test/test_story_sets.py`.
- Run `ruff check --select F,E9,B` on changed files only.
- Browser check in demo mode (launch config `genmedia-story-demo`, `STORY_STUDIO_MOCK=true`) at 1440 and 390 px, light and dark:
  1. Auto-build a set.
  2. Edit a character and regenerate one image.
  3. Lock an image.
  4. Save the set.
  5. Start a second story with the same set and render it.
- **Before merging, ask the owner** for one live test, since it costs money: a 4-scene story with 2 characters and 1 location. Compare face and room consistency against a run without a set.

## Rules (from the owner)

- **Commits:** commit as ProjectZero02, with no Claude/AI co-author lines and no "Generated with" footer. One logical change per commit.
- **Cost:** don't deploy. Ask the owner before paid calls, GPUs or min instances.
- **UI:**
  - Tonal buttons, not bright outlines; sibling controls the same size (40 px).
  - Short labels and no sentences explaining obvious actions.
  - Don't use Website Maker.
- **Scope:**
  - Don't touch the timeline editor (`components/story_studio/story_timeline.js`) or the Edit step, except where a set name needs showing.
  - Keep the Omni thread logic for spoken takes as it is.
- **Done:** push the branch and open a PR into `main`. In the description, include what changed, the test counts, screenshots, and the voice limits above.

## Risks

- **Omni's reference cap is unconfirmed:** pick refs per shot and keep the cap configurable.
- **Fine details drift:** logos, accessories and small text can still drift. Props help but don't guarantee them.
- **More images, more cost:** auto-build makes about 4 images per character plus 2–3 per location. Show the count before running, and let the user skip it ("No set").
- **Voice limits:** on-camera voice identity across takes stays best-effort until Omni voice references are on Vertex.
