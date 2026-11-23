# Branding plan: your brand on everything you make

Goal: a company saves its brand once, and every film, video and image it makes in GenMedia Creative Studio comes out on brand without extra steps.

A **brand** is not a **Set**. A Set is reusable cast and places (who and where). A brand is how the company looks and sounds on every piece: logo, colors, fonts, caption and title style, opening and closing, and tone.

## 1. Pitch (for companies)

> Save your brand once: logo, colors, fonts and tone. From then on, every film, video and image you make in Creative Studio is on brand by default. Scenes are painted in your palette and written in your voice, your logo sits in the corner, captions and titles use your font and colors, and each film can open with your logo sting and close on your end card. Keep one brand per client, product line or campaign, pick it from a dropdown, and switch branding off for internal drafts. The logo is drawn on at export, never invented by the AI, so it is always exact.

## 2. What the best tools do

Eight brand kits were checked (official help pages, November 2026). Canva's pages block fetching, so its facts come from search excerpts of the official pages.

| Product | Stores | How it is applied | Several brands | Notable |
|---|---|---|---|---|
| [Synthesia](https://docs.synthesia.io/docs/brand-kits) | Light and dark logo, up to 120 colors in themes (text, background, accent roles), 2 fonts mapped to 5 text styles (title 1/2, subtitle, body, caption), corner style, avatars, backgrounds | **Automatic**: the workspace default kit applies to new videos. Menu action in the editor replaces colors, fonts and logos. Old videos change only on "Update video" | Yes, per workspace with a default ([enforcement](https://help.synthesia.io/en/articles/11593582-how-can-i-enforce-brand-guidelines-across-my-workspace-s-videos) on Business/Enterprise) | Admin "enforcement": no off-brand fonts or logos, no "no brand" option |
| [HeyGen](https://help.heygen.com/en/articles/9889198-what-are-brand-kits) | Primary and alternate logos, colors, fonts, images, video, motion elements, avatars | One click from a Brand menu | Unlimited ("Brand Systems") | **Build from a website URL**: detects logo, colors, fonts; editable after ([API](https://developers.heygen.com/docs/brand-kits/import)) |
| [VEED](https://support.veed.io/en/articles/9616498-how-to-create-and-manage-brand-kits) | Fonts, colors, images, video, audio, saved groups (lower thirds, intros, outros) | One click; brand colors and fonts appear first in text and subtitle pickers. "Save to Brand Kit" from the timeline | Yes on Pro and up | Intros and outros are saved groups, not a special type |
| [Kapwing](https://www.kapwing.com/help/how-to-use-brand-kit-and-brand-templates-in-kapwing/) | Templates, colors, fonts, text and **subtitle styles**, voices, logos, intros, outros, overlays, spelling and pronunciation guide | Brand font is the default for new text; projects start from a brand template | No, one per workspace | Pronunciation guide for voiceover |
| [Descript](https://help.descript.com/branding/brand-studio.md) | Fonts, colors, layout packs tagged intro / outro / captions / text, shared media (music, logos), glossary, do-not-translate list | A default layout pack is offered first in every project | No, one per Drive | **Do-not-translate list** for brand terms |
| [Canva](https://www.canva.com/help/brand-kit/) | Logos with variants, labelled palettes, font pairings with sizes, brand templates | One click from the kit panel; Brand Controls can restrict to brand colors and fonts | Yes, per team, client or campaign | [Brand Kit Builder](https://www.canva.com/help/brand-kit-builder/) extracts a kit from a website or PDF |
| [Adobe Express](https://www.adobe.com/ie/learn/express/web/create-brand-kit) | Logo, colors, fonts, graphics, templates | Via font and color pickers; [lockable elements](https://adobe.com/uk/express/learn/blog/lockable-brand-assets) | Unclear | Lock single elements in templates |
| [CapCut Teams](https://www.capcut.com/help/benefits-of-capcut-teams) | Colors, logos, fonts, brand templates | Picker | Teams plan | Little documented |

**Patterns most of them share**

1. A brand is a shared library with an editor (owner or admin) and users.
2. Brand fonts and colors become the defaults in every picker, so on-brand is the easy path.
3. Intros, outros, lower thirds and caption styles are reusable layouts tagged by type.
4. Light and dark logo versions.
5. Fastest start: import from a website, then review.
6. Strict locking is a premium feature (Synthesia, Adobe, Descript Enterprise).

**What none of them can do, and we can:** put the brand into the *generation itself*. They are editors, so their brand only styles text and overlays. We write the scenes, paint the frames and make the clips, so the palette, wardrobe, set dressing, lighting and tone of voice can follow the brand too. That is the selling point.

**Logo size and placement:** none of the eight document defaults. Video APIs use: [Cloudflare Stream](https://developers.cloudflare.com/stream/edit-videos/applying-watermarks) 15% scale, 5% padding, top right; [Pictory](https://docs.pictory.ai/guides/branding-customization/logo) 15%, top right. Broadcast corner logos ("bugs") are smaller, about 5 to 8% of width.

## 3. What we have today

| Piece | Where | Status |
|---|---|---|
| Brand data: name, up to 5 colors, tone (300 chars), logo, corner | `src/common/brand_kit.py` | Works. **One brand per person**: the Firestore key is the SHA-1 of the owner's email in `brand_kits` |
| Brand page | `/brand` (`src/pages/brand.py`), in the avatar menu as "My brand" | Works. Name, tone, colors, logo upload (PNG, WebP, JPEG), corner. No fonts, no logo size, no preview |
| Story Studio switch | "Use my brand" toggle in `setup_view.py`, `on_use_brand` in `pages/story_studio.py` | Works. At Create the kit is **copied onto the story** (`Story.brand_json`), so later edits don't change a film half way. Good design, keep it |
| Prompts | `_brand_line` / `_brand_rule` in `services/story_models.py`, used by the director (`story_director.py`) and frame prompts | Works. Colors and tone go into scenario, breakdown and frame prompts, with "never show the brand name or a logo in a scene" |
| Image Studio | "Apply my brand: colours and tone" chip, `pages/gemini_image_generation.py` | Prompt only. No logo on images |
| Home chat (live jobs) | `brand` toggle in `services/studio_options.py`, `_brand_prompt` in `services/live_jobs.py` | Prompt only |
| Logo on the film | `logo_overlay_png` (brand_kit.py) → `render_timeline(logo=…)` → one `overlay` in `render_args` (`story_timeline.py`) | Works for **export** (`start_export`) and **subtitled downloads** (`start_subtitled`), via `_logo_args` in `story_service.py`. Size is fixed: 14% of the short side tall (about 12% of width at 16:9), 4% margin, 90% opacity, whole film |
| Captions and titles | `text_overlay_png` in `story_timeline.py`; 3 styles (clean, boxed, bold), Noto Sans, white text | Not brand-aware: no brand font or color |

**Gaps found**

1. **Bug: the first film has no logo.** `make_film` (`story_service.py` ~434) calls `render_timeline` without `_logo_args`, so the film from "Make film" is unbranded and only a later Export adds the logo. Fix in Phase 1.
2. One brand per person; no team or client brands.
3. No fonts, no caption or title style, no intro or outro, no end card, no light/dark logo.
4. No logo size or opacity control; vertical (9:16) films put a bottom-right logo where TikTok, Reels and Shorts draw their buttons and captions.
5. No branding on single videos (Veo/Omni pages) or images.
6. No per-export switch to turn branding off for a draft.
7. Brand guidelines tools exist but are separate (`/brand_adherence`, `/guideline_analysis`: check media against a guidelines PDF). They could later score films against the brand.

## 4. Recommended design

### 4.1 Data model: several brands per owner, shareable later

New Firestore collection `brands`, one document per brand (random id). Keep the old `brand_kits` document and migrate it on first load into a brand named after it (or "My brand"), then mark it migrated.

```text
brands/{brand_id}
  owner          email of the creator
  team           "" today; a team id later (shared brands)
  name           "Acme"
  is_default     true for the owner's default brand
  colors         [{hex, role}]   roles: primary, secondary, accent, text, background (max 6)
  tone           tone of voice (300 chars)
  logos          {light: uri, dark: uri}   PNG/WebP/SVG with transparency
  logo           {corner: br|bl|tr|tl|auto, size: s|m|l, opacity: 0.85, on: whole|end|off}
  fonts          {title: font id, body: font id}   from a fixed list or an uploaded TTF/OTF
  captions       {style: clean|boxed|bold, color, box_color, pos: bottom|top}
  titles         {style, color}
  intro          {kind: none|logo_sting|upload, uri, seconds: 2.5}
  outro          {kind: none|end_card|upload, uri, seconds: 3, line: "acme.com"}
  music          uri of a brand sound (optional)
  voice          preferred voice id (optional)
  terms          words to keep as written (brand and product names; do-not-translate, pronunciation)
  created, updated
```

- Access: owner-only reads and writes through the existing `common/authz` rules. A `team` field is reserved so a later phase can share a brand with a team without changing the schema (and without inventing new library-sharing switches; see AGENTS.md).
- The story keeps a **snapshot** (`Story.brand_json`) as today, plus `brand_id`, so a film stays the same if the brand changes, and "Update to latest brand" can refresh it (Synthesia's "Update video").
- `brand_kit.clean()` stays the single validator; it grows to the new fields, with old one-brand documents mapped to the new shape.

### 4.2 What to support first

In order of value for a demo and effort to build:

1. **Logo watermark** (exists; fix the bug, add size, auto corner, light/dark).
2. **Colors and tone in generation** (exists; add color roles).
3. **Caption and title style**: brand font and colors on burned-in subtitles and text overlays.
4. **End card**: logo on a brand-color background with one line (website or tagline), 3 s.
5. **Intro sting**: logo fades in on brand color, 2.5 s; or an uploaded clip.
6. Brand music and voice, terms list.
7. Import a brand from a website.

### 4.3 Where each piece is applied

| Asset | Prompt level (generation) | Render level (ffmpeg, at export) |
|---|---|---|
| Colors | Yes: palette, wardrobe, set, lighting (today's `prompt_line`, with roles: "primary #… dominant, accent #… sparingly") | Yes: caption box, title color, end card and intro background |
| Tone of voice | Yes: scenario, narration, dialogue | No |
| Terms | Yes: spelled as written in scripts; kept as is in subtitle translation | Subtitles |
| Logo | **Never** (the model must not draw logos; keep the existing rule) | Yes: corner overlay, intro, end card |
| Fonts | No | Yes: captions, titles, end card |
| Caption and title style | No | Yes |
| Intro / outro | No | Yes: added as clips on the timeline |
| Music, voice | Voice: picks the narrator voice | Music: default music track when the story has none |

Rule: **anything that must be exact (logo, fonts, words on screen) is drawn at render time, not generated.** The model only gets mood and palette.

### 4.4 Render design (how it fits the code)

- Keep the brand out of `render_args` internals as much as possible: `render_timeline` takes one `brand: dict` instead of `logo` + `logo_corner`.
- **Logo**: extend `logo_overlay_png`. Size from the short side so it reads the same in 16:9 and 9:16; pick the light or dark logo from the mean brightness of the frame area under it (sample a few frames with the existing `_frame_luma` helper).
- **Intro and outro**: add as normal video clips at the start and end of the timeline (`build_timeline` already lays out clips), so the editor shows them and the player and export use the same rule. A logo sting and an end card are rendered once per brand and aspect ratio into a short MP4 (Pillow frame + ffmpeg fade) and cached in GCS under the brand.
- **Captions and titles**: `text_overlay_png` takes a font path and colors from the brand; unknown or missing fonts fall back to today's Noto fonts (Arabic lines keep the Arabic fallback).
- **Images**: same logo overlay with Pillow on the downloaded image (Image Studio "Add logo" on download, not baked into the library original).
- **Single videos (Veo, Omni pages)**: an "Add brand" export that runs the same render on a one-clip timeline.

### 4.5 Defaults

| Setting | Default | Why |
|---|---|---|
| Logo size | Small: 12% of the short side wide (about 7% of width at 16:9) | The owner's 6% idea; broadcast bugs are 5 to 8%. Medium 16%, Large 22% |
| Logo margin | 5% of the short side (36 px at 720p) | Inside title-safe; matches Cloudflare's 5% padding |
| Logo corner | Bottom right for 16:9 and 1:1; **top right for 9:16** ("Auto") | Social apps cover the bottom and right edge in vertical video |
| Logo opacity | 85% | Visible but not loud |
| Logo shown | Whole film, but **hidden during the intro and end card** (they already show it) | No double logo |
| Intro | Off; when on, 2.5 s logo sting | Bumpers make films longer; let the company choose |
| End card | On when a brand is used: 3 s, logo on primary color, one line | Cheapest strong brand moment; nothing covers the content |
| Captions | Brand body font, white text, boxed in brand primary at 80% | Readable on any frame |

### 4.6 Where it shows in the app

**Brand page (`/brand` → "Brands")**
- A list of brand cards (logo, color dots, name) with "New brand". One is starred as default.
- Brand editor in four short sections: **Logo** (light, dark, corner, size), **Colors** (with roles), **Text** (fonts, caption style, title style), **Open and close** (intro, end card). A live preview frame at 16:9 and 9:16 shows logo, a caption and the end card.
- Later: "Start from website" (paste a URL; Gemini reads the page and logo; the user reviews).

**Story Studio Setup (v4 Phase B)**
- The References area gets a **Brand** dropdown: "No brand", each saved brand, "New brand" (opens `/brand` in a new tab, as "Edit my brand" does today). Defaults to the owner's default brand.
- The live blueprint adds a line when a brand is set, e.g. "Brand: Acme · logo, end card".

**Export menu (v4 Phase D)**
- **Branding**: on/off (on when the story has a brand).
- Under it, three quiet toggles: Logo, Intro, End card, set from the brand's defaults.
- Subtitles "burned-in" uses the brand caption style when branding is on.

**Image Studio and Home chat**
- Replace the "Apply my brand" chip with a brand picker chip (same list). Image download gets "With logo".

## 5. Build phases

Each phase is its own PR with tests, after v4 Phase A (seamless engine) lands. Effort is for one agent session working in this repo.

| Phase | What | Effort | Fits v4 |
|---|---|---|---|
| **1. Logo done right** | Pass the brand to the first render in `make_film` (bug). Logo size s/m/l, opacity, "Auto" corner (top right for 9:16), light/dark logo picked by brightness. Tests for `logo_overlay_png` geometry and the overlay filter | 0.5 to 1 day | Independent; ship first |
| **2. Several brands** | `brands` collection, migration from `brand_kits`, default brand, `brand_id` + snapshot on the story, brand list and editor on `/brand`, brand dropdown in Story Studio Setup (replaces the toggle), picker chip in Image Studio and Home chat | 2 days | Is v4 Phase B's brand dropdown |
| **3. Branded text** | Fonts (fixed list of Google fonts shipped in the container, plus TTF/OTF upload), caption and title styles from the brand in `text_overlay_png`, color roles in `prompt_line`, terms list in prompts and subtitle translation | 1.5 days | Feeds v4 Phase D "burned-in (style)" |
| **4. Open and close** | Logo sting and end card generator (cached per brand and aspect), uploaded intro/outro clips, added to the timeline as clips, logo hidden during them | 2 days | Before Phase D export |
| **5. Export controls** | Branding on/off and Logo / Intro / End card toggles in the Export menu; "Update to latest brand" on a story | 0.5 day | Part of v4 Phase D |
| **6. Beyond films** | Logo on image downloads, "Add brand" export for Veo and Omni videos | 1 day | Independent |
| **7. Start from website** (later) | Paste a URL: fetch the page, pick logo, colors and fonts with Gemini, user reviews. Brand music and voice | 1.5 days | Independent |
| **8. Teams and checks** (later) | Share a brand with a team, admin-only edits, optional "always on" enforcement; score a film against the brand with the existing guideline tools | 2 days | After a team model exists |

Phases 1 to 5 make the demo story: about 7 days of agent work. Phase 1 alone fixes today's bug and makes the logo look professional.

## 6. Testing

- Unit tests with no network: brand validation and migration, logo geometry per aspect ratio and size, auto corner, light/dark choice on a synthetic frame, `render_args` filter text with and without intro/outro, caption font fallback.
- Mock-mode render (demo backend) of one story at 16:9 and 9:16 with a brand, checked frame by frame at the logo corner, intro and end card.
- No live generation while testing (owner rule); one live film only with the owner's yes.

## 7. Open questions for the owner

1. Logo on every shot, or only on the intro and end card? This plan defaults to **both** (small corner logo plus end card), with Export toggles to change it.
2. Should a brand be shareable with a team now, or is one person per brand enough for the first demos? This plan reserves the field and builds sharing later.
3. Font upload: allow custom TTF/OTF (licensing is the company's responsibility), or only a fixed list of Google fonts at first? This plan does both, list first.
