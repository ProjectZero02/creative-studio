# UI consistency audit (2026-11-18)

Purpose: one set of rules for buttons, fields, cards and copy on every page, so
the studio looks like one product. Measured locally (mock generation, port
8099) at 1440 x 900 and 390 x 844, dark and light, plus Arabic (RTL), with a
script that reads every visible button's size, radius and border, finds sibling
buttons that differ, and finds side-by-side cards of different heights.

Builds on 3633ebe6 (secondary buttons tonal, softer fields).

## The rules

| Rule | Where it lives |
| --- | --- |
| One control height: 40 px on desktop, 44 px on phones (`--gm-control-h`). | `src/assets/ui/studio.src.css` |
| One radius family: `--gm-radius-sm/md/lg/xl`; buttons use `md`. | `studio.src.css` |
| One filled primary per view. Secondary = tonal fill (`--gm-tonal*`), no outline. Quiet = text button. | `studio.src.css`, pages |
| Buttons in one row under an image well are the same width and height, icon or no icon. | `.gm-demo-actions` in `src/assets/ui/demos.css` |
| Upload buttons carry an icon like "From library" does. | `demo_upload_button()` in `src/components/demo_flow/demo_flow.py` |
| Side-by-side cards share height, and their heads line up with or without a hint line, so wells and buttons align. | `.gm-demo-pair` in `demos.css` |
| A card that holds only a text field grows the field to the card's height. | `.gm-demo-fill` in `demos.css` |
| Primary action sits bottom-right of the step, on the card edge; nothing floats over it. | `.gm-demo-bar-actions`; round mic in `live_agent.js` |
| Toggle groups never show a bright outline or check marks; filters use the pill switch. | `.gm-segmented`, `.gm-filter-row` in `studio.src.css` |
| Fields: soft fill + faint hairline, brand colour only on focus. | `studio.src.css` (3633ebe6) |
| Card hints only say what a good input looks like; no hint that repeats the title or the empty state. | `demo_card_head(number, title, hint="")` |

## Per page

### Interiors (`/interior_design`)
Before:
- "Upload plan" 130 x 40 next to "From library" 162 x 40; only one had an icon.
- Primary "Generate 3D view" 44 px tall, card buttons 40 px.
- Hint "A furnished 3D model of the whole plan." repeats "Your 3D view appears here".

After: both buttons 253 x 40 with icons; primary 40 px; output hint removed and
the card heads keep one height so the two wells line up; "Rooms" hint shortened
to "Pick a room to restyle it."

### Product 360 (`/object-rotation`)
Before:
- "Upload photo" 140 x 40 vs "From library" 162 x 40.
- Description card had no number (photo card had "1") and a 6-row box that
  left half the card empty beside the tall photo card.
- Step 2 showed two filled buttons at once ("Generate 4 views" and "Next").
- Filler hints: "Veo turns the four views into one smooth spin."

After: buttons 253 x 40; description is card "2" and its field fills the card
(both cards 488 px, field 362 px); in step 2 "Generate" is filled until the four
views exist, then it becomes tonal "Generate again" and "Next" leads; filler
hints shortened or removed.

### Fashion (`/fashion`)
Before: "Upload photo" 140, "From library" 162, "Create virtual model" 185 wide
in one row; action bar buttons 44 px vs 40 px elsewhere; on a 1440 x 900 screen
the "Talk to the studio" pill covered "Try it on".

After: three equal buttons per card ("Create virtual model" is now "Generate
model" so it fits); bar buttons 40 px; the floating mic is a 48 px round button
(label on hover/focus) and no longer covers the primary.

### Brand kit (`/starter-pack`)
Before: same unequal Upload / From library / Use a sample row; "Create virtual
model" too; "Start over" and "Create brand kit" 44 px; the mic pill covered
"Create brand kit"; filler hint "A collage of matching pieces, colours and props."

After: equal buttons, 40 px bar, primary visible, hint removed.

### Library (`/library_v2`)
Before: three Material toggle groups with a bright grey outline
(`rgb(115,122,134)`), dividers and check marks, unlike every other switch in
the app; long empty-state copy; "End of list" printed under "Nothing here yet".

After: the same pill switch as Video Studio's modes, wrapping and centred; one
short empty-state line; "End of list" only shows when there are items.

### Image Studio, Video Studio, Voice, Music (composer pages)
No sibling-size mismatches or bright outlines found. The mode switch (Video
Studio) uses label-width pills by design. Only change: the round mic.

### Home
Buttons live inside web components (not measured by the script); visual check
shows no outlines. No change.

### Story Studio (`/story`) — not changed here
Another session is editing `pages/story_studio.py`, `assets/ui/story.css` and
the timeline files. Items for that session:
- "Get started" is 44 px tall on desktop (story.css); use `var(--gm-control-h)`.
- The step bar draws an outlined box per step; use the demo step indicator
  (`demo_steps`) or the tonal fill so it matches the other workflows.
- Secondary buttons in the Edit step are `type="stroked"`: they already get the
  tonal fill from the theme; check sibling rows share width where they sit
  side by side (same pattern as `.gm-demo-actions`).

### Hidden legacy pages (`SHOW_LEGACY_PAGES`)
Not audited one by one; they get the global rules (control height, tonal
secondary buttons, toggle groups without bright outlines).

## Checked
- 1440 and 390, dark and light: Interiors, Product 360, Fashion, Brand kit,
  Library, Video Studio. No horizontal scroll at 390.
- Arabic (RTL) at 1440: Brand kit mirrors correctly, equal buttons, mic moves
  to the left corner.
- Tests: `test_app_imports`, `test_i18n`, `test_interiors_layout`,
  `test_live_agent`, `test_object_rotation_library`, `test_page_headers`,
  `test_read_authz`, `test_ui_layering` (95 passed).
