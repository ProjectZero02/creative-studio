# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Story Studio timeline: the editable film, and its ffmpeg renderer.

A timeline is plain JSON so the browser editor can change it and the server
can render it::

    {"version": 1, "fps": 24, "width": 1280, "height": 720,
     "tracks": [
       {"id": "video", "kind": "video", "clips": [
          {"id", "src", "start", "in", "out", "gain", "fade_in", "label", "scene"}]},
       {"id": "voice", "kind": "voice", "clips": [{"id", "src", "start", "in", "out", "gain", "tempo"}]},
       {"id": "music", "kind": "music", "duck": true, "clips": [{"id", "src", "start", "in", "out", "gain"}]},
       {"id": "text",  "kind": "text",  "clips": [{"id", "text", "start", "dur", "pos", "size"}]}]}

Times are seconds. A clip plays its source from ``in`` to ``out`` at
``start`` on the film. Video clips also carry the clip's own sound (speech,
ambience) at ``gain``; ``ambient: true`` marks a narrated clip whose sound is
a bed under the voice (it neither ducks the music nor is ducked). The video track is sequential: ``normalize`` lays its
clips end to end, overlapping by ``fade_in`` (a crossfade).

Everything above ``render_timeline`` is pure and unit tested.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import tempfile
import uuid

TRACK_KINDS = ("video", "voice", "music", "text")
TEXT_POSITIONS = ("top", "center", "bottom")
MAX_GAIN = 4.0
# Loudness targets (LUFS): each clip's dialogue, the model's own sound under
# a narrator (an ambient bed), and the finished film.
DIALOGUE_LUFS = -20.0
AMBIENT_LUFS = -30.0
# Gain for a narrated clip whose loudness could not be measured.
AMBIENT_GAIN = 0.25
MASTER_LUFS = -14.0
# Short fade on every audio cut so joins never click.
EDGE_FADE = 0.04


def new_clip_id() -> str:
    return uuid.uuid4().hex[:8]


def empty_timeline(width: int = 1280, height: int = 720, fps: int = 24) -> dict:
    return {
        "version": 1,
        "fps": fps,
        "width": width,
        "height": height,
        "tracks": [
            {"id": "video", "kind": "video", "clips": []},
            {"id": "voice", "kind": "voice", "clips": []},
            {"id": "music", "kind": "music", "duck": True, "clips": []},
            {"id": "text", "kind": "text", "clips": []},
        ],
    }


def track(timeline: dict, kind: str) -> dict:
    """The track of `kind` (created if missing)."""
    for t in timeline.setdefault("tracks", []):
        if t.get("kind") == kind:
            return t
    t = {"id": kind, "kind": kind, "clips": []}
    if kind == "music":
        t["duck"] = True
    timeline["tracks"].append(t)
    return t


def clip_length(clip: dict) -> float:
    if "dur" in clip and "out" not in clip:
        return max(0.0, float(clip.get("dur") or 0))
    tempo = float(clip.get("tempo") or 1.0) or 1.0
    return max(0.0, (float(clip.get("out") or 0) - float(clip.get("in") or 0)) / tempo)


def clip_end(clip: dict) -> float:
    return float(clip.get("start") or 0) + clip_length(clip)


def duration(timeline: dict) -> float:
    """Film length: the end of the last video clip (other tracks are cut there)."""
    ends = [clip_end(c) for c in track(timeline, "video")["clips"]]
    if not ends:
        ends = [clip_end(c) for t in timeline.get("tracks", []) for c in t.get("clips", [])]
    return round(max(ends or [0.0]), 3)


def _num(value, default: float, lo: float, hi: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = default
    if v != v:  # NaN
        v = default
    return min(hi, max(lo, v))


def normalize(timeline: dict | str | None) -> dict:
    """Validate and tidy a timeline from the editor (never trust the browser).

    Unknown tracks and fields are dropped, numbers are clamped, clips without
    a source are removed, and the video track is laid end to end.
    """
    if isinstance(timeline, str):
        try:
            timeline = json.loads(timeline or "{}")
        except ValueError:
            timeline = {}
    src = timeline if isinstance(timeline, dict) else {}
    out = empty_timeline(
        int(_num(src.get("width"), 1280, 64, 3840)) // 2 * 2,
        int(_num(src.get("height"), 720, 64, 3840)) // 2 * 2,
        int(_num(src.get("fps"), 24, 1, 60)),
    )
    by_kind: dict[str, dict] = {}
    for t in src.get("tracks") or []:
        if isinstance(t, dict) and t.get("kind") in TRACK_KINDS and t["kind"] not in by_kind:
            by_kind[t["kind"]] = t
    for kind in TRACK_KINDS:
        given = by_kind.get(kind) or {}
        dest = track(out, kind)
        if kind == "music":
            dest["duck"] = bool(given.get("duck", True))
        for c in given.get("clips") or []:
            if not isinstance(c, dict):
                continue
            clean = _clean_clip(kind, c)
            if clean:
                dest["clips"].append(clean)
    _layout_video(track(out, "video")["clips"])
    for kind in ("voice", "music", "text"):
        track(out, kind)["clips"].sort(key=lambda c: c["start"])
    return out


def _clean_clip(kind: str, c: dict) -> dict | None:
    cid = str(c.get("id") or new_clip_id())[:24]
    start = round(_num(c.get("start"), 0, 0, 36000), 3)
    if kind == "text":
        text = str(c.get("text") or "").strip()[:300]
        if not text:
            return None
        pos = c.get("pos") if c.get("pos") in TEXT_POSITIONS else "bottom"
        return {
            "id": cid,
            "text": text,
            "start": start,
            "dur": round(_num(c.get("dur"), 3, 0.2, 3600), 3),
            "pos": pos,
            "size": int(_num(c.get("size"), 48, 12, 200)),
        }
    srcuri = str(c.get("src") or "").strip()
    if not srcuri:
        return None
    cin = round(_num(c.get("in"), 0, 0, 36000), 3)
    cout = round(_num(c.get("out"), cin + 1, cin + 0.1, 36000), 3)
    clean = {
        "id": cid,
        "src": srcuri,
        "start": start,
        "in": cin,
        "out": cout,
        "gain": round(_num(c.get("gain"), 1.0, 0, MAX_GAIN), 3),
    }
    if kind == "video":
        clean["fade_in"] = round(_num(c.get("fade_in"), 0, 0, 3), 3)
        clean["label"] = str(c.get("label") or "")[:60]
        clean["scene"] = int(_num(c.get("scene"), -1, -1, 999))
        if c.get("ambient"):
            clean["ambient"] = True
        if c.get("src_max") is not None:
            clean["src_max"] = round(_num(c.get("src_max"), cout, cout, 36000), 3)
    if kind == "voice":
        clean["tempo"] = round(_num(c.get("tempo"), 1.0, 0.5, 2.0), 4)
        # The scene this line belongs to: it moves with that scene's clip.
        if c.get("scene") is not None:
            clean["scene"] = int(_num(c.get("scene"), -1, -1, 999))
    if kind == "music" and c.get("src_max") is not None:
        clean["src_max"] = round(_num(c.get("src_max"), cout, cout, 36000), 3)
    return clean


def _layout_video(clips: list[dict]) -> None:
    """End to end; each clip overlaps the previous by its fade (a crossfade)."""
    t = 0.0
    for k, c in enumerate(clips):
        length = clip_length(c)
        fade = 0.0 if k == 0 else min(c.get("fade_in", 0.0), length / 2, t)
        c["fade_in"] = round(fade, 3)
        c["start"] = round(max(0.0, t - fade), 3)
        t = c["start"] + length


# ---------------------------------------------------------------------------
# Building a timeline from a rendered story
# ---------------------------------------------------------------------------


def _linked(clip: dict) -> bool:
    return int(clip.get("scene", -1)) >= 0


def follow_scenes(prev: dict, cur: dict) -> dict:
    """After the video track changed from `prev` to `cur`: move each voice
    line with its scene's clip (drop it when the scene is gone), and keep
    music that ran to the end of the film running to the new end. The same
    rule as the editor's `_follow` (story_timeline.js). Changes `cur`."""
    pv = track(prev, "video")["clips"]
    vids = track(cur, "video")["clips"]
    keep = []
    for line in track(cur, "voice")["clips"]:
        at = float(line["start"])

        def inside(c: dict, at: float = at) -> bool:
            return c["start"] - 0.001 <= at < clip_end(c)

        if _linked(line):
            same = [c for c in pv if c.get("scene") == line["scene"]]
            p = next((c for c in same if inside(c)), same[0] if same else None)
        else:
            p = next((c for c in pv if inside(c)), None)
        if p is None or not _linked(p):
            keep.append(line)
            continue
        line["scene"] = p["scene"]
        src = p["in"] + (at - p["start"])
        now = [c for c in vids if c.get("scene") == line["scene"]]
        if not now:
            continue
        c = next((x for x in now if x["in"] - 0.001 <= src < x["out"]), now[0])
        line["start"] = round(max(0.0, c["start"] + (src - c["in"])), 3)
        keep.append(line)
    track(cur, "voice")["clips"] = keep
    old_end, end = duration(prev), duration(cur)
    for m in track(cur, "music")["clips"]:
        if old_end > 0 and abs(clip_end(m) - old_end) < 0.05 and end > m["start"]:
            m["out"] = round(m["in"] + (end - m["start"]), 3)
    return cur


def _keep_video_edits(new: dict, old: dict) -> None:
    """Re-apply the editor's per-scene changes to a fresh render: the scene
    order (when the same scenes are there), and each unchanged clip's trims,
    level and the transitions of its join. A scene whose clip was remade
    starts fresh."""
    old_v, new_v = track(old, "video")["clips"], track(new, "video")["clips"]
    if not old_v or not all(_linked(c) for c in old_v + new_v):
        return
    old_scenes = [c["scene"] for c in old_v]
    if len(set(old_scenes)) != len(old_scenes):
        return  # a split scene: too ambiguous to carry over
    by_scene = {c["scene"]: c for c in old_v}
    for c in new_v:
        o = by_scene.get(c["scene"])
        if o and o["src"] == c["src"]:
            top = c.get("src_max", c["out"])
            c["in"] = min(o["in"], top - 0.1)
            c["out"] = max(c["in"] + 0.1, min(o["out"], top))
            c["gain"] = o["gain"]
    if sorted(old_scenes) == sorted(c["scene"] for c in new_v):
        new_v.sort(key=lambda c: old_scenes.index(c["scene"]))
        for k, c in enumerate(new_v):
            c["fade_in"] = old_v[k]["fade_in"]


def keep_edits(new: dict, old: dict | str | None) -> dict:
    """Carry the user's own edits from the previous timeline into a freshly
    rendered one: titles, music level and ducking, and per scene its order,
    trims, level and transitions (see _keep_video_edits). Voice lines and
    music follow the scenes."""
    if not old:
        return new
    old, new = normalize(old), normalize(new)
    track(new, "text")["clips"] = track(old, "text")["clips"]
    old_music, new_music = track(old, "music"), track(new, "music")
    new_music["duck"] = old_music.get("duck", True)
    if old_music["clips"] and new_music["clips"]:
        new_music["clips"][0]["gain"] = old_music["clips"][0]["gain"]
    before = copy.deepcopy(new)
    _keep_video_edits(new, old)
    _layout_video(track(new, "video")["clips"])
    return follow_scenes(before, new)


def build_timeline(
    story,
    plan,
    *,
    width: int,
    height: int,
    fps: int = 24,
    clip_lengths: dict[int, float] | None = None,
    voice_uris: dict[int, str] | None = None,
    voice_lengths: dict[int, float] | None = None,
    clip_gains: dict[int, float] | None = None,
    music_uri: str = "",
    music_length: float = 0.0,
) -> dict:
    """The film as a timeline, from a stitch plan and the made media.

    ``plan`` is a ``StitchPlan`` (segment order and crossfades). Every clip
    keeps its own sound at ``clip_gains[index]``: spoken scenes levelled to
    ``DIALOGUE_LUFS``, narrated scenes to ``AMBIENT_LUFS`` as a bed under the
    narrator (see :func:`clip_gain`). Narration starts just after each
    crossfade.
    """
    tl = empty_timeline(width, height, fps)
    vids, voices = track(tl, "video")["clips"], track(tl, "voice")["clips"]
    voice_uris = voice_uris or {}
    for seg in plan.segments:
        i = seg.index
        cin = float(getattr(seg, "trim_head", 0.0))
        src_len = (clip_lengths or {}).get(i, cin + float(seg.duration))
        # The measured clip may be a little shorter than planned.
        length = max(0.1, min(float(seg.duration), src_len - cin))
        default = 1.0 if seg.spoken else AMBIENT_GAIN
        gain = (clip_gains or {}).get(i, default)
        clip = {
            "id": new_clip_id(),
            "src": seg.clip_uri,
            "start": seg.start,
            "in": round(cin, 3),
            "out": round(cin + length, 3),
            "src_max": round(max(src_len, cin + length), 3),
            "gain": round(gain, 3),
            "fade_in": seg.fade_in,
            "label": f"Scene {i + 1}",
            "scene": i,
        }
        if not seg.spoken:
            clip["ambient"] = True
        vids.append(clip)
    _layout_video(vids)
    for seg, vclip in zip(plan.segments, vids, strict=True):
        vuri = voice_uris.get(seg.index, "")
        if not vuri:
            continue
        length = clip_length(vclip)
        vlen = float((voice_lengths or {}).get(seg.index, length))
        begin = min(vclip["fade_in"] + 0.25, length / 3)
        room = max(0.3, length - begin - 0.05)
        voices.append(
            {
                "id": new_clip_id(),
                "src": vuri,
                "start": round(vclip["start"] + begin, 3),
                "in": 0.0,
                "out": round(min(vlen, room), 3),
                "gain": 1.0,
                "tempo": 1.0,
                "scene": seg.index,
            }
        )
    if music_uri:
        total = duration(tl) or plan.total
        length = music_length or total
        track(tl, "music")["clips"].append(
            {
                "id": new_clip_id(),
                "src": music_uri,
                "start": 0.0,
                "in": 0.0,
                # Music shorter than the film loops when rendered.
                "out": round(total, 3),
                "src_max": round(max(total, length), 3),
                "gain": 0.8,
            }
        )
    return normalize(tl)


# ---------------------------------------------------------------------------
# Rendering (ffmpeg)
# ---------------------------------------------------------------------------


def _ffmpeg() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def probe(path: str) -> tuple[float, bool]:
    """(duration seconds, has an audio stream) of a media file."""
    import re

    err = subprocess.run(
        [_ffmpeg(), "-hide_banner", "-i", path], capture_output=True, text=True, check=False
    ).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0
    return secs, bool(re.search(r"Stream #.*Audio:", err))


def measure_lufs(path: str) -> float | None:
    """Integrated loudness of a file's audio, or None (silent or no audio)."""
    import re

    err = subprocess.run(
        [_ffmpeg(), "-hide_banner", "-nostats", "-i", path, "-vn", "-af",
         "ebur128=framelog=quiet", "-f", "null", "-"],
        capture_output=True, text=True, check=False,
    ).stderr
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
    if not m:
        return None
    value = float(m[-1])
    return None if value <= -60 else value


def gain_to(
    lufs: float | None, target: float = DIALOGUE_LUFS, floor: float = 0.25
) -> float:
    """Linear gain that brings `lufs` to `target` (1.0 when unknown)."""
    if lufs is None:
        return 1.0
    return round(min(MAX_GAIN, max(floor, 10 ** ((target - lufs) / 20))), 3)


def clip_gain(lufs: float | None, spoken: bool) -> float:
    """Gain for a clip's own sound: speech levelled to DIALOGUE_LUFS; a
    narrated clip's sound (ambience, effects) kept low at AMBIENT_LUFS so the
    narrator sits on top of it."""
    if spoken:
        return gain_to(lufs, DIALOGUE_LUFS)
    if lufs is None:
        return AMBIENT_GAIN
    return gain_to(lufs, AMBIENT_LUFS, floor=0.01)


def _atempo(tempo: float) -> str:
    stages = []
    while tempo > 2.0:
        stages.append(2.0)
        tempo /= 2.0
    while tempo < 0.5:
        stages.append(0.5)
        tempo /= 0.5
    stages.append(tempo)
    return ",".join(f"atempo={t:.4f}" for t in stages)


def render_args(
    timeline: dict,
    paths: dict[str, str],
    has_audio: dict[str, bool],
    overlays: dict[str, str],
    out_path: str,
    preset: str = "veryfast",
) -> list[str]:
    """ffmpeg argv that renders `timeline` (already normalized).

    ``paths`` maps each clip src to a local file, ``has_audio`` says which
    files have sound, ``overlays`` maps text clip ids to full-frame RGBA PNGs.
    """
    w, h, fps = timeline["width"], timeline["height"], timeline["fps"]
    total = max(0.1, duration(timeline))
    args = [_ffmpeg(), "-v", "error", "-y"]
    filters: list[str] = []
    n = 0

    def add_input(path: str, *pre: str) -> int:
        nonlocal n
        args.extend([*pre, "-i", path])
        n += 1
        return n - 1

    # Video: black canvas, each clip overlaid at its start (fades = crossfades).
    filters.append(f"color=c=black:s={w}x{h}:r={fps}:d={total:.3f}[base]")
    last = "base"
    dialogue: list[str] = []
    # Narrated clips' own sound: a bed under the voice, mixed after the
    # ducking so it neither ducks the music nor is ducked.
    beds: list[str] = []
    for k, c in enumerate(track(timeline, "video")["clips"]):
        idx = add_input(paths[c["src"]])
        length = clip_length(c)
        chain = (
            f"[{idx}:v]trim=start={c['in']:.3f}:end={c['out']:.3f},setpts=PTS-STARTPTS,"
            f"fps={fps},scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuva420p"
        )
        if c.get("fade_in"):
            chain += f",fade=t=in:st=0:d={c['fade_in']:.3f}:alpha=1"
        chain += f",setpts=PTS+{c['start']:.3f}/TB[v{k}]"
        filters.append(chain)
        filters.append(
            f"[{last}][v{k}]overlay=eof_action=pass:enable='between(t,{c['start']:.3f},"
            f"{c['start'] + length:.3f})'[o{k}]"
        )
        last = f"o{k}"
        if c.get("gain", 0) > 0 and has_audio.get(c["src"]):
            bucket = beds if c.get("ambient") else dialogue
            bucket.append(_audio_chain(filters, idx, c, length, f"d{k}"))
    for k, c in enumerate(track(timeline, "text")["clips"]):
        png = overlays.get(c["id"])
        if not png:
            continue
        idx = add_input(png, "-loop", "1", "-t", f"{total:.3f}")
        end = min(total, c["start"] + c["dur"])
        filters.append(
            f"[{last}][{idx}:v]overlay=0:0:enable='between(t,{c['start']:.3f},{end:.3f})'[t{k}]"
        )
        last = f"t{k}"
    filters.append(f"[{last}]format=yuv420p[vout]")

    for k, c in enumerate(track(timeline, "voice")["clips"]):
        if not has_audio.get(c["src"], True):
            continue
        idx = add_input(paths[c["src"]])
        dialogue.append(_audio_chain(filters, idx, c, clip_length(c), f"s{k}"))

    music_track = track(timeline, "music")
    music: list[str] = []
    for k, c in enumerate(music_track["clips"]):
        if not has_audio.get(c["src"], True):
            continue
        idx = add_input(paths[c["src"]], "-stream_loop", "-1")
        music.append(_audio_chain(filters, idx, c, clip_length(c), f"m{k}", fade=1.0))

    audio_out = ""
    if dialogue or music or beds:
        dlg = ""
        if dialogue:
            dlg = "dlg"
            filters.append(
                "".join(f"[{d}]" for d in dialogue)
                + f"amix=inputs={len(dialogue)}:normalize=0:duration=longest[{dlg}]"
            )
        mus = ""
        if music:
            mus = "mus"
            filters.append(
                "".join(f"[{m}]" for m in music)
                + f"amix=inputs={len(music)}:normalize=0:duration=longest[{mus}]"
            )
        if dlg and mus and music_track.get("duck", True):
            # Music dips under speech and comes back up between lines.
            filters.append(f"[{dlg}]asplit=2[dlg1][dlg2]")
            filters.append(
                f"[{mus}][dlg2]sidechaincompress=threshold=0.02:ratio=8:attack=20:"
                "release=450:makeup=1[mducked]"
            )
            parts = ["dlg1", "mducked"]
        else:
            parts = [p for p in (dlg, mus) if p]
        parts += beds
        mix = parts[0]
        if len(parts) > 1:
            filters.append(
                "".join(f"[{p}]" for p in parts)
                + f"amix=inputs={len(parts)}:normalize=0:duration=longest[mix]"
            )
            mix = "mix"
        filters.append(
            f"[{mix}]apad,atrim=0:{total:.3f},"
            f"loudnorm=I={MASTER_LUFS}:TP=-1.5:LRA=11,aresample=48000[aout]"
        )
        audio_out = "aout"

    args += ["-filter_complex", ";".join(filters), "-map", "[vout]"]
    if audio_out:
        args += ["-map", f"[{audio_out}]", "-c:a", "aac", "-b:a", "192k"]
    args += [
        "-c:v", "libx264", "-preset", preset, "-crf", "20", "-pix_fmt", "yuv420p",
        "-r", str(fps), "-t", f"{total:.3f}", "-movflags", "+faststart", out_path,
    ]
    return args


def _audio_chain(
    filters: list[str], idx: int, c: dict, length: float, label: str, fade: float = EDGE_FADE
) -> str:
    tempo = float(c.get("tempo") or 1.0)
    chain = f"[{idx}:a]atrim=start={c['in']:.3f}:end={c['out']:.3f},asetpts=PTS-STARTPTS"
    if abs(tempo - 1.0) > 0.005:
        chain += "," + _atempo(tempo)
    f = min(fade, length / 3)
    chain += (
        f",aformat=sample_rates=48000:channel_layouts=stereo,volume={c.get('gain', 1.0):.3f},"
        f"afade=t=in:st=0:d={f:.3f},afade=t=out:st={max(0.0, length - f):.3f}:d={f:.3f},"
        f"adelay={int(round(c['start'] * 1000))}:all=1[{label}]"
    )
    filters.append(chain)
    return label


def text_overlay_png(clip: dict, width: int, height: int, out_path: str) -> str:
    """A full-frame transparent PNG with the clip's text (shadowed, wrapped)."""
    from PIL import Image, ImageDraw, ImageFont

    size = max(10, int(clip.get("size", 48) * height / 720))
    try:
        font = ImageFont.load_default(size=size)
    except TypeError:  # older Pillow
        font = ImageFont.load_default()
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    words, lines, line = clip["text"].split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) > width * 0.86 and line:
            lines.append(line)
            line = word
        else:
            line = trial
    lines.append(line)
    gap = int(size * 1.25)
    block = gap * len(lines)
    y = {"top": int(height * 0.08), "center": (height - block) // 2}.get(
        clip.get("pos"), height - block - int(height * 0.08)
    )
    for ln in lines:
        tw = draw.textlength(ln, font=font)
        x = (width - tw) / 2
        pad = max(2, size // 16)
        draw.text((x + pad, y + pad), ln, font=font, fill=(0, 0, 0, 170))
        draw.text((x, y), ln, font=font, fill=(255, 255, 255, 255))
        y += gap
    img.save(out_path, "PNG")
    return out_path


def render_timeline(
    timeline: dict, fetch, out_path: str, preset: str = "veryfast"
) -> str:
    """Render a timeline to MP4. ``fetch(uri, local_path)`` copies a source
    file to disk (GCS download, or a local copy in demo mode)."""
    from common.error_handling import GenerationError

    tl = normalize(timeline)
    if not track(tl, "video")["clips"]:
        raise GenerationError("The timeline has no video clips.")
    with tempfile.TemporaryDirectory() as tmp:
        paths: dict[str, str] = {}
        has_audio: dict[str, bool] = {}
        for t in tl["tracks"]:
            for c in t["clips"]:
                src = c.get("src")
                if not src or src in paths:
                    continue
                ext = os.path.splitext(src.split("?")[0])[1][:6] or ".bin"
                local = os.path.join(tmp, f"src{len(paths)}{ext}")
                fetch(src, local)
                paths[src] = local
                has_audio[src] = probe(local)[1]
        overlays = {
            c["id"]: text_overlay_png(
                c, tl["width"], tl["height"], os.path.join(tmp, f"text_{c['id']}.png")
            )
            for c in track(tl, "text")["clips"]
        }
        args = render_args(tl, paths, has_audio, overlays, out_path, preset)
        result = subprocess.run(args, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            from common.analytics import get_logger

            get_logger(__name__).error("ffmpeg render failed: %s", result.stderr[-2000:])
            raise GenerationError("Rendering the film failed. Retry export.")
    return out_path


def copy_timeline(timeline: dict) -> dict:
    return copy.deepcopy(timeline)
