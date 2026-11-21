# Studio extras plan

Features that the app did not have yet, chosen after a survey of every page
and service (November 2026). Seven are built in this branch; three are
planned here for later and deliberately **not** built.

| Feature | Status |
| --- | --- |
| 1. Subtitles for Story Studio films | Built |
| 2. Film versions and side-by-side compare | Built |
| 3. Usage and cost page | Built |
| 4. Favourites and collections in the Library | Built |
| 5. Prompt history in the studios | Built |
| 6. "Done" notifications | Built |
| 7. Brand kit | Built |
| 8. Re-export a film in other shapes | Future |
| 9. Share links | Future |
| 10. Batch runs | Future |

---

## 1. Subtitles (Story Studio)

**Why.** Most social video is watched muted. Films can be dubbed into a
second language but had no captions at all.

**How.**
- `services/story_subtitles.py` (pure, unit tested) builds cues from the
  story: each scene's narration is timed to its voice clip, an on-camera line
  to its video clip. Long lines are cut into short cues (two lines of about 42
  characters) whose length follows the word count.
- Output: `.srt` and `.vtt` text, and caption clips for the timeline's
  existing text track. Caption clips carry `"sub": true`, so turning
  subtitles off or rebuilding them never touches the user's own titles.
- Styles: **Clean** (white with a soft shadow, the current title look),
  **Boxed** (white on a dark rounded box) and **Bold** (larger, outlined).
- Edit step: a "Subtitles" switch, a style choice and "Download .srt". The
  switch rebuilds the caption clips and marks the film as edited, so Export
  renders them.
- Arabic and other scripts: captions are drawn with a font that has the
  script (Noto in the container, Arial Unicode or Segoe UI on Windows) and
  laid out right to left with Pillow's shaping. The Dockerfile adds
  `fonts-noto-core` and `libfribidi0`.

## 2. Film versions and compare (Story Studio)

**Why.** Undo only goes back one fix, so trying the AI fix felt risky.

**How.**
- `Story.film_versions_json`: the last 8 films, each with its timeline,
  time and a label ("First render", "Export", "After fix: ...").
- Recorded wherever a new film is saved (render and export).
- Edit step: a Versions list. **Compare** opens the chosen version next to
  the current film in a small player that plays both in sync. **Use this
  version** brings back that film and its timeline (scenes, frames and the
  set stay as they are; the fix's Undo still restores those).

## 3. Usage and cost page

**Why.** Story Studio has cost caps, but nobody could see what they spent.

**How.**
- `common/usage.py` stores every model call (owner, model, page, status,
  units) in a Firestore `usage_events` collection, best effort and off the
  request thread. `log_model_call` already runs for every generation, so it
  writes there too.
- Background jobs (Story Studio, Live) run in threads where the page state is
  not available; they now set the owner in a context variable so their calls
  are counted for the right person.
- `config/pricing.py`: an estimate per model (per image, per second of
  video, per track...). The page always says "estimate".
- `/usage` page: the last 7 or 30 days, totals per model and per day, with a
  simple bar chart. Admins can switch to "Everyone" and see a per-user table.

## 4. Favourites and collections (Library)

**Why.** There was no way to star a result or group results.

**How.**
- `common/library_marks.py`: one Firestore document per user with starred
  ids and named collections (ids per collection).
- Library: a star and an "Add to collection" control in the item dialog,
  and a filter row with **Starred** and a collection picker.

## 5. Prompt history

**Why.** Reusing a good prompt meant finding it in the Library.

**How.**
- The user's recent prompts per studio come from their own library items
  (no new storage).
- A history button in the composer (Image, Video, Music, Voice) opens the
  last prompts for that studio; picking one fills the prompt through
  `services/page_forms.py`, the same path the Live agent uses.

## 6. "Done" notifications

**Why.** Films and videos take minutes; people leave the tab.

**How.**
- A small `<gm-notify>` component in the page scaffold. Python calls
  `notify(title, body)`; the browser shows a system notification only when
  the tab is in the background and the user turned notifications on.
- A switch in the user menu asks the browser for permission and remembers
  the choice in this browser.
- Hooked into the end of image, video, music, voice and Story Studio jobs.

## 7. Brand kit

**Why.** Brand adherence could be checked, but a brand could not be saved
and applied.

**How.**
- `common/brand_kit.py`: one Firestore document per user with a name, up to
  five colours, a tone of voice and a logo.
- `/brand` page to edit it.
- Story Studio: "Use my brand kit" on the Create step adds the colours and
  tone to the scenario and picture prompts, and puts the logo in a corner of
  the exported film.
- Image Studio: an "Apply brand" switch adds the colours and tone to the
  prompt.

---

## Future (planned, not built)

### 8. Re-export a film in other shapes

Make 9:16, 1:1 and 16:9 versions of one story.

- Not built because every frame and clip would have to be generated again in
  the new shape (Veo and the image models make one aspect ratio per call);
  cropping a 16:9 film to 9:16 loses most of the picture.
- Plan when wanted: "Make another shape" on the Edit step clones the story
  with the new aspect ratio, keeps scenario, set and music, regenerates
  frames and clips (paid, shown in the preview like a fix), and links the
  copies so the Versions list can show them together. A cheaper first step
  could be smart cropping for close-up scenes only, with regeneration for the
  rest.

### 9. Share links

A view-only link to a result or a film for someone without an account.

- Not built at the user's request.
- Plan when wanted: a `shares` collection of random tokens (owner, media id,
  expiry), a public `/s/<token>` route that streams a short-lived signed URL
  and nothing else, revoke from the item dialog, and an admin switch to turn
  sharing off for the whole deployment.

### 10. Batch runs

Run one prompt across several models or settings, or a list of prompts, and
pick the best from a grid.

- Not built at the user's request.
- Plan when wanted: a Batch tab in the composer that builds a list of
  (prompt, settings) runs, submits them through the existing job runners
  with the per-user concurrency cap, shows a results grid with a "keep" mark
  and a cost estimate before starting (from `config/pricing.py`).
