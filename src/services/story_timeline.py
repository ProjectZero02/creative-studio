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
       {"id": "text",  "kind": "text",  "clips": [{"id", "text", "start", "dur", "pos", "size",
                                                    "style", "sub"}]}]}

A text clip with ``"sub": true`` is a subtitle (see services/story_subtitles.py);
``style`` is "clean", "boxed" or "bold".

Times are seconds. A clip plays its source from ``in`` to ``out`` at
``start`` on the film. Video clips also carry the clip's own sound (speech,
ambience) at ``gain``; ``ambient: true`` marks a narrated clip whose sound is
a bed under the voice (it neither ducks the music nor is ducked). The video track is sequential: ``normalize`` lays its
clips end to end, overlapping by ``fade_in`` (a crossfade).

Everything above ``render_timeline`` is pure and unit tested.
"""

from __future__ import annotations

import contextvars
import copy
import json
import os
import re
import subprocess
import tempfile
import threading
import time
import uuid

# The running job's cancel event (set by story_jobs for its threads): a long
# ffmpeg run stops when the user cancels.
CANCEL: contextvars.ContextVar[threading.Event | None] = contextvars.ContextVar(
    "story_cancel", default=None
)


class Cancelled(Exception):
    """The user cancelled the job while ffmpeg was running."""


def run_ffmpeg(args: list[str], **kw) -> subprocess.CompletedProcess:
    """subprocess.run for ffmpeg that stops it when the job is cancelled:
    "q" on stdin first (ffmpeg's own clean stop), then terminate, then kill.
    Raises Cancelled after stopping it. Never uses a shell."""
    cancel = CANCEL.get()
    if cancel is None:
        return subprocess.run(args, capture_output=True, text=True, check=False, **kw)
    if cancel.is_set():
        raise Cancelled()
    proc = subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **kw,
    )
    box: dict = {"out": [], "err": []}
    readers = [
        threading.Thread(
            target=lambda s=stream, k=k: box[k].append(s.read()), daemon=True
        )
        for k, stream in (("out", proc.stdout), ("err", proc.stderr))
    ]
    for r in readers:
        r.start()
    while proc.poll() is None:
        time.sleep(0.25)
        if cancel.is_set() and proc.poll() is None:
            try:
                proc.stdin.write("q")
                proc.stdin.flush()
            except (OSError, ValueError):
                pass
            deadline = time.time() + 2
            while proc.poll() is None and time.time() < deadline:
                time.sleep(0.05)
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(3)
                except subprocess.TimeoutExpired:
                    proc.kill()
            raise Cancelled()
    for r in readers:
        r.join(5)
    try:
        proc.stdin.close()
    except OSError:
        pass
    return subprocess.CompletedProcess(
        args, proc.returncode, "".join(box["out"]), "".join(box["err"])
    )

TRACK_KINDS = ("video", "voice", "music", "text")
JOIN_TYPES = ("cut", "bridge", "extend", "dissolve", "fade_black")
TEXT_POSITIONS = ("top", "center", "bottom")
TEXT_STYLES = ("clean", "boxed", "bold")
# Fonts tried in order for on-film text: Noto covers Arabic and most scripts
# (fonts-noto-core in the container); Arial Unicode / Segoe UI on Windows.
# Fonts per script. Noto Sans Arabic has no Latin letters (English drew as
# boxes with it), so each caption line gets a font for its own script: Latin
# for most lines, Arabic for right-to-left ones. The Windows fonts at the end
# cover both, for local runs.
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/ARIALUNI.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
)
BOLD_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
)
RTL_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/ARIALUNI.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
)
RTL_BOLD_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
)
_RTL = re.compile("[\u0590-\u08ff\ufb1d-\ufdff\ufe70-\ufefc]")
MAX_GAIN = 4.0
# Spoken clips are already near dialogue level; pushing them harder only
# drives the master limiter and flattens the voice.
SPOKEN_GAIN_MAX = 1.15
# Loudness targets (LUFS): each clip's dialogue, the model's own sound under
# a narrator (an ambient bed), and the finished film.
DIALOGUE_LUFS = -20.0
AMBIENT_LUFS = -30.0
# Gain for a narrated clip whose loudness could not be measured.
AMBIENT_GAIN = 0.25
MASTER_LUFS = -14.0
# Short fade on every audio cut so joins never click.
EDGE_FADE = 0.04
# A little longer on a clip's own sound, so a level change at a cut is
# eased rather than a jump.
JOIN_FADE = 0.08
# Silence (seconds) added after the music before ducking it; see render_args.
DUCK_PAD = 2.0
# The film's ending: the music that runs to the end fades over MUSIC_OUTRO
# seconds, the last clip's own sound over END_SOUND_FADE. When speech still
# runs within END_SPEECH_GAP of the end, the last frame is held END_HOLD
# seconds and fades to black, so the film never stops on the last word.
MUSIC_OUTRO = 3.0
END_SOUND_FADE = 0.5
END_SPEECH_GAP = 0.8
END_HOLD = 1.0
# A 50 ms slice louder than this (dBFS) counts as speech.
SPEECH_DB = -35.0
# Frozen picture at a clip's start or end (models often hold the first or
# last frame): shorter holds are left, longer ones trimmed up to the cap,
# and a clip always keeps at least MIN_KEEP seconds.
STILL_MIN = 0.25
STILL_CAP = 1.0
MIN_KEEP = 2.0
FREEZE_NOISE = "-60dB"
SILENCE_NOISE = "-35dB"


def new_clip_id() -> str:
    return uuid.uuid4().hex[:8]


def empty_timeline(width: int = 1280, height: int = 720, fps: int = 24) -> dict:
    return {
        "version": 1,
        "fps": fps,
        "width": width,
        "height": height,
        "color_match": True,
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


def merge_runs(clips: list[dict], fps: int = 24) -> list[dict]:
    """Back-to-back pieces of one file (a continuous take cut into scenes)
    as single clips: same source, the next piece starts where the last one
    ended (in the file and on the timeline, within a frame), and no fade.
    Rendered as one piece, the picture and its sound run straight through
    the join instead of being cut and faded there."""
    tol = 1.5 / max(1, fps)
    out: list[dict] = []
    for c in clips:
        prev = out[-1] if out else None
        if (
            prev is not None
            and c.get("src") == prev.get("src")
            and not c.get("fade_in")
            and abs(float(c.get("tempo") or 1.0) - 1.0) < 1e-6
            and abs(float(prev.get("tempo") or 1.0) - 1.0) < 1e-6
            and bool(c.get("ambient")) == bool(prev.get("ambient"))
            and abs(float(c.get("gain", 1.0)) - float(prev.get("gain", 1.0))) < 1e-6
            and abs(float(c["in"]) - float(prev["out"])) <= tol
            and abs(float(c["start"]) - clip_end(prev)) <= tol
        ):
            out[-1] = {
                **prev,
                "out": c["out"],
                "src_max": max(float(prev.get("src_max", prev["out"])), float(c.get("src_max", c["out"]))),
            }
            continue
        out.append(dict(c))
    return out


def trim_to(timeline: dict, seconds: float) -> dict:
    """Cut every clip at `seconds`: clips that start after it go, clips that
    run past it end there (a one-take film lands on the asked length)."""
    end = float(seconds)
    if end <= 0:
        return timeline
    for t in timeline.get("tracks", []):
        kept = []
        for c in t.get("clips", []):
            start = float(c.get("start") or 0)
            if start >= end - 1e-6:
                continue
            if clip_end(c) > end + 1e-6:
                if "dur" in c and "out" not in c:
                    c["dur"] = round(end - start, 3)
                else:
                    tempo = float(c.get("tempo") or 1.0) or 1.0
                    c["out"] = round(float(c.get("in") or 0) + (end - start) * tempo, 3)
            kept.append(c)
        t["clips"] = kept
    return timeline


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


def normalize(timeline: dict | str | None, keep_rev: bool = False) -> dict:
    """Validate and tidy a timeline from the editor (never trust the browser).

    Unknown tracks and fields are dropped, numbers are clamped, clips without
    a source are removed, and the video track is laid end to end.
    ``keep_rev`` keeps the editor's revision tag ``rev``; every other caller
    drops it, so a timeline the server made never looks like the editor's
    own echo. ``removed`` lists the scene clips the user deleted, so a
    re-render does not bring them back (see :func:`keep_edits`).
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
    out["color_match"] = bool(src.get("color_match", True))
    if keep_rev and src.get("rev"):
        out["rev"] = str(src["rev"])[:40]
    removed: list[dict] = []
    for r in src.get("removed") or []:
        if isinstance(r, dict) and r.get("src"):
            item = {"scene": int(_num(r.get("scene"), -1, -1, 999)), "src": str(r["src"])}
            if item["scene"] >= 0 and item not in removed:
                removed.append(item)
    if removed:
        out["removed"] = removed[:200]
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
        clean = {
            "id": cid,
            "text": text,
            "start": start,
            "dur": round(_num(c.get("dur"), 3, 0.2, 3600), 3),
            "pos": pos,
            "size": int(_num(c.get("size"), 48, 12, 200)),
        }
        if c.get("style") in TEXT_STYLES:
            clean["style"] = c["style"]
        if c.get("sub"):
            clean["sub"] = True
        return clean
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
        join = str(c.get("join") or "").strip().lower()
        if join not in JOIN_TYPES:
            join = "dissolve" if clean["fade_in"] > 0 else "cut"
        clean["join"] = join
        clean["label"] = str(c.get("label") or "")[:60]
        clean["scene"] = int(_num(c.get("scene"), -1, -1, 999))
        if c.get("level") is not None:
            # The clip's own sound as first levelled: the editor's "100%".
            clean["level"] = round(_num(c.get("level"), 1.0, 0.01, MAX_GAIN), 3)
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
    track(cur, "voice")["clips"] = no_overlap(keep)
    old_end, end = duration(prev), duration(cur)
    for m in track(cur, "music")["clips"]:
        if old_end > 0 and abs(clip_end(m) - old_end) < 0.05 and end > m["start"]:
            m["out"] = round(m["in"] + (end - m["start"]), 3)
    return cur


VOICE_GAP = 0.05
MIN_LEN = 0.3  # the editor's shortest clip
# Narrator lines: each starts VOICE_LEAD into its scene and should end
# VOICE_BREATH before the next scene. Every line of a film plays at one
# speed, sped up by at most MAX_FILM_TEMPO when some line is too long. A
# line still too long may run VOICE_SPILL into a next scene that has no
# line of its own, and is otherwise ended at its last pause (never
# mid-word), fading out over VOICE_CUT_FADE.
VOICE_LEAD = 0.25
VOICE_BREATH = 0.5
MAX_FILM_TEMPO = 1.08
VOICE_SPILL = 0.5
VOICE_CUT_FADE = 0.12
# A voice slice quieter than this (dBFS) is silence; a run of at least
# VOICE_PAUSE seconds of it inside a line is a pause between words.
VOICE_SILENCE_DB = -40.0
VOICE_PAUSE = 0.15


def voice_shape(path: str) -> dict:
    """A narrator line's shape: {"length", "lead" (silence before the first
    word), "end" (where the last word stops), "pauses" (middle of each pause
    inside the line)}, all in seconds of the file."""
    window = 0.02
    levels = audio_levels(path, window)
    length = len(levels) * window
    loud = [i for i, v in enumerate(levels) if v > VOICE_SILENCE_DB]
    if not loud:
        return {"length": round(length, 3), "lead": 0.0, "end": round(length, 3), "pauses": []}
    pauses, run = [], 0
    for i in range(loud[0], loud[-1] + 1):
        if levels[i] <= VOICE_SILENCE_DB:
            run += 1
            continue
        if run * window >= VOICE_PAUSE:
            pauses.append(round((i - run / 2) * window, 3))
        run = 0
    return {
        "length": round(length, 3),
        "lead": round(loud[0] * window, 3),
        "end": round((loud[-1] + 1) * window, 3),
        "pauses": pauses,
    }


def film_tempo(needs: list[tuple[float, float]]) -> float:
    """One speed for every narrator line of a film: 1.0 when every line's
    speech (seconds) fits its room, else just enough for the longest, up
    to MAX_FILM_TEMPO."""
    worst = max([need / room for need, room in needs if room > 0] or [1.0])
    return round(min(MAX_FILM_TEMPO, max(1.0, worst)), 4)


def _place_voices(vids, segs, voices, voice_uris, voice_lengths, voice_info) -> None:
    """Lay the narrator lines under their scenes (see VOICE_LEAD and the
    constants after it): the leading silence trimmed, one speed for the
    film, a breath before the next scene, never cut mid-word."""
    voice_uris = voice_uris or {}
    plan: list[dict] = []
    for k, (seg, vclip) in enumerate(zip(segs, vids, strict=True)):
        vuri = voice_uris.get(seg.index, "")
        if not vuri:
            continue
        length = clip_length(vclip)
        vlen = float((voice_lengths or {}).get(seg.index, length))
        shape = (voice_info or {}).get(seg.index) or {}
        lead = min(float(shape.get("lead", 0.0)), max(0.0, vlen - 0.1))
        cin = round(max(0.0, lead - 0.05), 3)
        end = min(vlen, float(shape.get("end", vlen)) + 0.1)
        need = max(0.1, end - cin)
        begin = min(vclip["fade_in"] + VOICE_LEAD, length / 3)
        room = max(0.3, length - begin - VOICE_BREATH)
        if need > room:
            # A clip with spare picture after it grows to fit the line.
            next_seg = segs[k + 1] if k + 1 < len(segs) else None
            src_max = float(vclip.get("src_max", vclip["out"]))
            next_seamless = next_seg is not None and getattr(next_seg, "join", "") in (
                "bridge",
                "extend",
            )
            if src_max > vclip["out"] and not next_seamless:
                vclip["out"] = round(min(src_max, vclip["out"] + (need - room)), 3)
                _layout_video(vids)
                length = clip_length(vclip)
                begin = min(vclip["fade_in"] + VOICE_LEAD, length / 3)
                room = max(0.3, length - begin - VOICE_BREATH)
        plan.append(
            {
                "k": k,
                "seg": seg,
                "vuri": vuri,
                "cin": cin,
                "need": need,
                "room": room,
                "begin": begin,
                "shape": shape,
            }
        )
    tempo = film_tempo([(p["need"], p["room"]) for p in plan])
    voiced = {p["k"] for p in plan}
    for p in plan:
        k, vclip = p["k"], vids[p["k"]]
        start = vclip["start"] + p["begin"]
        nxt = vids[k + 1] if k + 1 < len(vids) else None
        if nxt is None:
            limit = clip_end(vclip)
        elif k + 1 in voiced:
            nbegin = min(nxt["fade_in"] + VOICE_LEAD, clip_length(nxt) / 3)
            limit = nxt["start"] + nbegin - VOICE_GAP
        else:
            limit = min(clip_end(vclip) + VOICE_SPILL, clip_end(nxt))
        out = p["cin"] + p["need"]
        cut = False
        if start + p["need"] / tempo > limit:
            # Too long even so: end at the last pause that fits.
            latest = p["cin"] + (limit - start) * tempo
            gaps = [t for t in p["shape"].get("pauses", []) if p["cin"] < t <= latest]
            out = gaps[-1] if gaps else latest
            cut = True
        line = {
            "id": new_clip_id(),
            "src": p["vuri"],
            "start": round(start, 3),
            "in": p["cin"],
            "out": round(max(p["cin"] + 0.1, out), 3),
            "gain": 1.0,
            "tempo": tempo,
            "scene": p["seg"].index,
        }
        if cut:
            line["cut"] = True
        voices.append(line)


def no_overlap(lines: list[dict]) -> list[dict]:
    """Voice lines in time order, each ending before the next one starts:
    a line that would run into the next is cut short there, and dropped when
    less than MIN_LEN of it is left (two narrators never talk at once). The
    same rule as the editor's `_noOverlap` (story_timeline.js)."""
    out: list[dict] = []
    # From the last line back, so each line yields to the next one kept.
    for line in sorted(lines, key=lambda c: float(c["start"]), reverse=True):
        nxt = out[0] if out else None
        if nxt is not None and clip_end(line) > float(nxt["start"]) - VOICE_GAP + 1e-6:
            room = float(nxt["start"]) - VOICE_GAP - float(line["start"])
            if room < MIN_LEN:
                continue
            tempo = float(line.get("tempo") or 1.0) or 1.0
            line["out"] = round(float(line["in"]) + room * tempo, 3)
        out.insert(0, line)
    return out


def _scene_groups(clips: list[dict]) -> dict[int, list[dict]]:
    groups: dict[int, list[dict]] = {}
    for c in clips:
        groups.setdefault(int(c.get("scene", -1)), []).append(c)
    return groups


def _keep_video_edits(new: dict, old: dict) -> set[int]:
    """Re-apply the editor's per-scene changes to a fresh render. A scene is
    kept as the user left it (its pieces after splits, their order, trims,
    levels and transitions) when its clip is the same file in both; a scene
    whose clip was remade starts fresh, where its old pieces were. Scenes the
    user deleted stay deleted while their clip is unchanged. Returns the
    scenes that were kept."""
    old_v, new_v = track(old, "video")["clips"], track(new, "video")["clips"]
    if not old_v or not all(_linked(c) for c in old_v + new_v):
        return set()
    removed = {(r["scene"], r["src"]) for r in old.get("removed", [])}
    new_by = _scene_groups(new_v)
    old_by = _scene_groups(old_v)
    kept: set[int] = set()
    for scene, olds in old_by.items():
        fresh = new_by.get(scene)
        if fresh and all(o["src"] == fresh[0]["src"] for o in olds):
            kept.add(scene)
    out: list[dict] = []
    placed: set[int] = set()
    for o in old_v:
        scene = o["scene"]
        if scene in kept:
            top = float(new_by[scene][0].get("src_max", new_by[scene][0]["out"]))
            c = dict(o)
            c["src_max"] = max(top, 0.1)
            c["in"] = min(float(o["in"]), top - 0.1)
            c["out"] = max(c["in"] + 0.1, min(float(o["out"]), top))
            out.append(c)
        elif scene not in placed and scene in new_by:
            out.extend(new_by[scene])
        placed.add(scene)
    # Scenes the old timeline did not have: in story order, unless the user
    # deleted that very clip.
    for scene in sorted(s for s in new_by if s not in placed):
        fresh = [c for c in new_by[scene] if (scene, c["src"]) not in removed]
        if not fresh:
            continue
        at = 0
        for k, c in enumerate(out):
            if c["scene"] < scene:
                at = k + 1
        out[at:at] = fresh
    new_v[:] = out
    still = [
        r
        for r in old.get("removed", [])
        if any(c["src"] == r["src"] for c in new_by.get(r["scene"], []))
    ]
    if still:
        new["removed"] = still
    else:
        new.pop("removed", None)
    return kept


def _map_lines(lines: list[dict], prev: dict, cur: dict) -> list[dict]:
    """Voice lines placed on `prev`'s video track, moved onto `cur`'s."""
    if not lines:
        return []
    tmp = {"tracks": [{"kind": "video", "clips": track(cur, "video")["clips"]},
                      {"kind": "voice", "clips": copy.deepcopy(lines)}]}
    follow_scenes(prev, tmp)
    return track(tmp, "voice")["clips"]


def keep_edits(new: dict, old: dict | str | None) -> dict:
    """Carry the user's own edits from the previous timeline into a freshly
    rendered one: titles; per scene its pieces, order, trims, levels and
    transitions, and deleted scenes (see _keep_video_edits); voice lines of
    unchanged scenes with their level and place; the music clips when the
    music file is the same, else the music level; ducking. A scene whose
    clip or voice was remade starts fresh."""
    if not old:
        return new
    old, new = normalize(old), normalize(new)
    track(new, "text")["clips"] = track(old, "text")["clips"]
    before = copy.deepcopy(new)
    kept = _keep_video_edits(new, old)
    _layout_video(track(new, "video")["clips"])
    # Voice: an unchanged line keeps its level and place on its scene.
    old_lines = {(c.get("scene", -1), c["src"]): c for c in track(old, "voice")["clips"]}
    carried, fresh = [], []
    for line in track(before, "voice")["clips"]:
        o = old_lines.get((line.get("scene", -1), line["src"]))
        if o is not None and line.get("scene", -1) in kept:
            carried.append(copy.deepcopy(o))
        else:
            fresh.append(line)
    track(new, "voice")["clips"] = no_overlap(
        _map_lines(carried, old, new) + _map_lines(fresh, before, new)
    )
    # Music: the same file keeps its trims; a new file keeps the level.
    old_music, new_music = track(old, "music"), track(new, "music")
    new_music["duck"] = old_music.get("duck", True)
    if old_music["clips"] and new_music["clips"]:
        if {c["src"] for c in old_music["clips"]} == {c["src"] for c in new_music["clips"]}:
            tmp = {"tracks": [{"kind": "video", "clips": track(new, "video")["clips"]},
                              {"kind": "music", "clips": copy.deepcopy(old_music["clips"])}]}
            follow_scenes(old, tmp)
            new_music["clips"] = track(tmp, "music")["clips"]
        else:
            new_music["clips"][0]["gain"] = old_music["clips"][0]["gain"]
    return normalize(new)


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
    clip_stills: dict[int, tuple[float, float]] | None = None,
    music_uri: str = "",
    music_length: float = 0.0,
    voice_info: dict[int, dict] | None = None,
) -> dict:
    """The film as a timeline, from a stitch plan and the made media.

    ``plan`` is a ``StitchPlan`` (segment order and crossfades). Every clip
    keeps its own sound at ``clip_gains[index]``: spoken scenes levelled to
    ``DIALOGUE_LUFS``, narrated scenes to ``AMBIENT_LUFS`` as a bed under the
    narrator (see :func:`clip_gain`). Narration starts just after each
    crossfade. ``clip_stills[index]`` is the frozen (head, tail) of a clip
    (see :func:`clip_edges`), trimmed off so cuts land on movement.
    ``voice_info[index]`` is a narrator line's shape (see
    :func:`voice_shape`), used to fit it (see :func:`_place_voices`).
    """
    tl = empty_timeline(width, height, fps)
    tl["color_match"] = bool(getattr(story, "color_match", True))
    vids, voices = track(tl, "video")["clips"], track(tl, "voice")["clips"]
    voice_uris = voice_uris or {}
    segs = list(plan.segments)
    for k, seg in enumerate(segs):
        i = seg.index
        next_seg = segs[k + 1] if k + 1 < len(segs) else None
        cin = float(getattr(seg, "trim_head", 0.0))
        src_len = (clip_lengths or {}).get(i, cin + float(seg.duration))
        head, tail = (clip_stills or {}).get(i, (0.0, 0.0))
        entering_seamless = (
            getattr(seg, "join", "") in ("bridge", "extend")
            or float(getattr(seg, "trim_head", 0.0)) > 0
        )
        exiting_seamless = (
            next_seg is not None
            and getattr(next_seg, "join", "") in ("bridge", "extend")
        )
        if entering_seamless:
            head = 0.0
        if exiting_seamless:
            tail = 0.0
        cin = max(cin, min(head, src_len - MIN_KEEP))
        usable = max(cin + 0.1, src_len - tail)
        # The measured clip may be a little shorter than planned.
        length = max(0.1, min(float(seg.duration), usable - cin))
        default = 1.0 if seg.spoken else AMBIENT_GAIN
        gain = (clip_gains or {}).get(i, default)
        join = str(getattr(seg, "join", "cut") or "cut")
        if join not in JOIN_TYPES:
            join = "dissolve" if seg.fade_in > 0 else "cut"
        clip = {
            "id": new_clip_id(),
            "src": seg.clip_uri,
            "start": seg.start,
            "in": round(cin, 3),
            "out": round(cin + length, 3),
            "src_max": round(max(src_len, cin + length), 3),
            "gain": round(gain, 3),
            "level": round(gain, 3),
            "fade_in": seg.fade_in,
            "join": join,
            "label": f"Scene {i + 1}",
            "scene": i,
        }
        if not seg.spoken:
            clip["ambient"] = True
        vids.append(clip)
    _layout_video(vids)
    _place_voices(vids, segs, voices, voice_uris, voice_lengths, voice_info)
    asked = float(getattr(story, "target_seconds", 0) or 0)
    if getattr(story, "one_take", False) and 0 < asked < duration(tl):
        trim_to(tl, asked)
    tracks = getattr(story, "music_tracks", None)
    if music_uri or (callable(tracks) and any(t.get("uri") for t in tracks())):
        place_music(
            tl,
            story,
            music_uri,
            main_length=music_length,
            total=duration(tl) or plan.total,
        )
    return normalize(tl)


# Music clips overlap by this much where one track hands over to another
# (each music clip fades in and out over 1 s when rendered).
MUSIC_OVERLAP = 1.0


def take_spans(tl: dict, story) -> list[tuple[float, float] | None]:
    """(start, end) of each take on the timeline, or None for a take with
    no clip placed."""
    from services.story_models import take_groups

    groups = take_groups(story)
    take_of = {i: k for k, g in enumerate(groups) for i in g}
    spans: dict[int, tuple[float, float]] = {}
    for c in track(tl, "video")["clips"]:
        k = take_of.get(int(c.get("scene", -1)))
        if k is None:
            continue
        a = float(c.get("start", 0.0))
        b = a + clip_length(c)
        lo, hi = spans.get(k, (a, b))
        spans[k] = (min(lo, a), max(hi, b))
    return [spans.get(k) for k in range(len(groups))]


def place_music(
    tl: dict,
    story,
    main_uri: str,
    *,
    gain: float = 0.8,
    main_length: float = 0.0,
    total: float = 0.0,
) -> dict:
    """Lay the music track out: each music track under its takes, and the
    film's own music (`main_uri`) wherever no track plays, picking up where
    it would be had it played all along. Neighbours overlap by MUSIC_OVERLAP
    so their fades cross. Replaces the music track's clips."""
    total = total or duration(tl)
    tracks_of = getattr(story, "music_tracks", None)
    tracks = [t for t in (tracks_of() if callable(tracks_of) else []) if t.get("uri")]
    half = MUSIC_OVERLAP / 2
    clips: list[dict] = []
    covered: list[tuple[float, float]] = []
    spans = take_spans(tl, story) if tracks else []
    for t in tracks:
        ranges = [
            spans[int(k)]
            for k in t.get("takes") or []
            if 0 <= int(k) < len(spans) and spans[int(k)]
        ]
        if not ranges:
            continue
        a, b = min(r[0] for r in ranges), max(r[1] for r in ranges)
        covered.append((a, b))
        start, end = max(0.0, a - half), min(total, b + half)
        clips.append(
            {
                "id": new_clip_id(),
                "src": t["uri"],
                "start": round(start, 3),
                "in": 0.0,
                "out": round(end - start, 3),
                "src_max": round(end - start, 3),
                "gain": gain,
            }
        )
    if main_uri:
        gaps, at = [], 0.0
        for a, b in sorted(covered):
            if a > at:
                gaps.append((at, a))
            at = max(at, b)
        if at < total:
            gaps.append((at, total))
        for a, b in gaps:
            if b - a < half:
                continue
            start = max(0.0, a - (half if a > 0 else 0.0))
            end = min(total, b + (half if b < total else 0.0))
            clips.append(
                {
                    "id": new_clip_id(),
                    "src": main_uri,
                    "start": round(start, 3),
                    # As if it had played from the start of the film. Music
                    # shorter than the film loops when rendered.
                    "in": round(start, 3),
                    "out": round(end, 3),
                    "src_max": round(max(total, main_length or total), 3),
                    "gain": gain,
                }
            )
    clips.sort(key=lambda c: c["start"])
    track(tl, "music")["clips"] = clips
    return tl


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


def _spans(err: str, key: str, length: float) -> list[tuple[float, float]]:
    """(start, end) spans from freezedetect / silencedetect log lines; a span
    still open at the end of the file ends at ``length``."""
    import re

    marks = re.findall(rf"{key}_(start|end): (-?[\d.]+)", err)
    spans, begin = [], None
    for kind, value in marks:
        if kind == "start":
            begin = float(value)
        elif begin is not None:
            spans.append((begin, float(value)))
            begin = None
    if begin is not None:
        spans.append((begin, length))
    return spans


def _edges(spans: list[tuple[float, float]], length: float) -> tuple[float, float]:
    # Back-to-back spans (the detector restarts after a keyframe) are one hold.
    merged: list[list[float]] = []
    for s, e in sorted(spans):
        if merged and s - merged[-1][1] <= 0.1:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    spans = [(s, e) for s, e in merged]
    head = next((e for s, e in spans if s <= 0.05), 0.0)
    tail = next((length - s for s, e in spans if e >= length - 0.05), 0.0)
    return max(0.0, head), max(0.0, tail)


def clip_edges(path: str, spoken: bool = False) -> tuple[float, float, float]:
    """(picture length, still head, still tail) of a video clip, in seconds.

    The length is the video stream's own (the file can run longer when its
    sound does, which left black frames at the cuts). The still head and tail
    are frozen picture at either end, worth trimming; for a spoken clip only
    where it is also silent, so no line is cut. (0, 0, 0) when unreadable.
    """
    import re

    cmd = [
        _ffmpeg(),
        "-hide_banner",
        "-i",
        path,
        "-map",
        "0:v:0",
        "-vf",
        f"freezedetect=n={FREEZE_NOISE}:d={STILL_MIN}",
    ]
    if spoken:
        cmd += [
            "-map",
            "0:a:0",
            "-af",
            f"silencedetect=n={SILENCE_NOISE}:d={STILL_MIN}",
        ]
    err = subprocess.run(
        [*cmd, "-f", "null", "-"], capture_output=True, text=True, check=False
    ).stderr
    frames = re.findall(r"frame=\s*(\d+)", err)
    fps = re.search(r"Stream #.*Video:.*?([\d.]+) fps", err)
    if not frames or not fps or float(fps.group(1)) <= 0:
        return 0.0, 0.0, 0.0
    length = int(frames[-1]) / float(fps.group(1))
    frozen = _spans(err, "lavfi.freezedetect.freeze", length)
    head, tail = _edges(frozen, length)
    if head >= length - 0.1:
        return round(length, 3), 0.0, 0.0  # a still shot by design: keep it whole
    if spoken:
        quiet = _edges(_spans(err, "silence", length), length)
        head, tail = min(head, quiet[0]), min(tail, quiet[1])
    head, tail = (min(STILL_CAP, x) if x >= STILL_MIN else 0.0 for x in (head, tail))
    spare = length - MIN_KEEP
    if head + tail > spare:
        scale = max(0.0, spare) / (head + tail)
        head, tail = head * scale, tail * scale
    return round(length, 3), round(head, 3), round(tail, 3)


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
        return min(SPOKEN_GAIN_MAX, gain_to(lufs, DIALOGUE_LUFS))
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


def loop_audio_crossfade(
    src_path: str,
    target_seconds: float,
    out_path: str,
    crossfade_s: float = 2.5,
) -> str:
    """Loop ``src_path`` to ``target_seconds`` as a 48 kHz stereo WAV using
    equal-power cosine/sine crossfades across each loop boundary."""
    import wave

    import numpy as np

    sr = 48000
    raw = subprocess.run(
        [
            _ffmpeg(),
            "-v",
            "error",
            "-i",
            src_path,
            "-ar",
            str(sr),
            "-ac",
            "2",
            "-f",
            "f32le",
            "-acodec",
            "pcm_f32le",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    ).stdout
    samples = np.frombuffer(raw, dtype=np.float32)
    n_frames = len(samples) // 2
    samples = samples[: n_frames * 2].reshape(n_frames, 2)
    target_n = max(1, int(round(max(0.1, float(target_seconds)) * sr)))
    if n_frames == 0:
        out = np.zeros((target_n, 2), dtype=np.float32)
    elif n_frames >= target_n:
        out = samples[:target_n].copy()
    else:
        src_dur = n_frames / sr
        cf_s = max(0.0, min(float(crossfade_s), src_dur / 3.0))
        cf_n = min(int(round(cf_s * sr)), n_frames // 3)
        step = max(1, n_frames - cf_n)
        out = np.zeros((target_n, 2), dtype=np.float32)
        first_take = min(n_frames, target_n)
        out[:first_take] = samples[:first_take]
        if cf_n > 0:
            theta = np.linspace(0.0, np.pi / 2.0, cf_n, dtype=np.float32)[:, None]
            fade_out = np.cos(theta)
            fade_in = np.sin(theta)
        pos = step
        while pos < target_n:
            ov = min(cf_n, target_n - pos)
            if ov > 0:
                out[pos : pos + ov] = (
                    out[pos : pos + ov] * fade_out[:ov]
                    + samples[:ov] * fade_in[:ov]
                )
            body_start = pos + cf_n
            if body_start < target_n:
                rem = min(n_frames - cf_n, target_n - body_start)
                out[body_start : body_start + rem] = samples[cf_n : cf_n + rem]
            pos += step
    pcm = (np.clip(out, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(out_path, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return out_path


def _frame_luma(path: str, at_seconds: float) -> float | None:
    """Mean normalized luma [0, 1] of one frame near `at_seconds`, or None."""
    if not path or not os.path.exists(path):
        return None
    import io

    import numpy as np
    from PIL import Image

    for t in (max(0.0, float(at_seconds)), max(0.0, float(at_seconds) - 0.25)):
        res = subprocess.run(
            [
                _ffmpeg(),
                "-v",
                "error",
                "-ss",
                f"{t:.3f}",
                "-i",
                path,
                "-frames:v",
                "1",
                "-f",
                "image2pipe",
                "-vcodec",
                "png",
                "pipe:1",
            ],
            capture_output=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout:
            try:
                img = Image.open(io.BytesIO(res.stdout)).convert("L")
                return float(np.asarray(img, dtype=np.float32).mean() / 255.0)
            except Exception:
                return None
    return None


def compute_boundary_eq(
    prev_path: str, prev_out: float, cur_path: str, cur_in: float
) -> float:
    """Brightness offset in [-0.08, 0.08] matching `cur` at `cur_in` to `prev`
    near `prev_out`. Returns 0.0 for near-black/white frames or diff < 0.02."""
    luma_prev = _frame_luma(prev_path, max(0.0, float(prev_out) - 0.08))
    luma_cur = _frame_luma(cur_path, max(0.0, float(cur_in)))
    if luma_prev is None or luma_cur is None:
        return 0.0
    if luma_prev < 0.05 or luma_cur < 0.05 or luma_prev > 0.95 or luma_cur > 0.95:
        return 0.0
    if abs(luma_prev - luma_cur) < 0.02:
        return 0.0
    ratio = luma_prev / luma_cur
    offset = (ratio - 1.0) * 0.25
    return round(max(-0.08, min(0.08, offset)), 4)


def render_args(
    timeline: dict,
    paths: dict[str, str],
    has_audio: dict[str, bool],
    overlays: dict[str, str],
    out_path: str,
    preset: str = "veryfast",
    logo_png: str = "",
    crf: int = 20,
    fmt: str = "mp4",
    end_hold: float = 0.0,
) -> list[str]:
    """ffmpeg argv that renders `timeline` (already normalized).

    ``paths`` maps each clip src to a local file, ``has_audio`` says which
    files have sound, ``overlays`` maps text clip ids to full-frame RGBA PNGs.
    ``logo_png`` is a full-frame PNG shown for the whole film (brand logo).
    ``fmt`` is a key of EXPORT_FORMATS; the audio formats skip the picture.
    ``end_hold``: seconds the last frame is held (fading to black) after
    the last clip; music that reaches the end must already cover it.
    """
    w, h, fps = timeline["width"], timeline["height"], timeline["fps"]
    end_hold = max(0.0, float(end_hold or 0.0))
    total = max(0.1, duration(timeline)) + end_hold
    video = EXPORT_FORMATS.get(fmt, EXPORT_FORMATS["mp4"])["video"]
    args = [_ffmpeg(), "-v", "error", "-y"]
    filters: list[str] = []
    # Picture filters; an audio-only render leaves them out.
    vf: list[str] = filters if video else []
    n = 0

    def add_input(path: str, *pre: str) -> int:
        nonlocal n
        args.extend([*pre, "-i", path])
        n += 1
        return n - 1

    # Video: black canvas, each clip overlaid at its start (fades = crossfades).
    vf.append(f"color=c=black:s={w}x{h}:r={fps}:d={total:.3f}[base]")
    last = "base"
    dialogue: list[str] = []
    # Narrated clips' own sound: a bed under the voice, mixed after the
    # ducking so it neither ducks the music nor is ducked.
    beds: list[str] = []
    vclips = merge_runs(track(timeline, "video")["clips"], fps)
    color_match = bool(timeline.get("color_match", True))
    for k, c in enumerate(vclips):
        idx = add_input(paths[c["src"]])
        length = clip_length(c)
        # Snap the clip's slot to whole output frames. A start like 11.96 s
        # falls between two frames at 24 fps; without this the frame at
        # 11.958 belonged to neither clip and showed the black canvas.
        f0 = round(c["start"] * fps)
        frames = max(1, round((c["start"] + length) * fps) - f0)
        next_c = vclips[k + 1] if k + 1 < len(vclips) else None
        hold_frames = round(end_hold * fps) if next_c is None else 0
        frames += hold_frames
        start, slot = f0 / fps, frames / fps
        prev_c = vclips[k - 1] if k > 0 else None
        eq_b = 0.0
        if video and color_match and prev_c is not None and c.get("join") == "bridge":
            eq_b = compute_boundary_eq(
                paths[prev_c["src"]], prev_c["out"], paths[c["src"]], c["in"]
            )
        # One spare frame past the slot (hidden by `enable`): overlay treats a
        # clip as over at its last frame's time, which blacked out the film's
        # final frame.
        chain = (
            f"[{idx}:v]trim=start={c['in']:.3f}:end={c['out']:.3f},setpts=PTS-STARTPTS,"
            f"fps={fps},scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
        )
        if abs(eq_b) > 0.001:
            chain += f"eq=brightness={eq_b:.4f},"
        chain += (
            # A clip whose picture ends early holds its last frame instead of
            # showing the black canvas, and never runs past its slot.
            f"tpad=stop_mode=clone:stop_duration={slot + 2 / fps:.3f},trim=end_frame={frames + 1},"
            "format=yuva420p"
        )
        if c.get("fade_in"):
            if c.get("join") == "fade_black":
                chain += f",fade=t=in:st=0:d={c['fade_in']:.3f}"
            else:
                chain += f",fade=t=in:st=0:d={c['fade_in']:.3f}:alpha=1"
        if hold_frames:
            hold = hold_frames / fps
            chain += f",fade=t=out:st={max(0.0, slot - hold):.3f}:d={hold:.3f}"
        if (
            next_c is not None
            and next_c.get("join") == "fade_black"
            and next_c.get("fade_in", 0) > 0
        ):
            dip = min(next_c["fade_in"] / 2.0, slot / 2.0)
            dip_st = max(0.0, (next_c["start"] - start) - dip)
            if dip > 0.01:
                chain += f",fade=t=out:st={dip_st:.3f}:d={dip:.3f}:alpha=1"
        # Offset by whole frames (the fps filter set the time base to 1/fps):
        # PTS+11.958333/TB rounds down to frame 286 instead of 287.
        chain += f",setpts=PTS+{f0}[v{k}]"
        vf.append(chain)
        vf.append(
            f"[{last}][v{k}]overlay=eof_action=pass:enable='between(t,{start:.6f},"
            f"{start + slot - 0.5 / fps:.6f})'[o{k}]"
        )
        last = f"o{k}"
        if c.get("gain", 0) > 0 and has_audio.get(c["src"]):
            bucket = beds if c.get("ambient") else dialogue
            aclip = c
            alen = length
            # At a cut the outgoing sound runs on under the incoming one, so
            # the two cross instead of both fading to a dip (heard as a cut).
            tail = 0.16 if c.get("ambient") else (JOIN_FADE if next_c is not None else 0.0)
            if tail and c["out"] + tail <= c.get("src_max", c["out"]):
                aclip = {**c, "out": round(c["out"] + tail, 3)}
                alen = clip_length(aclip)
            bucket.append(
                _audio_chain(
                    filters,
                    idx,
                    aclip,
                    alen,
                    f"d{k}",
                    fade=JOIN_FADE,
                    # The film's last sound eases out instead of stopping.
                    fade_out=END_SOUND_FADE if next_c is None else None,
                )
            )
    for k, c in enumerate(track(timeline, "text")["clips"] if video else []):
        png = overlays.get(c["id"])
        if not png:
            continue
        idx = add_input(png, "-loop", "1", "-t", f"{total:.3f}")
        end = min(total, c["start"] + c["dur"])
        vf.append(
            f"[{last}][{idx}:v]overlay=0:0:enable='between(t,{c['start']:.3f},{end:.3f})'[t{k}]"
        )
        last = f"t{k}"
    if logo_png and video:
        idx = add_input(logo_png, "-loop", "1", "-t", f"{total:.3f}")
        vf.append(f"[{last}][{idx}:v]overlay=0:0[logo]")
        last = "logo"
    vf.append(f"[{last}]format=yuv420p[vout]")

    for k, c in enumerate(track(timeline, "voice")["clips"]):
        if not has_audio.get(c["src"], True):
            continue
        idx = add_input(paths[c["src"]])
        # A line ended early (see _place_voices) eases out, never clicks.
        dialogue.append(
            _audio_chain(
                filters, idx, c, clip_length(c), f"s{k}", fade_out=VOICE_CUT_FADE
            )
        )

    music_track = track(timeline, "music")
    music: list[str] = []
    for k, c in enumerate(music_track["clips"]):
        if not has_audio.get(c["src"], True):
            continue
        if c.get("_looped"):
            idx = add_input(paths[c["src"]])
        else:
            idx = add_input(paths[c["src"]], "-stream_loop", "-1")
        mlen = clip_length(c)
        # The music that runs to the end of the film fades out slowly.
        outro = MUSIC_OUTRO if c["start"] + mlen >= total - 0.05 else None
        music.append(
            _audio_chain(filters, idx, c, mlen, f"m{k}", fade=1.0, fade_out=outro)
        )

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
            # Dialogue that ends before the film (a held ending) stalled the
            # compressor now and then: it runs to the film's end first.
            filters.append(f"[{dlg}]apad=whole_dur={total:.3f},asplit=2[dlg1][dlg2]")
            # sidechaincompress drops what it still holds when an input
            # ends, at a point that varies between runs: unpadded, the music
            # stopped dead anywhere up to a second before the film's end.
            # Both inputs run on past the end (silence) and the result is
            # trimmed back, so whatever it drops is after the film. Both pads
            # end at a fixed time: an endless pad made held endings hang.
            padded = total + DUCK_PAD
            filters.append(
                f"[{mus}]apad=whole_dur={padded:.3f}[mus_p];"
                f"[dlg2]apad=whole_dur={padded:.3f}[dlg2_p];"
                "[mus_p][dlg2_p]sidechaincompress=threshold=0.02:ratio=8:attack=20:"
                f"release=450:makeup=1,atrim=0:{total:.3f}[mducked]"
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

    if not video and not audio_out:
        # Audio only, and nothing makes a sound: silence the film's length.
        filters.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{total:.3f}[aout]")
        audio_out = "aout"
    args += ["-filter_complex", ";".join(filters)]
    if video:
        args += ["-map", "[vout]"]
    if audio_out:
        args += ["-map", f"[{audio_out}]"]
    args += encode_args(fmt, preset, crf, fps, total, bool(audio_out))
    args.append(out_path)
    return args


# Export menu formats: picture codec, sound codec, container.
EXPORT_FORMATS = {
    "mp4": {"label": "MP4 (H.264)", "ext": "mp4", "mime": "video/mp4", "video": True},
    "mov": {"label": "MOV", "ext": "mov", "mime": "video/quicktime", "video": True},
    "webm": {"label": "WebM", "ext": "webm", "mime": "video/webm", "video": True},
    "mp3": {"label": "MP3", "ext": "mp3", "mime": "audio/mpeg", "video": False},
    "wav": {"label": "WAV", "ext": "wav", "mime": "audio/wav", "video": False},
}
# Export sizes by the short side (9:16 at "1080p" is 1080 wide).
RESOLUTIONS = (540, 720, 1080, 2160)
RESOLUTION_LABELS = {540: "540p", 720: "720p", 1080: "1080p", 2160: "4K"}
# The preview proxy: quick to make, small to stream; the same picture and
# sound as an export, only softer.
PROXY_SHORT_SIDE = 540
PROXY_CRF = 30
PROXY_PRESET = "ultrafast"


def encode_args(
    fmt: str, preset: str, crf: int, fps: int, total: float, audio: bool
) -> list[str]:
    """ffmpeg output options for an EXPORT_FORMATS key (without the path)."""
    t = ["-t", f"{total:.3f}"]
    if fmt == "mp3":
        return ["-vn", "-c:a", "libmp3lame", "-q:a", "2", *t]
    if fmt == "wav":
        return ["-vn", "-c:a", "pcm_s16le", "-ar", "48000", *t]
    quick = preset == PROXY_PRESET
    if fmt == "webm":
        out = [
            "-c:v", "libvpx-vp9", "-crf", str(min(63, crf + 11)), "-b:v", "0",
            "-deadline", "realtime" if quick else "good",
            "-cpu-used", "8" if quick else "4", "-row-mt", "1",
            "-pix_fmt", "yuv420p", "-r", str(fps),
        ]
        if audio:
            out += ["-c:a", "libopus", "-b:a", "128k"]
        return out + t
    out = [
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
        "-r", str(fps),
    ]
    if audio:
        out += ["-c:a", "aac", "-b:a", "128k" if quick else "192k"]
    if fmt == "mov":
        out += ["-f", "mov"]
    return out + [*t, "-movflags", "+faststart"]


def source_short_side(timeline: dict) -> int:
    """The timeline's own frame size by its short side (720 for 1280x720)."""
    return int(min(timeline.get("width") or 1280, timeline.get("height") or 720))


def resolution_options(timeline: dict) -> list[dict]:
    """Export sizes: up to the clips' own size, and the sizes above it
    marked as upscaled: {"short": 1080, "label": "1080p", "upscale": True}."""
    src = source_short_side(timeline)
    out = [
        {"short": p, "label": RESOLUTION_LABELS[p], "upscale": p > src}
        for p in RESOLUTIONS
    ]
    if src not in RESOLUTIONS:
        out.append({"short": src, "label": f"{src}p", "upscale": False})
        out.sort(key=lambda r: r["short"])
    return out


def scaled_size(width: int, height: int, short: int) -> tuple[int, int]:
    """(width, height) with the short side at `short`, both even."""
    scale = short / max(1, min(width, height))
    return (
        max(2, int(round(width * scale / 2)) * 2),
        max(2, int(round(height * scale / 2)) * 2),
    )


def _audio_chain(
    filters: list[str],
    idx: int,
    c: dict,
    length: float,
    label: str,
    fade: float = EDGE_FADE,
    fade_out: float | None = None,
) -> str:
    tempo = float(c.get("tempo") or 1.0)
    chain = f"[{idx}:a]atrim=start={c['in']:.3f}:end={c['out']:.3f},asetpts=PTS-STARTPTS"
    if abs(tempo - 1.0) > 0.005:
        chain += "," + _atempo(tempo)
    f = min(fade, length / 3)
    fo = min(fade if fade_out is None else fade_out, length / 2)
    chain += (
        f",aformat=sample_rates=48000:channel_layouts=stereo,volume={c.get('gain', 1.0):.3f},"
        f"afade=t=in:st=0:d={f:.3f}:curve=qsin,"
        f"afade=t=out:st={max(0.0, length - fo):.3f}:d={fo:.3f}:curve=qsin,"
        f"adelay={int(round(c['start'] * 1000))}:all=1[{label}]"
    )
    filters.append(chain)
    return label


def overlay_font(size: int, bold: bool = False, rtl: bool = False):
    """The first available font for the script (Latin, or Arabic and Hebrew
    when `rtl`), else Pillow's own."""
    from PIL import ImageFont

    if rtl:
        paths = (RTL_BOLD_FONT_CANDIDATES if bold else ()) + RTL_FONT_CANDIDATES
    else:
        paths = (BOLD_FONT_CANDIDATES if bold else ()) + FONT_CANDIDATES
    for path in paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # older Pillow
        return ImageFont.load_default()


def _text_kwargs(text: str) -> dict:
    """Right-to-left layout for Arabic and Hebrew when Pillow can shape it."""
    from PIL import features

    if _RTL.search(text) and features.check("raqm"):
        return {"direction": "rtl"}
    return {}


def wrap_lines(text: str, measure, max_width: float) -> list[str]:
    """Break `text` into lines no wider than `max_width` (explicit line
    breaks are kept). `measure(line)` returns a line's width."""
    lines: list[str] = []
    for para in str(text).split("\n"):
        line = ""
        for word in para.split():
            trial = f"{line} {word}".strip()
            if measure(trial) > max_width and line:
                lines.append(line)
                line = word
            else:
                line = trial
        lines.append(line)
    return [ln for ln in lines if ln] or [""]


def text_overlay_png(clip: dict, width: int, height: int, out_path: str) -> str:
    """A full-frame transparent PNG with the clip's text, wrapped, in its
    style: clean (soft shadow), boxed (dark box) or bold (outlined)."""
    from PIL import Image, ImageDraw

    style = clip.get("style") if clip.get("style") in TEXT_STYLES else "clean"
    size = max(10, int(clip.get("size", 48) * height / 720))
    bold = style == "bold"
    fonts = {False: overlay_font(size, bold), True: overlay_font(size, bold, rtl=True)}
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Font and direction per line: an English + Arabic caption mixes both.
    def font_for(s: str):
        return fonts[bool(_RTL.search(s))]

    def measure(s: str) -> float:
        return draw.textlength(s, font=font_for(s), **_text_kwargs(s))

    lines = wrap_lines(clip["text"], measure, width * 0.86)
    gap = int(size * 1.3)
    block = gap * len(lines)
    margin = int(height * (0.07 if clip.get("sub") else 0.08))
    y = {"top": margin, "center": (height - block) // 2}.get(
        clip.get("pos"), height - block - margin
    )
    pad = max(2, size // 16)
    if style == "boxed":
        widest = max(measure(ln) for ln in lines)
        bx, by = size * 0.5, size * 0.3
        draw.rounded_rectangle(
            ((width - widest) / 2 - bx, y - by, (width + widest) / 2 + bx, y + block + by * 0.4),
            radius=int(size * 0.35),
            fill=(0, 0, 0, 160),
        )
    for ln in lines:
        x = (width - measure(ln)) / 2
        kw = _text_kwargs(ln)
        font = font_for(ln)
        if style == "clean":
            draw.text((x + pad, y + pad), ln, font=font, fill=(0, 0, 0, 170), **kw)
            draw.text((x, y), ln, font=font, fill=(255, 255, 255, 255), **kw)
        elif style == "bold":
            draw.text(
                (x, y), ln, font=font, fill=(255, 255, 255, 255),
                stroke_width=max(2, size // 12), stroke_fill=(0, 0, 0, 230), **kw,
            )
        else:
            draw.text((x, y), ln, font=font, fill=(255, 255, 255, 255), **kw)
        y += gap
    img.save(out_path, "PNG")
    return out_path


def render_timeline(
    timeline: dict,
    fetch,
    out_path: str,
    preset: str = "veryfast",
    logo: str = "",
    logo_corner: str = "auto",
    check_seams: bool = False,
    logo_size: str = "s",
    short_side: int = 0,
    crf: int = 20,
    fmt: str = "mp4",
) -> str:
    """Render a timeline to a file (MP4 unless ``fmt`` says otherwise, see
    EXPORT_FORMATS). ``fetch(uri, local_path)`` copies a source file to disk
    (GCS download, or a local copy in demo mode). ``logo`` is an image uri
    drawn in ``logo_corner`` at ``logo_size`` for the whole film.
    ``short_side`` scales the film (0 keeps the timeline's size).
    ``check_seams`` measures every join of the result into
    ``timeline["seams"]`` (see :func:`seam_check`)."""
    from common.error_handling import GenerationError

    tl = normalize(timeline)
    if not track(tl, "video")["clips"]:
        raise GenerationError("The timeline has no video clips.")
    if short_side:
        tl["width"], tl["height"] = scaled_size(tl["width"], tl["height"], short_side)
    with tempfile.TemporaryDirectory() as tmp:
        paths: dict[str, str] = {}
        has_audio: dict[str, bool] = {}
        src_durations: dict[str, float] = {}
        for t in tl["tracks"]:
            for c in t["clips"]:
                src = c.get("src")
                if not src or src in paths:
                    continue
                ext = os.path.splitext(src.split("?")[0])[1][:6] or ".bin"
                local = os.path.join(tmp, f"src{len(paths)}{ext}")
                fetch(src, local)
                paths[src] = local
                dur, aud = probe(local)
                src_durations[src] = dur
                has_audio[src] = aud
        hold = end_hold(tl, paths, has_audio)
        if hold:
            # The music that reaches the end plays on under the held frame.
            end = duration(tl)
            for c in track(tl, "music")["clips"]:
                if clip_end(c) >= end - 0.05:
                    c["out"] = round(float(c["out"]) + hold, 3)
        for k, c in enumerate(track(tl, "music")["clips"]):
            src = c.get("src", "")
            if not src or not has_audio.get(src, True):
                continue
            src_dur = src_durations.get(src, 0.0)
            need = max(clip_length(c), float(c.get("out") or 0.0))
            if src_dur > 0 and need > src_dur + 0.2:
                loop_wav = os.path.join(tmp, f"music_loop_{k}.wav")
                loop_audio_crossfade(paths[src], need + 0.5, loop_wav)
                loop_key = f"__music_loop_{k}_{src}"
                paths[loop_key] = loop_wav
                has_audio[loop_key] = True
                c["src"] = loop_key
                c["_looped"] = True
        overlays = {
            c["id"]: text_overlay_png(
                c, tl["width"], tl["height"], os.path.join(tmp, f"text_{c['id']}.png")
            )
            for c in track(tl, "text")["clips"]
        }
        logo_png = ""
        if logo:
            try:
                from common.brand_kit import logo_overlay_png

                ext = os.path.splitext(logo.split("?")[0])[1][:6] or ".png"
                raw = os.path.join(tmp, f"logo_src{ext}")
                fetch(logo, raw)
                logo_png = logo_overlay_png(
                    raw,
                    tl["width"],
                    tl["height"],
                    os.path.join(tmp, "logo.png"),
                    logo_corner,
                    size=logo_size,
                )
            except Exception:  # a broken logo never stops the film
                from common.analytics import get_logger

                get_logger(__name__).warning("Brand logo skipped", exc_info=True)
                logo_png = ""
        args = render_args(
            tl,
            paths,
            has_audio,
            overlays,
            out_path,
            preset,
            logo_png,
            crf=crf,
            fmt=fmt,
            end_hold=hold,
        )
        result = run_ffmpeg(args)
        if result.returncode != 0:
            from common.analytics import get_logger

            get_logger(__name__).error("ffmpeg render failed: %s", result.stderr[-2000:])
            raise GenerationError("Rendering the film failed. Retry export.")
    if check_seams:
        cuts = [
            {
                "t": c["start"] + float(c.get("fade_in") or 0) / 2,
                "scene": c.get("scene", -1),
                "seamless": c.get("join") in SEAMLESS_JOINS,
            }
            for c in merge_runs(track(tl, "video")["clips"], tl["fps"])[1:]
        ]
        try:
            # One decode of the film serves both checks.
            changes = frame_changes(out_path)
            timeline["seams"] = seam_check(out_path, cuts, changes=changes)
            planned = [c["t"] for c in cuts if not c["seamless"]]
            # Cuts nobody planned (inside a take, or at a seamless join).
            timeline["cuts"] = [
                c for c in take_cuts(out_path, changes=changes)
                if all(abs(c["t"] - p) > 0.3 for p in planned)
            ]
        except Exception:  # the check never stops the film
            from common.analytics import get_logger

            get_logger(__name__).warning("Seam check skipped", exc_info=True)
    return out_path


def speech_end(path: str, start: float, end: float) -> float:
    """Seconds into `path` where its last speech (a slice above SPEECH_DB)
    between `start` and `end` stops; `start` when there is none."""
    window = 0.05
    levels = audio_levels(path, window)
    a, b = int(start / window), min(len(levels), int(end / window))
    loud = [i for i in range(a, b) if levels[i] > SPEECH_DB]
    return (loud[-1] + 1) * window if loud else start


def end_hold(tl: dict, paths: dict[str, str], has_audio: dict[str, bool]) -> float:
    """END_HOLD when speech (the last clip's own, or the last voice line)
    runs within END_SPEECH_GAP of the film's end, else 0."""
    total = duration(tl)
    last = 0.0
    vclips = track(tl, "video")["clips"]
    candidates = []
    if vclips:
        c = max(vclips, key=clip_end)
        if not c.get("ambient") and float(c.get("gain", 0)) > 0:
            candidates.append(c)
    candidates += track(tl, "voice")["clips"][-1:]
    for c in candidates:
        path = paths.get(c.get("src", ""))
        if not path or not has_audio.get(c["src"], True):
            continue
        tempo = float(c.get("tempo") or 1.0) or 1.0
        t = speech_end(path, float(c["in"]), float(c["out"]))
        if t > float(c["in"]):
            last = max(last, float(c["start"]) + (t - float(c["in"])) / tempo)
    return END_HOLD if last and total - last < END_SPEECH_GAP else 0.0


# A join whose picture change is this many times the film's typical
# frame-to-frame change shows as a visible jump.
SEAM_JUMP_RATIO = 5.0
# Joins meant to be invisible. A jump at any other join is a planned cut.
SEAMLESS_JOINS = ("bridge", "extend")


def frame_changes(path: str) -> list[tuple[float, float]]:
    """(time, change from the previous frame) for every frame of a video:
    ffmpeg's scene score, 0 for identical frames up to 1 for a new picture."""
    import re

    with tempfile.TemporaryDirectory() as tmp:
        log = os.path.join(tmp, "scores.txt")
        run_ffmpeg(
            [
                _ffmpeg(), "-v", "error", "-i", path, "-an", "-vf",
                "select='gte(scene,0)',metadata=print:key=lavfi.scene_score:file=scores.txt",
                "-f", "null", "-",
            ],
            cwd=tmp,
        )
        if not os.path.exists(log):
            return []
        with open(log, encoding="utf-8", errors="replace") as f:
            text = f.read()
    times = [float(t) for t in re.findall(r"pts_time:([\d.]+)", text)]
    scores = [float(s) for s in re.findall(r"scene_score=([\d.]+)", text)]
    return list(zip(times, scores, strict=False))


# A frame change this many times a film's median is a hard cut (a jump to a
# new framing), wherever it falls; a continuous take should have none.
CUT_RATIO = 30.0
# ...and a real cut changes most of the picture: the cuts Omni made scored
# 0.34 to 0.44, caption swaps and soft joins about 0.02. Kept well above a
# fast camera pan (each flagged cut can pay for a turn to be made again),
# and still below the lowest real cut.
CUT_MIN_SCORE = 0.25


def locate(timeline: dict, t: float) -> tuple[int, float]:
    """(scene index, seconds into that scene's clip) at film time `t`, or
    (-1, 0.0) when no video clip plays there."""
    for clip in track(timeline, "video")["clips"]:
        start = float(clip.get("start", 0))
        length = float(clip.get("out", 0)) - float(clip.get("in", 0))
        if start <= t < start + length:
            return int(clip.get("scene", -1)), float(clip.get("in", 0)) + t - start
    return -1, 0.0


# A turn this many dB louder or quieter than its take's other turns is
# flagged, and a take whose quiet moments sit above NOISE_FLOOR_DB has
# background noise (hiss, crowd) under the speech.
SOUND_TURN_DB = 4.0
NOISE_FLOOR_DB = -45.0


def audio_levels(path: str, window: float = 0.05) -> list[float]:
    """dBFS of each `window`-second slice of a file's sound (mono, 16 kHz);
    [] when it has none."""
    import numpy as np

    result = subprocess.run(
        [_ffmpeg(), "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "16000",
         "-f", "s16le", "-"],
        capture_output=True,
        check=False,
    )
    data = np.frombuffer(result.stdout, dtype=np.int16).astype(np.float64) / 32768.0
    n = int(16000 * window)
    if result.returncode != 0 or len(data) < n:
        return []
    frames = data[: len(data) // n * n].reshape(-1, n)
    rms = np.sqrt(np.mean(frames**2, axis=1))
    return [float(v) for v in 20 * np.log10(np.maximum(rms, 1e-6))]


def sound_flags(path: str, turns: list[dict], window: float = 0.05) -> list[dict]:
    """Sound checks of one spoken take: a turn whose speech is SOUND_TURN_DB
    louder or quieter than the take's other turns ({"kind": "level", "turn",
    "db"}), and background noise ({"kind": "noise", "db"}). Speech level is
    the mean of a turn's loudest half (its pauses don't count)."""
    levels = audio_levels(path, window)
    if len(levels) < 20:
        return []
    flags: list[dict] = []

    def speech(chunk: list[float]) -> float | None:
        if len(chunk) < 10:
            return None
        top = sorted(chunk)[len(chunk) // 2 :]
        return sum(top) / len(top)

    per_turn = []
    for t in turns or []:
        a = int(float(t.get("start", 0)) / window)
        b = a + int(float(t.get("seconds", 0)) / window)
        per_turn.append(speech(levels[a:b]))
    known = sorted(v for v in per_turn if v is not None)
    if len(known) >= 2:
        middle = known[len(known) // 2]
        for k, v in enumerate(per_turn):
            if v is not None and abs(v - middle) > SOUND_TURN_DB:
                flags.append({"kind": "level", "turn": k, "db": round(v - middle, 1)})
    floor = sorted(levels)[len(levels) // 10]
    if floor > NOISE_FLOOR_DB:
        flags.append({"kind": "noise", "db": round(floor, 1)})
    return flags


def take_cuts(
    path: str,
    ratio: float = CUT_RATIO,
    skip: float = 0.25,
    min_score: float = CUT_MIN_SCORE,
    changes: list[tuple[float, float]] | None = None,
) -> list[dict]:
    """Hard cuts anywhere in a rendered film: every frame whose change is at
    least `ratio` times the median and at least `min_score` (a new picture,
    not a caption swap in a near-still shot), ignoring the first `skip`
    seconds.
    Unlike seam_check, which only looks next to planned joins, this finds a
    cut the video model made inside one generated take. ``changes``: the
    film's frame_changes when already measured."""
    if changes is None:
        changes = frame_changes(path)
    if len(changes) < 3:
        return []
    scores = sorted(s for _, s in changes)
    median = max(scores[len(scores) // 2], 1e-4)
    found = []
    for t_, s in changes:
        if t_ >= skip and s >= min_score and s / median >= ratio:
            if found and t_ - found[-1]["t"] < 0.2:  # one cut, several frames
                if s > found[-1]["score"]:
                    found[-1].update(t=round(t_, 3), score=round(s, 4),
                                     ratio=round(s / median, 1))
                continue
            found.append({"t": round(t_, 3), "score": round(s, 4),
                          "ratio": round(s / median, 1)})
    return found


def seam_check(
    path: str,
    cuts: list,
    window: float = 0.09,
    changes: list[tuple[float, float]] | None = None,
) -> list[dict]:
    """How visible each join of a rendered film is: the largest frame change
    within `window` seconds of the join, and how many times the film's
    median change that is. ``cuts`` are join times, or dicts with ``t``,
    ``scene`` (the clip after the join) and ``seamless`` (the join is meant
    to be invisible). ``jump`` marks a seamless join past SEAM_JUMP_RATIO.
    ``changes``: the film's frame_changes when already measured."""
    if not cuts:  # one take, no joins: nothing to decode
        return []
    if changes is None:
        changes = frame_changes(path)
    if not changes:
        return []
    ordered = sorted(s for _, s in changes)
    median = max(ordered[len(ordered) // 2], 1e-4)
    report = []
    for cut in cuts:
        info = cut if isinstance(cut, dict) else {"t": cut, "seamless": True}
        t = float(info["t"])
        near = [s for ts, s in changes if abs(ts - t) <= window]
        peak = max(near or [0.0])
        ratio = round(peak / median, 1)
        seamless = bool(info.get("seamless", True))
        report.append(
            {
                "t": round(t, 3),
                "scene": int(info.get("scene", -1) if info.get("scene") is not None else -1),
                "seamless": seamless,
                "score": round(peak, 4),
                "ratio": ratio,
                "jump": seamless and ratio >= SEAM_JUMP_RATIO,
            }
        )
    return report


def copy_timeline(timeline: dict) -> dict:
    return copy.deepcopy(timeline)
