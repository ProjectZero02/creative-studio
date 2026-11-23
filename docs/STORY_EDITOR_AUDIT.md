# Story Studio editor audit (Timeline & Export)

Date: 2026-11-23. Scope: the `<story-timeline>` editor, its Python side, AI Fix and export. Read-only audit; no app code changed.

**Recommendation: (b) simplify to a lean editor on top of the v4 Phase D proxy player.** Keep the shot strip (reorder, trim, split, delete), titles, transitions and two volume controls. Drop the live multi-`<video>` preview, free dragging of voice and music clips, and the per-edit full-timeline sync. Fix the three data-loss bugs first, since they hit any version of the editor.

## How it was tested

- `genmedia-story-demo` launch config (port 8098, mock mode), Edge-based browser pane at 1440×900.
- New story → "Lighthouse and whale" → Write breakdown → Paint all frames → Render film (4 shots, 24 s) → Timeline & Export.
- Tried play/pause/seek, Split, Delete, Add title, undo/redo, zoom, select and edit, voice/music lanes, Make music, Export, Download, subtitles and AI Fix, through clicks and through the component's own methods (`el._set`, `el._undoLast`, …). Instrumented playback at 100 ms steps.
- Read `story_timeline.js`, `timeline_view.py`, `story_timeline.py` (`normalize`, `keep_edits`, `render_args`), `story_jobs.py` (`save_timeline`, `start_export`, `start_subtitled`), `story_fix.py` and the Downloads panel.

Mock clips are small local files, so the preview stutter seen live with remote files did **not** show up here: element swaps landed on `readyState` 4 with no clock freeze. The stutter causes listed in the brief come from code reading and the live test. They are not reproduced in mock mode.

## Bug list

Severity: **High** = loses work or ships a wrong film. **Medium** = wrong or confusing, with a workaround. **Low** = polish.

| # | Sev | Bug | Repro | Where |
|---|-----|-----|-------|-------|
| 1 | High | **Edits are lost when the server's echo of an older edit arrives.** Every edit sends the whole timeline. The server saves it and sends back `json.dumps(normalize(...))`. That string never equals the editor's own `JSON.stringify`, so each echo replaces `_tl`. An echo of edit A that lands after edit B reverts B on screen, and the next edit C is built on the A-only state, so B is gone for good. | Change clip A's volume, 30 ms later change clip B, then after B flips back change clip C. B is lost **5 of 5 times** locally. On Cloud Run latency the window is hundreds of ms, so quick slider moves or drag-then-click are enough. | `story_timeline.js:243-249` (`willUpdate`), `:342-349` (`_commit`); `story_studio.py:3053` (`on_timeline_change`) |
| 2 | High | **AI Fix (and any re-render from Director's Desk) wipes manual edits.** `keep_edits` gives up on all video edits (order, trims, gains, transitions) as soon as one scene was split. Deleted parts come back. Voice gains and moved voice lines are never carried over. Music trims are dropped too; only the first music clip's gain is kept. Only titles survive. | Split shot 2, delete half of shot 3, set shot 4 to 150 %, set voice 2 to 40 %, then AI Fix → "Apply and generate". Result: the original 4 × 6 s shots with default gains. Only the title remains. | `story_timeline.py:324-348` (`_keep_video_edits`, "a split scene: too ambiguous", line 334), `:351-367` (`keep_edits`) |
| 3 | High | **The editor is re-created whenever a panel opens above it**, which loses undo/redo history, playhead, selection and zoom, and stops playback. This happens on the Music toggle, every progress panel (export, music, fix, subtitles) and the fix plan card. After an export or AI Fix, Ctrl+Z does nothing. | Make an edit (undo = 1, playhead 5 s). Click **Music**. The element is a new instance: undo = 0, playhead 0. | `timeline_view.py:273-306` (conditional siblings before the component at `:308-316`) |
| 4 | High | **Preview does not match the export.** (a) Clip sound hard-cuts at every element swap; the render fades each edge (`JOIN_FADE`) and adds a 0.16 s ambient tail. (b) Dip to black: the preview fades out, then in, inside the overlap. The render dips *before* the next clip starts and then fades up over the full length, so it is about 1.5× longer and earlier. (c) Bridge joins get `eq=brightness` colour matching only in the render. (d) Ducking: the preview applies a flat ×0.35; the render uses a sidechain compressor. (e) Volume 100–200 % sounds the same in the preview (`volume` is clamped to 1), and the render's final `loudnorm` evens levels out anyway. (f) Titles: the preview uses CSS text; the render uses PNG overlays, and `style` is neither shown nor editable. | Set a Dip to black, or a clip to 200 %, then compare the preview with the exported file. | `story_timeline.js:584`, `:618-629`, `:666-690`; `story_timeline.py:846`, `:866`, `:884`, `:939`, `:955` |
| 5 | High | **Preview stutters and cuts at clip boundaries** (seen live, not in mock). Every boundary swaps `<video>` elements (`active`→`next`→`scrub`). `src` is reassigned when the pool is short. Preload only starts within 4 s of the next clip. The clock freezes while `readyState < 3`. | Play a live film from remote storage across a join. | `story_timeline.js:461-477`, `:509-523`, `:634-648` |
| 6 | Medium | Deleting part of a split shot leaves that shot's voice line in place, so it **overlaps the next shot's line** (two narrators at once). `_follow` keeps the line if any part of its scene remains, even when the part left is shorter than the line. | Split shot 3 at 0.8 s, delete the second half. Voice 3 (12.25–14.6 s) overlaps voice 4 (13.05 s). | `story_timeline.js:315-328` (`_follow`); same rule in `story_timeline.py:286` |
| 7 | Medium | **Download points to a stale film** after an edit. The header **Download** stays live while "Edited since the last export" shows; the Downloads panel hides its own button. | Edit anything, then click Download in the header: you get the previous export. | `timeline_view.py:244-255` |
| 8 | Medium | **Download opens the MP4 in a new tab instead of saving it.** There is no `download` attribute and `/story-media/...` sends no `Content-Disposition` (only the `.srt` route does). On GCS signed URLs the attribute would be ignored anyway. | Click any Download: the video plays in a tab named `film_3dda1603.mp4`. | `timeline_view.py:249`; `story_studio.py:2684-2693`; compare `story_router.py:78` |
| 9 | Medium | **"Edited since the last export" never clears by undoing.** `film_edited` compares with the *previous save*, not the exported timeline, so undoing back to the exported state still blocks subtitled downloads ("Export your edit first"). | Export, make an edit, undo it. The warning stays and the subtitle buttons stay disabled. | `story_jobs.py:1212-1222` |
| 10 | Medium | **Undo crosses server changes.** The undo stack is not cleared or rebased when the server sends a new timeline (new music, version restore). Undo then writes an old timeline back, with the old music file or clips. In practice bug 3 usually wipes the stack first, which hides this. | Restore a version, then Ctrl+Z. | `story_timeline.js:243-249`, `:356-369` |
| 11 | Medium | No fullscreen, no export options (one 720p/clip-size H.264 at CRF 20 `veryfast`), no audio-only, no format choice. | n/a | `story_timeline.py:963`; `story_service.py:418` |
| 12 | Low | Layout: at 1440×900 the Fix with AI card sits above the editor, so the preview is below the fold. Preview, transport and tracks never fit one screen. The inspector is a tall empty box until a clip is selected. There are four "Download" links on the page. | Open Timeline & Export at 1440×900. | `timeline_view.py:304-316` |
| 13 | Low | The playhead runs off-screen when zoomed in, because there is no auto-scroll during playback. Zoom fits only once (`_pps` is never refit after the film length changes). | Zoom in, then press Play. | `story_timeline.js:538-547`, `:294-298` |
| 14 | Low | Both halves of a split keep the label "Scene 3", and a short half shows as "S.". | Split any shot. | `story_timeline.js:907-916` |
| 15 | Low | Each pause or seek sends a `point` event, which is a full Mesop round trip, to fill "At (seconds)" in Fix with AI. | Scrub while paused. | `story_timeline.js:482-490` |

Worked as intended: split, delete, add title (it appears after one server round trip), undo/redo, reorder (Earlier/Later and drag), trims, transition select, music ducking toggle, Export (new film plus a library copy), English subtitle Make plus `.srt`, Make music.

## What users need (vs best-in-class)

| Need | Google Flow Scenebuilder | Clipchamp / CapCut | Story Studio today |
|------|--------------------------|--------------------|--------------------|
| See the whole film smoothly, fullscreen | Previews the whole sequence | Single smooth preview, fullscreen | Stutters live, no fullscreen |
| Reorder shots | Yes | Yes | Yes |
| Trim each shot's start/end | Handles | Handles | Yes |
| Split / delete | No (trim only) | Yes | Yes |
| Titles / captions | No | Yes | Titles + burned subtitles |
| Transitions | No | Yes | Cut, crossfade, dip |
| Volume per clip, music ducking | No | Yes | Yes (preview ≠ render) |
| Free audio placement | No | Yes | Yes (rarely needed here; voice follows scenes) |
| Export choices | 720p, 1080p upscale, GIF | 480p/720p/1080p/4K, MP4, GIF, audio | One MP4 |
| Real download | Yes | Yes | Opens in a tab |

Flow's Scenebuilder is the closest match: a shot sequence with reorder, trim handles, a sequence preview and download, and no free multi-lane editing. That is the right bar for an AI-film tool whose main editor is AI Fix and Director's Desk. Clipchamp sets the bar for the export menu.

Sources: [Flow: edit videos & build scenes](https://support.google.com/flow/answer/16935718), [Flow FAQ](https://labs.google/fx/tools/flow/faq), [Clipchamp: choosing export resolution](https://support.microsoft.com/en-us/clipchamp/how-to-choose-the-right-export-resolution), [Clipchamp: exporting and saving](https://support.microsoft.com/en-us/Clipchamp/exporting-and-saving-a-video-in-clipchamp).

## Options

**(a) Fix in place.** This means fixing bugs 1–15 inside the current design: a better video pool, matching every render filter in Web Audio and CSS, and patching sync. It is about 2–3 weeks. Most of it is the preview engine, which Phase D replaces anyway, and the preview would still drift from ffmpeg (bug 4). Not worth it.

**(c) Remove it.** A rendered-film player plus an Export menu (Phase D) fixes stutter, mismatch and sync at once. But users lose reorder, trim, split and titles, which Flow treats as the minimum. Every small change would then go through AI Fix or a full re-render, which is slower and costs money. Too far.

**(b) Simplify (recommended).** Use one player and one editing strip:

- **Player:** the Phase D proxy file (one low-bitrate render of the current timeline, rebuilt after each edit, a few seconds in mock), fullscreen, and Space / F / arrow keys. Delete the 3-decoder pool and audio map (`story_timeline.js:420-694`, about 280 lines). The preview *is* the render, so bug 4 and bug 5 go away.
- **Strip (keep):** shot thumbnails in order with drag to reorder, trim handles, Split, Delete, transition per join (Cut / Crossfade / Dip to black), and undo/redo.
- **Titles lane (keep):** add, move, edit text, position and size.
- **Audio (simplify):** no free-drag voice or music lanes. Voice lines stay tied to their scene (the existing follow rule). There are two sliders (Voice, Music) plus the Duck toggle, and per-shot "clip sound" in the shot inspector, capped at 100 %.
- **Export menu:** as in Phase D (resolution up to the source with upscale marked, MP4/WebM/MOV, subtitles none/burned/SRT, audio only), with real downloads (`Content-Disposition: attachment`).

## Fix list (in order)

1. **Sync (bug 1, 10):** add a `rev` counter to the timeline. The editor sends `{rev, timeline}`, and the server answers with the saved `rev`. `willUpdate` ignores any echo whose `rev` is older than the editor's latest, and compares parsed and normalized data instead of strings. Clear the undo stack when an incoming timeline is not one of the editor's own revs. Effort: 0.5 day plus tests.
2. **Remount (bug 3):** give every conditional box in `_render_edit_view` a stable `key`, and render the music, progress and fix panels *below* the editor (or in one always-present slot), so the web component is never re-created. Effort: 0.5 day.
3. **Keep edits on re-render (bug 2):** match old and new clips by `(scene, src)` and keep splits for scenes whose source did not change. Only a scene whose clip was remade starts fresh. Also carry voice gains and moves, and music trims. Add a test: split, delete, gain, AI Fix of one other scene → all kept. Effort: 1 day.
4. **Phase D proxy player plus fullscreen (bugs 4, 5, 12, 13):** add a proxy render job (`render_args` with `preset=ultrafast`, CRF 30, 540p, mock passthrough) that runs after each saved edit, debounced, and the player swaps to the new proxy when it is ready. Remove the video pool. Effort: 2–3 days.
5. **Export menu and downloads (bugs 7, 8, 9, 11):** a single Export button that opens the menu. Downloads are served with `Content-Disposition`, and the GCS signed URL gets `response-content-disposition`. Remove the header Download. Compute `film_edited` against the exported timeline (store `exported_timeline_json`). Effort: 1.5 days.
6. **Voice overlap on delete (bug 6):** when a scene shrinks, trim or drop its voice line so it ends before the next line starts (in JS `_follow` and `follow_scenes`). Effort: 0.5 day.
7. **Trim the editor (b):** remove the free voice/music drag, cap gain at 100 %, label split halves "Scene 3a/3b", and move Fix with AI below the player. Effort: 1 day.

Total: about 7–8 days, with 1–3 shippable alone this week (≈2 days). They are worth doing before Phase D, because they lose user work today.
