# Story Studio audio plan: a natural ending, and voice-over that fits

Status: built (2026-11-24, branch `audio-fit`), tested with mocks and
local renders (`test/test_story_audio.py`). Not yet checked on a live film.

Found while building: once the ending can hold for a breath, the dialogue
ends before the film, and the ducking compressor then stalled ffmpeg now
and then (the render never finished). Both the dialogue and the music are
now padded to fixed lengths before ducking; 8 of 8 held renders finish.

Two problems:

1. The film's sound stops abruptly at the end.
2. In voice-over films, lines are spoken slowly, cut off, and the next line
   starts straight after.

## 1. The ending

### What we measured (720p test film, 2026-11-24)

- **Speech runs to the last moment.** Omni spoke the last line until
  28.85 s of the 30 s take. There is no breath after the last word; the
  prompt never asks for one.
- **The music drops out at 29.0 s, the moment the speech ends.** It falls from
  about −15 dB to silence within 0.1 s. The timeline asks for music until
  30 s with a 1 s fade.
  - A local re-render of the same timeline, and a local run of the app's own
    film step on the same files, are identical sample for sample up to 29.0 s
    and keep the music fading to 30 s.
  - So the dropout happens only in the running app's render. The cause is not
    found yet.
- **The fade is short:** 1 s for the film's music. Editors usually give the
  music 2–5 s at the end
  ([CapCut](https://www.capcut.com/features/how-to-fade-out-audio-capcut-workflow)).

### Fix

1. **Find the dropout.** Render inside the app process (the Export path and
   the first-film path) and bisect the ffmpeg graph: ducking, `loudnorm`,
   `-stream_loop`, padding. Fix it. Add a test that renders a film and checks
   the music is still playing in the last second, until its fade.
2. **A breath at the end.** The last turn of the last take finishes speaking
   about 1.5 s before the take ends. Its word budget is 1.5 s smaller, and its
   prompt says "finish speaking, then hold: a nod, a smile, looking at the
   audience".
3. **Music outro.**
   - The film's music fades over its last 3 s (`STORY_MUSIC_OUTRO`, default
     3.0).
   - The ducking lets the music swell back up after the last word.
   - The take's own sound fades over its last 0.5 s.
4. **Safety net.** After the render, if speech still ends within 0.8 s of the
   end, hold the last frame for 1 s and fade the picture to black under the
   music fade.
5. **Check.** After every render, measure the last 2 s of sound. A fall of
   more than 20 dB in under 0.2 s is an abrupt end: it is logged and shown on
   Takes.

## 2. Voice-over that fits

### What we measured (25 narrator lines from 6 past live films)

| | Planned | Measured |
|---|---|---|
| Words a second | 2.5, plus 15% slack (about 2.9 allowed) | median **1.75** (range 1.13–2.45) |
| Lines cut short | – | **19 of 25** |
| Lines sped up | up to 18% | **0** (all were further over, so they were cut) |
| Silence before each line | – | 0.26 s |

Example: a 4 s scene got 9 words. Voiced, that is 4.7 s, but the room for it
is 3.7 s (0.25 s in, 0.05 s gap), so it is cut, and the next line starts 0.05 s
later.

Causes:

- **The word budget assumes a pace the narrator doesn't speak at.** The
  budget is `WORDS_PER_SECOND = 2.5` (`story_models.py`), plus
  `NARRATION_SLACK = 1.15`. The script writer uses 2.4.
- **Every line is a separate text-to-speech call with no pace target**, so
  the pace changes from line to line, nearly two-fold.
- **Placement cuts instead of fitting.**
  - `build_timeline` speeds a line up only if it is at most 18% too long;
    otherwise it cuts it at the scene end.
  - `no_overlap` cuts any line that would run into the next one.
  - That is the "spoken slowly, cut, and the next one talks over it" effect.

How others do it:

- In [Pictory](https://kb.pictory.ai/en/articles/8468916-how-to-adjust-the-duration-of-a-scene)
  the scene is at least as long as the AI voice takes to read it.
- [HeyGen](https://help.heygen.com/en/articles/9143288-ai-studio-getting-started-tutorial)
  ("Auto Link") and
  [Vyond](https://product.vyond.com/auto-fit-scenes-to-match-text-to-speech-audio-length/)
  fit the scene length to the voice.
- [Synthesia](https://www.synthesia.io/updates/match-to-script) stretches the
  background video to the script.
- None of them cuts a line.

### Fix

1. **Measure the narrator's real pace, once per voice.**
   - When the set's narrator voice sample is made, measure its words a second
     (speech only, without the silence) and store it on the voice.
   - Use 1.8 until it is measured.
   - The same number is used for the whole film.
2. **One word budget from that pace.**
   - Budget = (scene length − 0.25 s before the line − 0.5 s breath after) ×
     pace × 0.95.
   - The script writer, the Script step's "About N words fit" and the fit
     check all use it. Drop the 15% slack.
   - A line over budget is rewritten shorter by Gemini before it is voiced.
     The rewrite-when-too-long retry exists; it gets the new budget.
3. **The same speed in every line.**
   - Every text-to-speech call gets the same voice, style and pace direction
     ("a steady, even pace").
   - After voicing, each line is measured. A line that still doesn't fit is
     rewritten shorter and voiced again, once.
   - No line is sped up on its own. As a last resort, one small speed-up (at
     most 8%) is applied to every line of the film alike, so they all match.
4. **Never cut a line mid-word.**
   - A line may run up to 0.5 s into the next scene when that scene's line
     starts later.
   - Otherwise the next line waits; lines never overlap.
   - If something must give, the line ends at a pause between words, with a
     fade.
5. **Later, a bigger option: voice first.** Voice every line, then pick each
   scene's length from it (as Pictory and HeyGen do). This fits Veo's
   4/6/8 s clips well, but Omni's fixed 10 s turns less well, so it is not
   part of this plan.

## Tests and checks

- Unit tests:
  - the budget from a measured pace;
  - a line that doesn't fit is rewritten, not cut;
  - one film-wide speed-up;
  - J-cut placement never overlaps;
  - the ending's music fade and breath;
  - the abrupt-end check.
- A mock-mode browser check of the Script step's word counter.
- Two live runs, about $12 each, each waiting for your yes:
  - the on-camera test prompt again, for the ending;
  - a 30 s voice-over film with 4–6 s scenes, for the narration.
- Done means:
  - no line is cut;
  - the measured pace varies less than 10% between lines;
  - the last word ends at least 1 s before the end;
  - the music fades out over the last 3 s.
