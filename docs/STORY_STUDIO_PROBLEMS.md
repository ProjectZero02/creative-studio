# Story Studio: remaining problems (scan of 2026-11-25)

Three passes: render pipeline code, step/state code, and a mock-mode run of three films (one 30s take, a 4-shot narrated film, music only). Read-only; nothing changed. "Seen" = reproduced in the browser, "Code" = confirmed by reading the code, "Likely" = not proven.

## A. Throws away finished work

1. **Clicking in and out of the Music prompt deletes the film and the music.** `pages/story_studio.py:2559` `_set_story_field` always runs `clear_films()` and clears `music_uri` on blur, with no "did it change" check. The box shows the default prompt when the stored one is empty, so a blur even writes new text. Next "Make film" pays Lyria again and re-stitches. Same unguarded clear for voice, music on/off and voice on/off. This is the "go back, come forward, must re-render" bug. *Seen.* Fix: skip when the value is unchanged; a music change should only re-mix, not clear the film.
2. **Blurring a narration or scene box can clear the film (and the clip for on-camera lines)** when the stored text has stray whitespace. `story_studio.py:1591` compares stripped vs unstripped text. *Likely.*
3. **Setup's only button after a film exists is "Write breakdown"**, which wipes scenes, set and films and re-runs everything. Setup changes that don't need a rewrite (aspect, resolution, engine, language, style, brand, Arabic) are never saved otherwise. *Seen + Code.* Fix: save those on change; ask only when idea, length or speech changed.
4. **"Make film" and "Paint start frames" ignore unsaved Set edits** (`on_render` :2693, `on_paint_all_frames` :1903). *Code.*
5. **A breakdown can be started while a render runs**; the old job keeps spending and can no longer be cancelled. No one-job-per-story guard on the server. *Code.*

## B. Steps that run no matter what kind of film it is

6. **Stitching always runs** (`services/story_jobs.py:867`). For one clip / one continuous take it still downloads everything, runs edge, loudness and sound checks, re-encodes with the logo, decodes the film twice for seam checks, and uploads. One-take joins have no fades, so "crossfades" is also wrong. *Seen + Code.* Fix: one segment with nothing to mix → use the clip (or stream copy + audio only); run the frame scan once.
7. **Voiceover is remade on every render and every Retry.** Scenes don't keep their voice file, so TTS and "Fitting the narration" run again even when no line changed. *Code.* Fix: store the voice file plus a key (text, voice, language) per scene and reuse it.
8. **"Make the second-language film" redoes the main film too**: re-voices, re-stitches and saves another English copy. *Code.* Fix: an alt-only job.
9. **The set job makes images and voice samples nothing uses**: 4 views + a voice sample per character, 2 per location; only face/front/plate are used for frames. *Likely.*
10. **Stitching can silently pay to remake clips** (seam/turn redo, `story_jobs.py:1254`) inside the "Stitching" step, with no notice. Fast motion in a long take can trigger it. *Code.* Fix: its own visible step, or ask first.
11. **Every render and film export adds another library item**, and records the config model, not the one used. *Code.*

## C. Wrong film type

12. **"One continuous take" is only detected from English keywords** ("one shot", "continuous", "no cuts"). "A 30-second video of a guy talking" or any Arabic idea becomes ~4 shots and gets stitched. Setup has no One take / Shots choice. *Code.*
13. **No "No speech" option.** The script prompt demands a line per scene; music-only or visual-only films still get lines and TTS unless every line is cleared. With narrator off, Frames still shows "Voiceover:" lines, and a single take gets an empty 3-turn voice track. *Seen + Code.*
14. **Setup's blueprint contradicts itself**: "1 continuous take" and "4 × ~8s shots" for a 4-take film, separate shots labelled "continuous", a Voice cost line on a music-only idea. *Seen.*

## D. Steps locked or out of sync

15. **Takes, Music and Edit & Export stay locked for any take made of several shots.** `services/story_models.py:2648` wants every shot to have a frame, but only the first shot of a take gets one. Once the film is cleared, Edit & Export can't be reopened. Fix: use `frames_ready(story)`. *Code.*
16. **Edit & Export still shows the old film after it was cleared**, with no "out of date" notice. *Seen + Code.*
17. **Reload doesn't return to the step you were on** (`story.step` is saved but never read). *Code.*
18. **Each "Write breakdown" in one session builds a brand-new set** (re-casting + all images, a new copy in the set library); after a reload it reuses the old one. *Code.*
19. **Reopening Setup lets auto-settings overwrite hand-set values**, and each typing pause fires an uncached Gemini call; a late reply can apply settings from older text. *Code.*

## E. Correctness

20. **Cancel doesn't stop a stitch that's already running**, and the cancelled result still replaces the film. *Code.*
21. **Retry on a failed export forgets its settings** (1080p, subtitles, WebM) and retries as the default MP4 (`story_jobs.py:2324`). *Code.*
22. **Shortening a narration line keeps the old translation**, so the Arabic film uses the longer line. *Code.*
23. **With more than one Cloud Run instance, a re-render can look finished at once** (old film counts as ready); set/music/translate jobs spin for minutes. *Likely.*
24. **Export defaults to 360p for a 720p film**, and the Arabic price shows "About 0.00 USD" in Edit vs "+$12.00" in Setup. *Seen.*
25. **"Write breakdown" is enabled with an empty idea** and does nothing, no message. *Seen.*

## F. Progress and wording

26. **Progress numbers disagree**: "2 of 6 steps done" next to 40%, "10 of 12" next to 87%; several steps say "Done · 0s". *Seen.*
27. **"Working on your film" panel and "Your film is ready. Edit it below" banner show on every step**, where "below" is wrong. *Seen.*
28. Leftover copy: "Go to Director's Desk" (screen no longer exists), "Clips, music and voiceover are generated in parallel, then stitched" (wrong for one-take and music-only), "Next: the set and start frames are made for you.", "1 shots", "Turns | No cuts found". Music is set in two places with different controls. *Seen + Code.*
29. A 30s request came out 29s. *Seen.*
