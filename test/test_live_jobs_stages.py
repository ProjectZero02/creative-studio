# Copyright 2025 Google LLC
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
"""Home's every-option settings, visible job steps and the chat's thinking trace."""

import json
from types import SimpleNamespace

import pytest
from google.genai import types

from services import live_jobs, studio_chat, studio_options
from services.live_jobs import DONE, LiveJob, LiveJobs, RunResult

OWNER = "stages@example.com"


# ------------------------------------------------------------ studio_options


def test_fields_follow_the_schema():
    allowed = {"select", "toggle", "text", "textarea", "number"}
    for kind, fields in studio_options.all_fields().items():
        names = [f["name"] for f in fields]
        for f in fields:
            assert f["type"] in allowed and f["tier"] in ("main", "advanced"), (kind, f)
            assert {"name", "label", "default", "options"} <= set(f)
            if f["type"] == "toggle":
                assert f["default"] in ("on", "off")
            for other in f.get("show_if") or {}:
                assert other in names, (kind, f["name"], other)


def test_every_studio_control_is_offered():
    names = {
        k: {f["name"] for f in fs} for k, fs in studio_options.all_fields().items()
    }
    assert {"model", "aspect", "size", "brand", "search", "thinking"} <= names["image"]
    assert {"model", "mode", "aspect", "duration", "resolution", "audio"} <= names[
        "video"
    ]
    assert {"model", "count", "lyrics", "lyrics_text", "instrumental"} <= names["music"]
    assert {
        "model",
        "voice",
        "language",
        "style",
        "pace",
        "dialogue",
        "speaker_a",
        "speaker_b",
        "voice_b",
        "direction",
        "pronunciations",
    } <= names["voice"]
    assert {
        "length",
        "source",
        "engine",
        "pacing",
        "speech",
        "camera",
        "scenes",
        "scene_length",
    } <= names["film"]
    lengths = [o["value"] for o in studio_options.fields("film")[0]["options"]]
    assert lengths == ["auto", "30", "60", "120", "180", "300", "600"]


def test_veo_fields_show_when_veo_is_listed(monkeypatch):
    from config import video_studio_models

    monkeypatch.setattr(video_studio_models, "veo_models_shown", lambda: True)
    video = {f["name"]: f for f in studio_options.fields("video")}
    for name in ("count", "negative_prompt", "seed", "people"):
        assert name in video and video[name]["tier"] in ("main", "advanced")
    assert video["people"]["default"] == "allow_adult"
    assert "extend" in [o["value"] for o in video["mode"]["by_model"]["3.1"]["options"]]
    cleaned = studio_options.clean(
        "video", {"model": "3.1", "seed": "99999999999", "count": "3", "people": "x"}
    )
    assert cleaned["seed"] == "4294967295" and cleaned["count"] == "3"
    assert cleaned["people"] == "allow_adult"
    # Omni hides the Veo-only fields, so they fall back to their defaults.
    omni = studio_options.clean("video", {"seed": "5", "count": "3"})
    assert omni["seed"] == "0" and omni["count"] == "1"


def test_image_labels_are_clear_and_music_matches_the_studio():
    labels = [o["label"] for o in studio_options.fields("image")[0]["options"]]
    assert "Nano Banana Pro · Gemini 3 Pro Image" in labels
    assert studio_options.fields("music")[0]["default"] == "lyria-3-pro-preview"


def test_clean_trims_caps_and_checks_toggles():
    out = studio_options.clean(
        "music",
        {"lyrics": "on", "lyrics_text": "  la la  " + "x" * 9000, "instrumental": True},
    )
    assert out["lyrics_text"].startswith("la la") and len(out["lyrics_text"]) == 4000
    assert out["instrumental"] == "on"
    hidden = studio_options.clean("music", {"lyrics": "off", "lyrics_text": "words"})
    assert hidden["lyrics_text"] == ""
    voice = studio_options.clean(
        "voice", {"speaker_a": "  Ann   Lee ", "voice_b": "nope"}
    )
    assert voice["voice_b"] == "Puck"


def test_inputs_list_the_file_slots():
    slots = studio_options.all_inputs()
    assert set(slots) == set(studio_options.KINDS)
    video = {s["name"]: s for s in slots["video"]}
    assert video["first_frame"]["show_if"] == {"mode": ["i2v", "interpolation"]}
    assert video["video"]["accept"] == "video/*"
    assert video["references"]["max"] == 10
    assert slots["image"][0]["max"] == 14
    assert slots["voice"] == [] and slots["film"] == []


# ---------------------------------------------------------------- stages


def test_stages_are_planned_per_kind():
    def job(kind, **kw):
        return LiveJob(
            id="x", owner=OWNER, kind=kind, handle=f"{kind} 1", prompt="p", **kw
        )

    stages, secs = live_jobs.plan_stages(job("image"))
    assert (
        stages
        == [
            "Preparing prompt",
            "Sending to Gemini",
            "Generating image",
            "Saving to library",
            "Done",
        ]
        and secs > 0
    )
    refs = job("image", params={"inputs": {"references": [{"uri": "gs://b/a.png"}]}})
    assert live_jobs.plan_stages(refs)[0][0] == "Reading your references"
    video = job("video", params={"settings": {"mode": "extend"}})
    stages, secs = live_jobs.plan_stages(video)
    assert stages[0] == "Preparing the clip" and stages[2] == "Extending video"
    assert stages[1] == "Sending to Gemini Omni" and secs >= 60
    assert live_jobs.plan_stages(job("music"))[0][2] == "Composing"
    assert live_jobs.plan_stages(job("voice"))[0][1].startswith("Sending to Gemini")


def test_mock_runner_walks_every_stage(monkeypatch):
    from common import mock_generation

    monkeypatch.setattr(mock_generation, "fake_wait", lambda *_a, **_k: None)
    seen = []
    registry = LiveJobs({"image": live_jobs._mock_image})
    registry.subscribe(OWNER, lambda j: seen.append((j.status, j.stage)))
    job = registry.submit(
        OWNER,
        "image",
        "a fox",
        params={"settings": {"aspect": "16:9"}},
        run_async=False,
    )
    assert job.status == DONE and job.stage == len(job.stages) - 1
    assert [s for st, s in seen if st == "running"][1:] == [0, 1, 2, 3]
    data = job.public()
    assert {"stages", "stage", "started_at", "typical_seconds", "tasks"} <= set(data)
    assert data["started_at"] >= data["created_at"]


def test_story_job_shows_story_studio_tasks(monkeypatch):
    from services import story_jobs

    snap = {
        "tasks": [
            {"label": "Writing the scenario with Gemini", "status": "done"},
            {"label": "Painting scene 1", "status": "running"},
            {"label": "Painting scene 2", "status": "queued"},
        ]
    }
    monkeypatch.setattr(story_jobs, "job_snapshot", lambda _id, _owner: snap)
    job = LiveJob(
        id="s",
        owner=OWNER,
        kind="story",
        handle="story 1",
        prompt="p",
        params={"story_job_id": "abc"},
    )
    data = job.public()
    assert data["tasks"][1] == {"label": "Painting scene 1", "status": "running"}
    assert data["stage"] == 1 and len(data["stages"]) == 3


# ---------------------------------------------------------------- runners


@pytest.fixture
def no_library(monkeypatch):
    from common import metadata, utils

    saved = []
    monkeypatch.setattr(metadata, "add_media_item_to_firestore", saved.append)
    monkeypatch.setattr(utils, "create_display_url", lambda uri: f"https://x/{uri}")
    return saved


def test_image_runner_passes_every_setting(monkeypatch, no_library):
    from common import brand_kit
    from models import gemini

    calls = {}

    def fake(**kw):
        calls.update(kw)
        return ["gs://b/1.png"], 1.0, [""], None, []

    monkeypatch.setattr(gemini, "generate_image_from_prompt_and_images", fake)
    monkeypatch.setattr(brand_kit, "load", lambda _o: {"name": "Acme"})
    monkeypatch.setattr(brand_kit, "prompt_line", lambda _k: "Brand: Acme.")
    job = LiveJob(
        id="i",
        owner=OWNER,
        kind="image",
        handle="image 1",
        prompt="a fox",
        aspect_ratio="16:9",
        params={
            "settings": {
                "model": "gemini-3-pro-image",
                "size": "4K",
                "brand": "on",
                "search": "on",
            },
            "inputs": {"references": [{"uri": "gs://b/ref.png"}]},
        },
    )
    job.stages, _ = live_jobs.plan_stages(job)
    live_jobs._real_image(job)
    assert calls["model_name"] == "gemini-3-pro-image" and calls["image_size"] == "4K"
    assert calls["use_search"] is True and calls["images"] == ["gs://b/ref.png"]
    assert calls["aspect_ratio"] == "16:9" and "Brand: Acme." in calls["prompt"]
    assert calls["thinking_level"] is None  # 3 Pro has no thinking setting
    assert job.stage == 3


def test_music_runner_uses_lyrics_count_and_image(monkeypatch, no_library):
    from models import lyria

    calls = {}

    def fake(**kw):
        calls.update(kw)
        return ["gs://b/1.wav"], None, []

    monkeypatch.setattr(lyria, "generate_music_with_lyria", fake)
    job = LiveJob(
        id="m",
        owner=OWNER,
        kind="music",
        handle="music 1",
        prompt="a sea shanty",
        params={
            "settings": {"lyrics": "on", "lyrics_text": "Heave ho"},
            "inputs": {"image": [{"uri": "gs://b/cover.jpg"}]},
        },
    )
    live_jobs._real_music(job)
    assert (
        calls["model_name"] == "lyria-3-pro-preview" and calls["lyrics"] == "Heave ho"
    )
    assert calls["image_gcs_uri"] == "gs://b/cover.jpg"
    assert calls["image_mime_type"] == "image/jpeg"
    two = LiveJob(
        id="m2",
        owner=OWNER,
        kind="music",
        handle="music 2",
        prompt="lo-fi",
        params={"settings": {"model": "lyria-002", "count": "3"}},
    )
    live_jobs._real_music(two)
    assert calls["sample_count"] == 3 and calls["lyrics"] is None


def test_voice_request_uses_engine_dialogue_and_pronunciations():
    from config.voice import CHIRP_ENGINE

    job = LiveJob(
        id="v",
        owner=OWNER,
        kind="voice",
        handle="voice 1",
        prompt="Host: Hi.\nGuest: Hello.",
        params={
            "settings": {
                "dialogue": "on",
                "speaker_a": "Host",
                "speaker_b": "Guest",
                "voice_b": "Puck",
                "direction": "Excited",
            }
        },
    )
    request = live_jobs._voice_request(job)
    assert request.multi_speaker and request.speakers == [
        ("Host", "Kore"),
        ("Guest", "Puck"),
    ]
    assert request.style_notes == "Excited"
    chirp = LiveJob(
        id="c",
        owner=OWNER,
        kind="voice",
        handle="voice 2",
        prompt="Say GenMedia.",
        params={
            "settings": {
                "model": CHIRP_ENGINE,
                "pronunciations": "GenMedia=jen media\nbad",
            }
        },
    )
    request = live_jobs._voice_request(chirp)
    assert request.engine == CHIRP_ENGINE
    assert request.pronunciations == [
        {"phrase": "GenMedia", "pronunciation": "jen media"}
    ]


def test_omni_runner_builds_the_mode_request(monkeypatch, no_library):
    from models import omni

    seen = {}

    def fake(request):
        seen["r"] = request
        return "gs://b/out.mp4", "iid"

    monkeypatch.setattr(omni, "generate_omni_video", fake)
    job = LiveJob(
        id="o",
        owner=OWNER,
        kind="video",
        handle="video 1",
        prompt="make it night",
        params={
            "settings": {"mode": "edit"},
            "inputs": {"video": [{"uri": "gs://b/in.mp4"}]},
        },
    )
    live_jobs._real_video(job)
    assert (
        seen["r"].omni_mode == "edit"
        and seen["r"].reference_video_gcs == "gs://b/in.mp4"
    )
    missing = LiveJob(
        id="o2",
        owner=OWNER,
        kind="video",
        handle="video 2",
        prompt="x",
        params={"settings": {"mode": "extend"}},
    )
    with pytest.raises(ValueError):
        live_jobs._real_video(missing)


# ------------------------------------------------------- make with inputs


def instant():
    def run(job):
        ext = {"video": "mp4"}.get(job.kind, "png")
        return RunResult(
            f"gs://b/{job.id}.{ext}", f"https://example.test/{job.id}.{ext}", "x/y"
        )

    return {k: run for k in ("image", "video", "music", "voice")}


@pytest.fixture
def jobs(monkeypatch):
    registry = LiveJobs(instant())
    monkeypatch.setattr(studio_chat, "get_live_jobs", lambda: registry)
    studio_chat.reset(OWNER)
    yield registry
    studio_chat.reset(OWNER)


def _png():
    import base64

    return "data:image/png;base64," + base64.b64encode(b"\x89PNG fake").decode()


def test_make_fills_input_slots_and_traces(jobs):
    store = lambda _o, _raw, mime, _d: (
        f"gs://b/up.{mime.split('/')[1]}",
        "https://x/up",
    )  # noqa: E731
    first = studio_chat.attach(OWNER, _png(), "a.png", store=store)
    last = studio_chat.attach(OWNER, _png(), "b.png", store=store)
    out = studio_chat.make(
        OWNER,
        "video",
        "dawn to dusk",
        {"mode": "interpolation"},
        jobs=jobs,
        inputs={"first_frame": [first["handle"]], "last_frame": [last["handle"]]},
    )
    job = jobs.list(OWNER)[-1]
    assert job.params["inputs"]["first_frame"][0]["uri"] == "gs://b/up.png"
    assert job.params["inputs"]["last_frame"][0]["handle"] == last["handle"]
    labels = [s["label"] for s in out["trace"]]
    assert labels[0].startswith("Picked Video · ") and labels[-1] == "Started video 1"
    assert all(s["type"] == "step" for s in out["trace"])
    with pytest.raises(ValueError):  # first + last frame without the last frame
        studio_chat.make(
            OWNER,
            "video",
            "x",
            {"mode": "interpolation"},
            jobs=jobs,
            inputs={"first_frame": [first["handle"]]},
        )
    with pytest.raises(ValueError):
        studio_chat.make(OWNER, "image", "x", jobs=jobs, inputs={"nope": ["image 1"]})


def test_video_upload_becomes_a_video_input(jobs):
    import base64

    store = lambda _o, _raw, mime, _d: ("gs://b/clip.mp4", "https://x/clip.mp4")  # noqa: E731
    data = "data:video/mp4;base64," + base64.b64encode(b"\x00\x00 ftyp").decode()
    up = studio_chat.attach(OWNER, data, "clip.mp4", store=store)
    assert up["kind"] == "video" and up["mime_type"] == "video/mp4"
    out = studio_chat.make(
        OWNER,
        "video",
        "",
        {"mode": "upscale", "resolution": "720p"},
        jobs=jobs,
        inputs={"video": [up["handle"]]},
    )
    job = jobs.list(OWNER)[-1]
    assert job.params["auto_prompt"] and out["job"]["kind"] == "video"
    assert job.params["inputs"]["video"][0]["uri"] == "gs://b/clip.mp4"


def test_big_video_upload_is_refused(monkeypatch):
    import base64

    monkeypatch.setattr(studio_chat, "MAX_VIDEO_UPLOAD_BYTES", 4)
    data = "data:video/mp4;base64," + base64.b64encode(b"0123456789" * 10).decode()
    with pytest.raises(ValueError, match="40 MB"):
        studio_chat.attach(OWNER, data, store=lambda *_a: ("", ""))


# ---------------------------------------------------------- chat trace


class FakeModels:
    def __init__(self, replies):
        self.replies = list(replies)

    def generate_content(self, model, contents, config):
        return SimpleNamespace(
            candidates=[SimpleNamespace(content=self.replies.pop(0))]
        )


def _call(name, **args):
    return types.Content(
        role="model",
        parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))],
    )


def _text(value):
    return types.Content(role="model", parts=[types.Part.from_text(text=value)])


def test_send_returns_a_trace(jobs):
    models = FakeModels(
        [
            _call(
                "generate_image", prompt="a red fox, golden hour", aspect_ratio="16:9"
            ),
            _text("Making image 1."),
        ]
    )
    steps = []
    out = studio_chat.send(
        OWNER,
        "a fox in snow, 16:9",
        (SimpleNamespace(models=models), "m"),
        steps.append,
    )
    labels = [s["label"] for s in out["trace"]]
    assert labels[0] == "Reading your message"
    assert "Found settings in your message" in labels
    assert any(
        lbl.startswith("Picked Image · ") and lbl.endswith("16:9") for lbl in labels
    )
    prompt_step = next(s for s in out["trace"] if s["label"] == "Wrote the prompt")
    assert prompt_step["detail"] == "a red fox, golden hour"
    assert labels[-1] == "Started image 1" and steps == out["trace"]


def test_chat_route_streams_ndjson(monkeypatch, jobs):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import chat_router

    models = FakeModels(
        [_call("generate_music", prompt="calm piano"), _text("Making music 1.")]
    )
    monkeypatch.setattr(
        studio_chat, "_default_client", lambda: (SimpleNamespace(models=models), "m")
    )
    app = FastAPI()
    app.include_router(chat_router.router)
    client = TestClient(app)
    res = client.post("/api/chat", json={"message": "calm piano music", "stream": True})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(line) for line in res.text.splitlines() if line.strip()]
    assert lines[0] == {
        "type": "step",
        "label": "Reading your message",
        "detail": "Gemini · m",
    }
    assert lines[-1]["type"] == "done" and lines[-1]["reply"] == "Making music 1."
    assert [j["handle"] for j in lines[-1]["jobs"]] == ["music 1"]
    assert lines[-1]["trace"] == lines[:-1]
    # Without stream: the same JSON as before, plus the trace.
    models.replies = [_text("Hello!")]
    plain = client.post("/api/chat", json={"message": "hi"}).json()
    assert (
        plain["reply"] == "Hello!" and plain["trace"][-1]["label"] == "Wrote the reply"
    )
    assert "inputs" in client.get("/api/chat/options").json()


def test_stream_reports_errors(monkeypatch, jobs):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import chat_router

    def boom(*_a, **_k):
        raise RuntimeError("broken")

    monkeypatch.setattr(studio_chat, "send", boom)
    app = FastAPI()
    app.include_router(chat_router.router)
    res = TestClient(app).post("/api/chat", json={"message": "x", "stream": True})
    assert json.loads(res.text.strip().splitlines()[-1]) == {
        "type": "error",
        "message": "broken",
    }


def test_film_passes_story_studio_setup(monkeypatch, jobs):
    from services import live_story

    seen = {}

    def fake(owner, idea, **kw):
        seen.update(kw, idea=idea)
        raise ValueError("stop here")

    monkeypatch.setattr(live_story, "create_story_record", fake)
    script = "NARRATOR: The sea was calm that morning, and the lighthouse slept."
    with pytest.raises(ValueError, match="stop here"):
        studio_chat.make(
            OWNER,
            "film",
            script,
            {
                "length": "120",
                "source": "script",
                "engine": "3.1",
                "pacing": "dynamic",
                "speech": "narrator",
                "camera": "orbit",
            },
            jobs=jobs,
        )
    assert seen["length"] == "120" and seen["script"] == script
    assert seen["video_model"] == "3.1" and seen["pacing"] == "dynamic"
    assert seen["speech_mode"] == "narrator" and seen["camera"] == "orbit"
    with pytest.raises(ValueError):
        studio_chat.make(
            OWNER,
            "film",
            "A fox explores a forest at dusk",
            {"scenes": "5", "scene_length": "8"},
            jobs=jobs,
        )
    assert seen["scene_count"] == 5 and seen["scene_seconds"] == 8


def test_story_record_takes_the_setup(tmp_path):
    from services import live_story, story_store

    story_store.set_store(story_store.LocalStoryStore(str(tmp_path / "s.json")))
    try:
        story = live_story.create_story_record(
            OWNER,
            "",
            speech_mode="on_camera",
            camera="orbit",
            pacing="dynamic",
            scene_count=5,
            scene_seconds=8,
            script="HOST: Welcome to the coast. Today we follow the tide.",
        )
        assert story.input_mode == "script" and story.raw_script.startswith("HOST:")
        assert story.speech_mode == "on_camera" and story.camera == "orbit"
        assert story.pacing == "dynamic" and story.scene_count == 5
    finally:
        story_store.set_store(None)
