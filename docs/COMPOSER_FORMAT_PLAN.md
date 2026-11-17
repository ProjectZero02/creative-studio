# Home and studio composer format (2026-11-17)

Purpose: one prompt-box layout for the home page and every studio page, in the
pattern people already know from chat apps.

## What the best products do

| | Attach | Mic and voice | Send | Web search |
|---|---|---|---|---|
| ChatGPT | One "+" at the bottom left; upload and library in one menu ([teardown](https://aiuxplayground.com/teardowns/chatgpt/composer), [release notes](https://help.openai.com/en/articles/6825453-chat-gpt-release-notes)) | Dictation mic on the right, next to send | Round icon | Mode in the "+" menu |
| Gemini | One "+" at the left: Upload files, Drive, Photos ([9to5Google](https://9to5google.com/2026/03/24/gemini-plus-menu-redesign-early-2026/)) | Mic on the right; Live is its own button | Round icon | Automatic |
| Claude.ai | One "+" at the lower left ([help](https://support.claude.com/en/articles/11176164-use-connectors-to-extend-claude-s-capabilities)) | Dictation mic and a separate voice-mode button ([help](https://support.claude.com/en/articles/11101966-use-voice-mode)) | Round icon | Toggle in "+" |
| Google Flow | One Add button: upload or project assets ([help](https://support.google.com/flow/answer/16353334?hl=en)) | — | — | — |

## Decisions

1. **One "+" button at the bottom left** of every composer: "Upload files" and
   "From library" in one small menu (shared `composer_add_menu`).
2. **Dictation mic next to send** on every composer (browser speech-to-text,
   hidden where the browser can't do it). It types into the prompt box.
3. **Send is a round icon-only arrow**, icon centred. On the home page the
   "Create image" pill becomes the same round send button.
4. **Voice conversation stays its own button.** On the home page "Talk to the
   studio" moves inside the prompt box, to the left of send.
5. **Search grounding is on by default** in Image Studio for models that
   support it; the chip is removed.
6. **Studio header:** icon to the left of the title; the info button sits to
   the right of the one-line purpose (shared `header(centered=True)`, so every
   studio and demo page gets it).
7. **Empty state:** no dashed outline and no hint sentence under the title;
   icon centred in its tile.
8. **Home:** remove the "Google Cloud · Vertex AI" eyebrow and the line under
   the call button.

## Where

- `components/header.py`, `components/composer/composer.py` (+ new
  `dictation.js`), `components/result_grid/result_card.py`
- `components/home_prompt/home_prompt.js`, `components/live_agent/live_agent.js`,
  `pages/home.py`
- `pages/gemini_image_generation.py`, `pages/veo.py`, `pages/lyria.py`,
  `pages/voice.py` (empty-state hints, attach menu)
- `assets/ui/studio.src.css` → `node scripts/ui/build_theme.mjs`
