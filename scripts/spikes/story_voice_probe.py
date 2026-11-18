"""Probe Story Studio's continuous spoken takes on real Gemini Omni.

Runs the app's own code path (``VertexStoryBackend``): scene 1 is a fresh
clip, scenes 2..N continue it in the same Omni thread
(``previous_interaction_id`` plus the take's history), exactly as a render
of back-to-back spoken scenes does. Prints each clip's interaction ID,
length, repeated head (``clip_in``) and loudness, and saves the clips so
you can listen for one consistent voice across them.

This makes billable Vertex AI calls (about LINES x SECONDS of Omni output
video, plus the re-sent history as input). It refuses to run without --yes.

Usage (from the repo root, with the app's environment, e.g. under
``core run --``):

    PYTHONDONTWRITEBYTECODE=1 python scripts/spikes/story_voice_probe.py OUTDIR --yes
        [--lines 3] [--seconds 8] [--resolution 720p] [--aspect 16:9]
"""

import argparse
import os
import sys

ap = argparse.ArgumentParser()
ap.add_argument("outdir")
ap.add_argument("--yes", action="store_true", help="confirm the billable run")
ap.add_argument("--lines", type=int, default=3, choices=(2, 3))
ap.add_argument("--seconds", type=int, default=8, help="seconds per scene")
ap.add_argument("--resolution", default="720p")
ap.add_argument("--aspect", default="16:9")
a = ap.parse_args()

if not a.yes:
    est = a.lines * a.seconds
    sys.exit(
        f"Billable: about {est} s of Gemini Omni output video. "
        "Re-run with --yes once the owner has approved the cost."
    )

# Config is read when config.default is imported: set it first.
os.environ["STORY_VIDEO_RESOLUTION"] = a.resolution
os.environ.setdefault("STORY_STUDIO_MOCK", "false")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(os.path.join(ROOT, "src"))
os.makedirs(a.outdir, exist_ok=True)

from common.storage import download_from_gcs  # noqa: E402
from config.default import Default  # noqa: E402
from services import story_timeline as T  # noqa: E402
from services.story_models import Scene, Story  # noqa: E402
from services.story_service import VertexStoryBackend  # noqa: E402

LINES = [
    "Good evening, everyone, and thank you so much for being here tonight.",
    "Two years ago we asked one simple question: what if your phone just listened?",
    "Tonight, I am proud to show you the answer. Let's begin.",
]

story = Story(
    title="Voice probe",
    idea="A presenter opens a product launch on a conference stage",
    aspect_ratio=a.aspect,
    scene_count=a.lines,
    duration=a.seconds,
    character="a woman in her late 30s with short dark hair and a navy blazer",
    speaker_voice="a female voice, late 30s, warm and confident, neutral American accent",
    scenes=[
        Scene(
            narration=line,
            spoken=True,
            duration=a.seconds,
            camera="static",
            visual=(
                "Medium shot of the presenter on a dark conference stage, a large "
                "screen glowing behind her, speaking into a headset microphone."
            ),
        )
        for line in LINES[: a.lines]
    ],
)
cfg = Default()
print(f"model={cfg.STORY_VIDEO_MODEL} resolution={a.resolution} take cap={cfg.STORY_TAKE_MAX_SECONDS}s")
for i in range(1, a.lines):
    print(f"scene {i + 1} continues the take: {story.continues_take(i)}")

backend = VertexStoryBackend()
rows = []
for i, sc in enumerate(story.scenes):
    if i == 0:
        uri, clip_in = backend.generate_clip(story, 0, ""), 0.0
    else:
        uri, clip_in = backend.extend_clip(story, i, story.scenes[i - 1].clip_uri)
    sc.clip_uri, sc.interaction_id = uri, backend.interaction_of(uri)
    path = os.path.join(a.outdir, f"scene{i + 1}.mp4")
    with open(path, "wb") as f:
        f.write(download_from_gcs(uri))
    length, has_audio = T.probe(path)
    lufs = T.measure_lufs(path) if has_audio else None
    rows.append((i + 1, sc.interaction_id, length, clip_in, lufs, uri))
    print(
        f"scene {i + 1}: interaction={sc.interaction_id} length={length:.2f}s "
        f"repeated_head={clip_in:.2f}s loudness={lufs} LUFS -> {path}"
    )

total = sum(r[2] - r[3] for r in rows)
print(f"\nOmni output: {sum(r[2] for r in rows):.1f} s ({total:.1f} s of new picture)")
print("Listen to the scene files in order: the voice should not change between them.")
