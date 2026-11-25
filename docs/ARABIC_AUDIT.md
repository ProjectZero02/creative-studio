# Arabic audit (2026-11-25)

**Purpose.** Make Arabic mode complete and reliable: every page in Arabic with a correct right-to-left layout, and AI output (Live, chat, generated text) in the language the person uses. Branch `arabic-i18n`.

## The rule

1. **Site in Arabic → everything defaults to Arabic.** Labels, menus, dialogs, errors, tab titles, sample text, the Voice language, the language of a new film.
2. **The person's language wins for AI output.** Typing or speaking Arabic gives Arabic replies, Arabic text in the fields Live fills, and Arabic titles, briefs, critiques and plans. English input gives English.
3. **No text to go by → the site language.**
4. **The person's words are never swapped for English.** Models that only read English (Veo, Lyria 2) get a translation inside the call, and the text box keeps the Arabic.

## What was wrong

### 1. Most pages were never translated
Translation only covered the side nav, headers and a few shared parts. 45 of 48 page files had no translation calls. The first-load scan found 11 to 37 English strings per page, and there were many more in menus, dialogs, progress and results. Film Studio alone had 287.

**Fix.** `common/i18n_mesop.py` wraps Mesop's `text`, `button`, `input`, `textarea`, `select`, `tooltip` and the other components once at startup. Each literal English string goes through `tx()`. The Arabic lives in one file per area, keyed by the English text:

| File | Covers |
|---|---|
| `common/i18n_ar/shell.py` | Home, nav, Library, Brand, Usage, Account, Settings, Users, Login, shared components |
| `common/i18n_ar/studios.py` | Image, Video, Voice and Music studios, composer chips |
| `common/i18n_ar/film.py` | Film Studio, every stage and the timeline editor |
| `common/i18n_ar/workflows.py` | Fashion, Interiors, Product 360, Brand kit |
| `common/i18n_ar/live.py` | Live panel, its replies, Home chat steps |

Upstream page code stays untouched, so upstream merges stay clean. Text built at runtime ("4 shots", "Scene 2 · video clip", errors) is matched with patterns. Web components (the composer chips, the Film Studio stepper, timeline and compare player, the Home chat audio player, the Library viewer) now get a translated strings map from Python.

### 2. Live typed English and answered in English
- The Live system prompts had no language rule.
- The offline agent only understood English.
- Voice jobs defaulted to en-US.
- The Live panel showed raw keys (`live.mute`, `live.jobs`) in both languages, because `tl()` returns the key itself, so the fallback never ran.

**Fix.**
- Live gets the site language (`?lang=` / `gm_lang` cookie) and a rule to speak and fill fields in the person's language.
- Arabic intents work offline: "اصنع صورة لثعلب في الثلج" fills "ثعلب في الثلج".
- Arabic scripts use an Arabic voice code (`ar-EG` for Gemini TTS, `ar-XA` for Chirp).
- The panel strings are translated.

### 3. AI-written text came back in English

| Where | Before | After |
|---|---|---|
| Home chat replies and steps | told it "prompts may stay in English"; steps always English (FastAPI has no Mesop state) | person's language; steps use the request language |
| Prompt rewriter (Improve, auto-enhance, lyrics, voice scripts, chat titles) | free | writes in the input's language, else the site's |
| Film brief, sequence titles, fix plans | brief forced to English | follow the idea's or request's language |
| New film language | always English | Arabic on an Arabic site, until the idea says otherwise |
| Interiors room names, try-on critique, Shop the look descriptions | English | site language |
| Image Studio suggested edits, Music critique | English | site or prompt language |
| Veo and Lyria 2 prompts | Arabic sent as is to English-only models | translated inside the call, field keeps Arabic |

### 4. Right-to-left layout
- Outlined fields drew broken borders with corner hooks on every page (physical corner radii). Fixed with logical radii.
- Select panels, menus and tooltips ran left to right: the overlay is created before the language loads. Overlay content is now right-to-left.
- The composer "+" menu opened off-screen at 390 px, and chip menus were misaligned.
- Typed text and prompts didn't follow their own direction, so English sentences in the Arabic UI showed the full stop at the wrong end. Inputs now act as `dir=auto` and user text keeps its own direction.
- Money and numbers flipped (`<$0.01` showed as `$0.01 >`, and "360°" as "°360"). They are now isolated.
- Home chat durations showed as "s 5", and the waveform played backwards.
- Login tiles overlapped their labels in Arabic.
- Film timeline: time runs left to right in every language, as in Clipchamp, CapCut and YouTube Studio. The stepper and progress follow reading direction.
- Browser tab titles stayed English. They now follow the language, and the welcome page got `lang`/`dir`.

## Result

Final scan with `scripts/ui/arabic_scan.mjs` on 16 routes, at 1440 and 390 px, mock mode:
- `dir=rtl` on every page.
- No horizontal overflow and no inputs forced left to right.
- The only English left is allowed: the "English" switch, "Live", Gemini voice names (Kore), model IDs on Usage, and the user's own film titles.
- Walk-throughs covered menus, dialogs and mock generations in each studio, all Film Studio stages, and the demo steps that run locally.

## Still to do
- **Check against live Vertex after deploy:**
  - Live speaks Arabic and fills Arabic.
  - Veo and Lyria 2 work with the translation step.
  - The rewriter keeps Arabic.
  - Interiors room names come back unique in Arabic.
  - Film fix plans come back in Arabic.
- **Not checked in the browser:** Product 360 steps 2–3, Interiors steps 2–4 and Shop the look. They need cloud storage or Firestore; their text is covered by the dictionary.
- **Film cast and set descriptions are written in English on purpose,** because they feed the image models. Data names made from the idea ("<title> set", "Character 1") stay as created.
- **Still English:** some image-analysis text in `models/gemini.py` (`describe_image`, `image_critique`, character-consistency prompts), and Settings > About.
- **Legacy pages** behind `SHOW_LEGACY_PAGES` (off by default) are not translated.
- **Small UI items:**
  - `gcs_uploader` "Upload video" has a bright outline next to a tonal button.
  - The Library "Show" select is taller than the pills beside it.
  - The Library viewer's download and GIF buttons still read English.
- **Mesop overlays still position themselves as left-to-right;** they stay on screen and their content is right-to-left.

## How to check Arabic
```
node scripts/ui/arabic_scan.mjs base=http://localhost:8110 out=scan.json shots=shots
```
It needs Playwright (`PLAYWRIGHT_PATH`) and Edge. To translate a new label, add it to the right `common/i18n_ar/*.py` file.
