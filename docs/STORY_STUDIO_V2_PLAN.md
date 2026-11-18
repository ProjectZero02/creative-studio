# Story Studio v2: films that sound right, and an editor

Date: 2026-11-18. Scope: `src/services/story_*`, `src/pages/story_studio.py`, `src/components/story_studio/`.

## What was wrong (sample `film_e75f9acc.mp4`: 3 spoken 8 s clips)

1. **Voice speeds up and slows down.** With "Same voice in every scene" (on by default) every on-camera line was thrown away and re-voiced with Gemini TTS, then time-warped piece by piece (`warp_voice`, ffmpeg `atempo` 0.6x to 1.8x) to land on the words Speech-to-Text heard in Veo's audio. Each piece gets its own speed, so the voice lurches.
2. **Lip sync is poor.** A different performance squeezed onto someone else's mouth never matches, however it is warped.
3. **Clip sound is lost.** The dubbed scenes drop Veo's audio and keep only a looped "room tone" made from the quiet frames.
4. **Levels jump between clips.** Each Veo clip is mixed at its own loudness. Music sits at a flat 35 % under speech, with no ducking and no loudness normalisation.
5. **No editing.** The output is one baked MP4; changing anything means re-rendering through the wizard.

## Research (cited in the session report)

- Veo has no voice reference or speaker control. Native Veo speech is the only source with exact lip sync.
- Voice conversion (Seed-VC, GPL; Chatterbox VC, MIT) can make one voice and keep the timing, but needs a GPU service (Cloud Run L4). That is a paid change, so it is left as a pluggable later step.
- TTS-first then lip-sync (LatentSync, Apache-2.0, 18 GB VRAM) gives the best result but is the same GPU cost and more effort.
- Veo 3.1 extension (`video` input, +7 s) continues a clip from its last second and is the best free lever for the same voice and the same shot across a long speech.
- Mixing: duck music with `sidechaincompress`, normalise the master with `loudnorm` (-14 LUFS for web).
- Editors: Twick (Sustainable Use licence) and designcombo (paid tiers) are not usable. OpenCut (MIT) is mid-rewrite. So: our own small timeline using the common `tracks[].clips[]` JSON shape, rendered server-side with ffmpeg.

## Plan

### Sound
- **Default: Veo's own speech.** Spoken scenes keep the clip audio (exact lip sync, natural pace, real ambience). "One fixed voice" stays as an opt-in.
- **No more time-warping.** The fixed-voice option now plays the line at one steady speed (at most ±8 %), starting when the person starts talking.
- **Continuous takes** (on by default for back-to-back spoken scenes): the next spoken scene extends the previous clip with Veo extension, so it is the same shot and Veo hears how the person sounded. The extension's new seconds are cut out by the timeline (`in` point).
- **One seed per film** for every clip, which steadies the look and voice Veo picks.
- **Even levels:** each clip's dialogue gets a measured gain to -20 LUFS. Music ducks under speech with a sidechain compressor. The master is normalised to -14 LUFS. Short fades at every audio cut stop clicks.

### Editor ("Edit" step, replaces the plain Video step)
- The render step writes a **timeline** (`Story.timeline_json`) before it renders:
  `{fps, width, height, tracks: [video, voice, music, text]}`, each clip `{id, src, start, in, out, gain, fade_in}` (text clips `{text, start, dur, pos, size}`).
- `<story-timeline>` web component: preview player that plays the timeline live (video, voice, music, text overlays), track lanes with clips drawn to scale, drag to move, drag edges to trim, reorder video clips, per-clip volume, add, edit and delete text, zoom, undo.
- **Export** renders the timeline with one ffmpeg `filter_complex` pass (no MoviePy), saves the MP4 and adds it to the library.
- Music: generate with Lyria, or upload your own audio file.

### Later (needs the owner's yes: GPU cost)
- Voice conversion of the dialogue stem to one voice per character (Chatterbox VC or Seed-VC on a Cloud Run L4 job).
- Lip-sync pass (LatentSync) for TTS-first dialogue.

## Sets (added later, see `docs/handoff/STORY_SETS_PLAN.md`)
- A **Set** holds a story's characters (looks, views and voice), locations, props and style. It is owner-only and can be reused: a new story picks a set on the Create step, or one is made from the story on the new **Set** step (between Scenario and Storyboard).
- Auto-build makes one Gemini casting call, then the images with Nano Banana: a character's front first and its other views from it, a location's plate then an angle, one image per prop, plus a voice sample per character. Each image can be regenerated, locked, uploaded or picked from the library.
- Rendering sends the set as references: the storyboard frame, then the cast faces and fronts, the location plate and props, capped at the lower of the model's limit and `STORY_MAX_CLIP_REFERENCES` (6). Props are dropped first, then extra views. Prompts describe the cast and use the speaker's voice description word for word.
- Each change bumps the set's version; a film made with an older version shows "Set changed since this film was made" on the Edit step.
- Voice limits: the narrator's Gemini TTS preset is consistent. The on-camera voice is best effort (a fixed description plus the Omni thread per take), so sets fix the look but cannot promise an identical on-camera voice across takes.
