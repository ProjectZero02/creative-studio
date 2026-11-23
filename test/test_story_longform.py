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
"""Story Studio v3 tests: long-form director, script-to-film, dual engine, mastering."""

from __future__ import annotations

import json
import math
import os
import wave

import numpy as np
import pytest

from config.default import Default
from models import omni as omni_mod
from services import (
    live_story,
    story_director,
    story_fix,
    story_jobs,
    story_models,
    story_service,
    story_store,
    story_timeline,
)
from services.story_models import (
    Scene,
    Segment,
    StitchPlan,
    Story,
    build_stitch_plan,
    parse_scenario,
    split_narration_parts,
)

OWNER = "director@example.com"


# ---------------------------------------------------------------------------
# Config & Blueprint Planning
# ---------------------------------------------------------------------------


def test_longform_config_defaults():
    fields = Default.__dataclass_fields__
    assert fields["STORY_MAX_SCENES"].default == 120
    assert fields["STORY_MAX_FILM_SECONDS"].default == 900
    assert fields["STORY_SEQUENCE_THRESHOLD_SCENES"].default == 10
    assert fields["STORY_AUDIO_OVERLAP_SECONDS"].default == pytest.approx(0.18)
    assert fields["STORY_MUSIC_LOOP_CROSSFADE"].default == pytest.approx(2.5)
    assert fields["STORY_COLOR_MATCH"].default is True


@pytest.mark.parametrize("target_secs", [300, 600])
@pytest.mark.parametrize("pacing", ["dynamic", "cinematic", "documentary"])
def test_plan_film_blueprint_multi_minute(target_secs, pacing):
    bp = story_director.plan_film_blueprint(
        target_secs, pacing=pacing, video_model="gemini-omni-1.2-flash"
    )
    assert bp["sequence_count"] >= 2
    assert bp["scene_count"] > 10
    assert sum(bp["shots_per_sequence"]) == bp["scene_count"]
    assert bp["estimated_seconds"] == bp["scene_count"] * bp["duration"]
    assert abs(bp["estimated_seconds"] - target_secs) <= bp["duration"] * 2


# ---------------------------------------------------------------------------
# Script-to-Film Deterministic Parser
# ---------------------------------------------------------------------------


def test_parse_user_script_screenplay_and_thirty_degree_rule():
    script = """Title: Harbour Dawn
INT. HARBOUR OFFICE - DAWN
[Visual: Warm lantern glow over nautical charts on an oak desk.]
MARA: We sail before the tide turns. Check the brass barometer twice.
[Visual: Close on Mara's steady hand resting on the barometer dial.]
MARA: If the fog lifts early, signal the outer pier.
NARRATOR (V.O.): Outside, the water lay like hammered silver against the pilings.
EXT. OUTER PIER - MORNING
[Visual: Wide view of the wooden pier stretching into the mist.]
"""
    parsed = story_director.parse_user_script(
        script, language="English", speech_mode="auto", pacing="cinematic"
    )
    assert parsed["title"] == "Harbour Dawn"
    assert len(parsed["sequences"]) == 2
    assert len(parsed["locations"]) == 2
    assert any(c["name"] == "Mara" for c in parsed["characters"])

    scenes = parsed["scenes"]
    assert len(scenes) >= 4
    spoken_scenes = [s for s in scenes if s["spoken"]]
    vo_scenes = [s for s in scenes if not s["spoken"]]
    assert len(spoken_scenes) >= 2
    assert any("hammered silver" in s["narration"] for s in vo_scenes)

    # 30-degree rule: consecutive same-location cuts never repeat shot_size.
    for prev, cur in zip(scenes, scenes[1:], strict=False):
        if prev["location"] and prev["location"] == cur["location"] and cur["transition"] == "cut":
            assert prev["shot_size"] != cur["shot_size"]


def test_parse_user_script_voiceover_paragraphs_split_cleanly():
    para1 = " ".join(["Morning light spills across the valley floor."] * 5)
    para2 = " ".join(["A quiet river winds between pine ridges toward the coast."] * 5)
    parsed = story_director.parse_user_script(
        f"{para1}\n\n{para2}",
        language="English",
        speech_mode="narrator",
        pacing="cinematic",
    )
    assert len(parsed["sequences"]) == 2
    assert len(parsed["scenes"]) >= 4
    for sc in parsed["scenes"]:
        assert sc["spoken"] is False
        assert 4 <= sc["seconds"] <= 15


# ---------------------------------------------------------------------------
# Hierarchical Two-Stage Scenario Generation & Smart Mock Backend
# ---------------------------------------------------------------------------


def test_vertex_hierarchical_scenario_for_five_minute_film(monkeypatch):
    backend = story_service.VertexStoryBackend()
    calls: list[tuple[str, str]] = []

    def fake_json_text(
        prompt: str,
        temperature: float | None = None,
        task: str = "story_scenario",
        model: str = "",
        media: list[str] | None = None,
        schema: dict | None = None,
        system: str = "",
        thinking: bool = False,
    ) -> str:
        calls.append((task, prompt))
        if task == "story_outline":
            return json.dumps(
                {
                    "title": "The Deep Meridian",
                    "brief": "An oceanographer charts an uncharted trench over one tense expedition.",
                    "visual_grammar": "35mm anamorphic lens, cool cyan shadows and amber instruments.",
                    "voice": "Warm documentary narrator",
                    "characters": [
                        {
                            "key": "c1",
                            "name": "Elena",
                            "description": "woman in her late 30s, everyday field researcher",
                            "outfit": "navy waterproof parka",
                            "voice": {
                                "tts_voice": "Kore",
                                "style": "calm, clear",
                                "description": "female voice, late 30s",
                            },
                        }
                    ],
                    "locations": [
                        {
                            "key": "l1",
                            "name": "Research Bridge",
                            "description": "compact ship bridge with sonar displays",
                            "time_of_day": "night",
                        }
                    ],
                    "props": [],
                    "sequences": [
                        {
                            "key": f"seq{i + 1}",
                            "title": f"Sequence {i + 1}",
                            "summary": f"Act beat {i + 1}",
                            "location": "l1",
                            "cast": ["c1"],
                            "target_seconds": 60,
                            "shot_count": 7 if i < 4 else 10,
                        }
                        for i in range(5)
                    ],
                }
            )
        # Stage 2 sequence expansion
        assert task == "story_sequence_shots"
        import re

        m = re.search(r"into exactly (\d+) shots", prompt)
        count = int(m.group(1)) if m else 7
        return json.dumps(
            {
                "scenes": [
                    {
                        "visual": f"Elena checks sonar display in shot {k + 1}.",
                        "motion_prompt": "Slow dolly in as sonar sweeps the screen.",
                        "audio_cue": "Low engine hum and sonar pings.",
                        "shot_size": "medium" if k % 2 == 0 else "close_up",
                        "camera": "dolly_in",
                        "spoken": False,
                        "narration": f"Depth gauge climbs past marker {k + 1}.",
                        "seconds": 8,
                        "transition": "cut",
                        "cast": ["c1"],
                        "location": "l1",
                        "props": [],
                        "speaker": "",
                    }
                    for k in range(count)
                ]
            }
        )

    monkeypatch.setattr(backend, "_json_text", fake_json_text)
    story = Story(
        idea="An oceanographer maps a glowing deep sea trench.",
        scene_count=38,
        duration=8,
        target_seconds=300,
        pacing="cinematic",
    )
    raw = backend.write_scenario(story)
    outline_calls = [c for c in calls if c[0] == "story_outline"]
    seq_calls = [c for c in calls if c[0] == "story_sequence_shots"]
    assert len(outline_calls) == 1
    assert len(seq_calls) == 5

    title, scenes = parse_scenario(raw, 38, 8)
    assert title == "The Deep Meridian"
    assert len(scenes) == 38
    assert scenes[0].sequence == "seq1"
    assert scenes[0].motion_prompt
    assert scenes[0].audio_cue
    assert story_models.parse_visual_grammar(raw)
    assert story_models.parse_sequences(raw)


def test_mock_backend_write_scenario_idea_and_script(tmp_path, monkeypatch):
    monkeypatch.setattr(story_service, "LOCAL_MEDIA_DIR", str(tmp_path))
    backend = story_service.MockStoryBackend(speed=0)

    idea_story = Story(
        idea="A man presenting Gemini Enterprise on a conference stage to developers",
        scene_count=4,
        duration=6,
    )
    raw_idea = backend.write_scenario(idea_story)
    title, scenes = parse_scenario(raw_idea, 4, 6)
    assert len(scenes) == 4
    # Trailing articles/prepositions stripped cleanly from mock titles.
    assert title.split()[-1].lower() not in {"a", "an", "the", "on", "in", "with"}
    joined_visuals = " ".join(s.visual.lower() for s in scenes)
    assert "misty harbour" not in joined_visuals

    script_story = Story(
        idea="",
        input_mode="script",
        raw_script="Title: Demo Cut\nINT. STUDIO - DAY\nALEX: Welcome to the live build.",
        scene_count=3,
        duration=6,
    )
    raw_script = backend.write_scenario(script_story)
    stitle, sscenes = parse_scenario(raw_script, 1, 6)
    assert stitle == "Demo Cut"
    assert len(sscenes) >= 1
    assert sscenes[0].spoken is True


# ---------------------------------------------------------------------------
# Keyframe Bridging & Protected Timeline Boundaries
# ---------------------------------------------------------------------------


def test_clip_inputs_first_last_bridge():
    story = Story(idea="Test bridge", style="photographic")
    scene = Scene(narration="", visual="Harbour pier", duration=6, transition="bridge")
    got = story_service.clip_inputs(
        story,
        scene,
        "gs://b/frame1.jpg",
        end_frame_uri="gs://b/frame2.jpg",
    )
    assert got["omni_mode"] == "first_last"
    assert got["reference_image_gcs"] == "gs://b/frame1.jpg"
    assert got["last_reference_image_gcs"] == "gs://b/frame2.jpg"


def test_build_stitch_plan_and_timeline_protect_bridge_boundaries():
    scenes = [
        Scene(
            id="s1",
            narration="",
            visual="Shot 1",
            duration=6,
            frame_uri="gs://b/f1.jpg",
            clip_uri="gs://b/c1.mp4",
            bridged_to="gs://b/f2.jpg",
            transition="cut",
        ),
        Scene(
            id="s2",
            narration="",
            visual="Shot 2",
            duration=6,
            frame_uri="gs://b/f2.jpg",
            clip_uri="gs://b/c2.mp4",
            transition="bridge",
        ),
        Scene(
            id="s3",
            narration="",
            visual="Shot 3",
            duration=6,
            frame_uri="gs://b/f3.jpg",
            clip_uri="gs://b/c3.mp4",
            transition="cut",
        ),
    ]
    plan = build_stitch_plan(scenes, crossfade=0.5, seamless=True, fps=24)
    assert len(plan.segments) == 3
    assert plan.segments[1].join == "bridge"
    assert plan.segments[1].fade_in == 0.0
    assert plan.segments[1].trim_head == pytest.approx(round(1 / 24, 4))

    tl = story_timeline.build_timeline(
        Story(idea="Bridge test"),
        plan,
        width=1280,
        height=720,
        fps=24,
        clip_lengths={0: 6.0, 1: 6.0, 2: 6.0},
        clip_stills={
            0: (0.4, 0.9),  # outgoing to bridge -> tail MUST NOT be trimmed
            1: (0.6, 0.5),  # entering via bridge -> head MUST stay trim_head (1/24)
            2: (0.4, 0.3),  # plain cut -> still head/tail trimmed
        },
    )
    vclips = story_timeline.track(tl, "video")["clips"]
    # Clip 0 exits into bridge: out stays full 6.0 (not 5.1)
    assert vclips[0]["out"] == pytest.approx(6.0)
    # Clip 1 enters via bridge: in stays 0.042 (not 0.6)
    assert vclips[1]["in"] == pytest.approx(round(1 / 24, 3))
    # Clip 2 is plain cut: still head 0.4 trimmed
    assert vclips[2]["in"] == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# Dual-Engine Video Routing (Omni 1.2 + Veo 3.1 + Hybrid)
# ---------------------------------------------------------------------------


def test_dual_engine_routing_and_veo_clip_generation(monkeypatch):
    story_hybrid = Story(idea="Hybrid", video_model="hybrid")
    spoken_scene = Scene(narration="Hello world.", spoken=True, duration=6)
    long_broll = Scene(narration="Slow pan.", spoken=False, duration=12)
    short_broll = Scene(narration="Quick cut.", spoken=False, duration=6)

    assert story_service.resolve_video_engine(story_hybrid, spoken_scene) == "gemini-omni-1.2-flash"
    assert story_service.resolve_video_engine(story_hybrid, long_broll) == "gemini-omni-1.2-flash"
    assert story_service.resolve_video_engine(story_hybrid, short_broll) == "3.1-fast"
    assert story_service.resolve_video_engine(Story(video_model="3.1"), short_broll) == "3.1"

    captured: list = []

    def fake_generate_video(req):
        captured.append(req)
        return ["gs://bucket/veo_clip.mp4"], None

    import models.veo as veo_mod

    monkeypatch.setattr(veo_mod, "generate_video", fake_generate_video)
    backend = story_service.VertexStoryBackend()
    story = Story(
        idea="Veo test",
        video_model="3.1-fast",
        scenes=[
            Scene(
                id="a",
                narration="Wide view.",
                visual="Lighthouse at dusk",
                motion_prompt="Slow dolly in",
                duration=6,
                frame_uri="gs://b/f1.jpg",
            )
        ],
    )
    # 1) i2v
    uri1 = backend.generate_clip(story, 0, "gs://b/f1.jpg")
    assert uri1 == "gs://bucket/veo_clip.mp4"
    assert captured[0].model_version_id == "3.1-fast"
    assert captured[0].reference_image_gcs == "gs://b/f1.jpg"
    assert captured[0].last_reference_image_gcs is None

    # 2) interpolation (bridge first+last)
    uri2 = backend.generate_clip(story, 0, "gs://b/f1.jpg", end_frame_uri="gs://b/f2.jpg")
    assert uri2 == "gs://bucket/veo_clip.mp4"
    assert captured[1].reference_image_gcs == "gs://b/f1.jpg"
    assert captured[1].last_reference_image_gcs == "gs://b/f2.jpg"
    assert "ending frame" in captured[1].prompt.lower()


# ---------------------------------------------------------------------------
# Multi-Turn Dialogue Split & Bounded Omni History
# ---------------------------------------------------------------------------


def test_split_narration_parts_and_extend_take_turn_frame():
    text = (
        "First we open the harbour gates before sunrise. "
        "Next the crew checks every rope and lantern. "
        "Finally the vessel glides into calm open water."
    )
    parts = split_narration_parts(text, [15, 8, 7])
    assert len(parts) == 3
    assert all(p.strip() for p in parts)
    assert " ".join(parts) == text

    scenes = [
        Scene(id="1", narration="One.", spoken=True, duration=6, frame_uri="gs://b/f1.jpg"),
        Scene(
            id="2",
            narration="Two.",
            spoken=True,
            duration=6,
            frame_uri="gs://b/f2.jpg",
            transition="extend",
        ),
        Scene(
            id="3",
            narration="Three.",
            spoken=True,
            duration=6,
            frame_uri="gs://b/f3.jpg",
            transition="auto",
        ),
    ]
    story = Story(idea="Extend", continuous_takes=True, scenes=scenes)
    assert story_service.take_turn_frame(story, 1, first=False) == ""
    assert story_service.take_turn_frame(story, 2, first=False) == "gs://b/f3.jpg"


def test_omni_resolve_gcs_uris_caps_inline_videos(monkeypatch):
    downloaded: list[str] = []

    def fake_dl(uri: str) -> bytes:
        downloaded.append(uri)
        return b"video-bytes"

    monkeypatch.setattr(omni_mod, "download_from_gcs", fake_dl)
    history = []
    for k in range(5):
        history.append({"type": "user_input", "content": [{"type": "text", "text": f"Turn {k}"}]})
        history.append(
            {
                "type": "model_output",
                "content": [{"type": "video", "gcs_uri": f"gs://b/clip_{k}.mp4", "mime_type": "video/mp4"}],
            }
        )

    resolved = omni_mod._resolve_gcs_uris_in_history(history, max_inline_videos=2)
    assert downloaded == ["gs://b/clip_3.mp4", "gs://b/clip_4.mp4"]
    omitted_turns = [
        step["content"][0]
        for step in resolved
        if step["type"] == "model_output" and step["content"][0]["type"] == "text"
    ]
    assert len(omitted_turns) == 3
    assert "omitted" in omitted_turns[0]["text"].lower()


# ---------------------------------------------------------------------------
# Audio/Video Mastering: Narrator Tempo, J/L Cuts, Fade-Black, Music Loop
# ---------------------------------------------------------------------------


def test_timeline_narrator_auto_tempo_and_render_args():
    plan = StitchPlan(
        segments=[
            Segment(index=0, clip_uri="gs://b/c1.mp4", start=0.0, duration=8.0, trim_head=0.0, fade_in=0.0, spoken=False, join="cut"),
            Segment(index=1, clip_uri="gs://b/c2.mp4", start=7.5, duration=8.0, trim_head=0.0, fade_in=0.5, spoken=False, join="fade_black"),
        ],
        crossfade=0.5,
        total=15.5,
    )
    tl = story_timeline.build_timeline(
        Story(idea="Master", color_match=False),
        plan,
        width=1280,
        height=720,
        fps=24,
        clip_lengths={0: 8.5, 1: 8.0},
        voice_uris={0: "gs://b/v1.wav"},
        voice_lengths={0: 8.5},  # slightly longer than 7.7s room (<1.18x)
        music_uri="gs://b/music.wav",
        music_length=30.0,
    )
    v0 = story_timeline.track(tl, "voice")["clips"][0]
    assert v0["out"] == pytest.approx(8.5)
    assert 1.0 < v0["tempo"] <= 1.18

    # Check ffmpeg filter graph for qsin curves, fade_black, and L-cut ambient overlap
    vclips = story_timeline.track(tl, "video")["clips"]
    vclips[0]["src_max"] = 9.0
    args = story_timeline.render_args(
        tl,
        paths={
            "gs://b/c1.mp4": "/tmp/c1.mp4",
            "gs://b/c2.mp4": "/tmp/c2.mp4",
            "gs://b/v1.wav": "/tmp/v1.wav",
            "gs://b/music.wav": "/tmp/music.wav",
        },
        has_audio={
            "gs://b/c1.mp4": True,
            "gs://b/c2.mp4": True,
            "gs://b/v1.wav": True,
            "gs://b/music.wav": True,
        },
        overlays={},
        out_path="/tmp/out.mp4",
    )
    graph = args[args.index("-filter_complex") + 1]
    assert "curve=qsin" in graph
    assert "fade=t=out:" in graph
    assert "fade=t=in:" in graph
    # L-cut overlap extended ambient audio past clip 0 out (8.5 -> 8.66)
    assert "end=8.66" in graph


def test_loop_audio_crossfade_produces_click_free_wav(tmp_path):
    src_wav = str(tmp_path / "loop_src.wav")
    out_wav = str(tmp_path / "loop_out.wav")
    sr = 24000
    t = np.arange(sr * 3) / sr
    # Smooth 220 Hz sine tone with non-zero boundary amplitude
    tone = (0.3 * np.sin(2 * math.pi * 220.0 * t)).astype(np.float32)
    pcm = (np.clip(tone, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(src_wav, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())

    got = story_timeline.loop_audio_crossfade(src_wav, 10.0, out_wav, crossfade_s=0.8)
    assert got == out_wav
    assert os.path.exists(out_wav)
    with wave.open(out_wav, "rb") as wf:
        assert wf.getnchannels() == 2
        assert wf.getframerate() == 48000
        frames = wf.getnframes()
        assert 9.9 <= frames / 48000 <= 10.1
        arr = np.frombuffer(wf.readframes(frames), dtype="<i2").astype(np.float32)
        assert not np.isnan(arr).any()


def test_story_fix_transition_timeline_op():
    tl = story_timeline.empty_timeline()
    tl["tracks"][0]["clips"] = [
        {"id": "a", "src": "gs://b/1.mp4", "start": 0.0, "in": 0.0, "out": 6.0, "gain": 1.0, "fade_in": 0.0, "join": "cut", "scene": 0},
        {"id": "b", "src": "gs://b/2.mp4", "start": 6.0, "in": 0.0, "out": 6.0, "gain": 1.0, "fade_in": 0.0, "join": "cut", "scene": 1},
    ]
    story = Story(
        idea="Fix transition",
        scenes=[
            Scene(id="s1", narration="One", duration=6, clip_uri="gs://b/1.mp4"),
            Scene(id="s2", narration="Two", duration=6, clip_uri="gs://b/2.mp4"),
        ],
        timeline_json=json.dumps(tl),
    )
    plan = story_fix.parse_fix_plan(
        json.dumps(
            {
                "action": "timeline",
                "summary": "Dip to black into scene 2.",
                "timeline": [{"op": "transition", "scene": 2, "join": "fade_black"}],
            }
        ),
        story,
    )
    assert plan.changes and plan.changes[0].timeline
    updated = story_fix.apply_timeline_ops(tl, plan.changes[0].timeline)
    clip2 = story_timeline.track(updated, "video")["clips"][1]
    assert clip2["join"] == "fade_black"
    assert clip2["fade_in"] > 0


# ---------------------------------------------------------------------------
# Job Controls, End-to-End Mock Film & Live Story Multi-Minute Integration
# ---------------------------------------------------------------------------


def test_start_scene_clips_and_cancel_job(tmp_path, monkeypatch):
    store = story_store.LocalStoryStore(str(tmp_path / "stories.json"))
    monkeypatch.setattr(story_service, "LOCAL_MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setattr(story_jobs, "get_store", lambda: store)
    monkeypatch.setattr(
        story_jobs, "get_backend", lambda: story_service.MockStoryBackend(speed=0)
    )
    story = store.save(
        Story(
            idea="Shot job test",
            scenes=[
                Scene(id="s1", narration="One", visual="V1", duration=4, frame_uri="local://f1.jpg"),
                Scene(id="s2", narration="Two", visual="V2", duration=4, frame_uri="local://f2.jpg"),
                Scene(id="s3", narration="Three", visual="V3", duration=4, frame_uri="local://f3.jpg"),
            ],
        ),
        OWNER,
    )
    # Create dummy frame files on disk
    for k in (1, 2, 3):
        p = story_service.local_path(f"local://f{k}.jpg")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        from PIL import Image

        Image.new("RGB", (320, 180), (40 * k, 80, 120)).save(p, "JPEG")

    job = story_jobs.wait(
        story_jobs.start_scene_clips(story.id, OWNER, [1]).id, OWNER, timeout=30
    )
    assert job is not None and job.status == story_jobs.DONE
    updated = store.get(story.id, OWNER)
    assert updated.scenes[0].clip_uri == ""
    assert updated.scenes[1].clip_uri != ""
    assert updated.scenes[2].clip_uri == ""

    # Cancel a slow job cleanly
    monkeypatch.setattr(
        story_jobs, "get_backend", lambda: story_service.MockStoryBackend(speed=0.4)
    )
    slow_job = story_jobs.start_storyboard(story.id, OWNER, [0, 1, 2])
    story_jobs.cancel_job(slow_job.id, OWNER)
    finished = story_jobs.wait(slow_job.id, OWNER, timeout=10)
    assert finished is not None
    assert finished.status == story_jobs.CANCELLED


def test_end_to_end_mock_film_with_mixed_transitions(tmp_path, monkeypatch):
    store = story_store.LocalStoryStore(str(tmp_path / "stories.json"))
    monkeypatch.setattr(story_service, "LOCAL_MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setattr(story_jobs, "get_store", lambda: store)
    monkeypatch.setattr(
        story_jobs, "get_backend", lambda: story_service.MockStoryBackend(speed=0)
    )
    story = store.save(
        Story(
            idea="A small sailing boat crosses a glassy fjord at sunrise",
            scene_count=3,
            duration=4,
            music_on=True,
        ),
        OWNER,
    )
    j1 = story_jobs.wait(story_jobs.start_scenario(story.id, OWNER).id, OWNER, timeout=20)
    assert j1.status == story_jobs.DONE

    def set_transitions(s: Story) -> None:
        s.scenes[1].transition = "bridge"
        s.scenes[2].transition = "dissolve"

    story_jobs.mutate_story(story.id, OWNER, set_transitions)
    j2 = story_jobs.wait(story_jobs.start_storyboard(story.id, OWNER).id, OWNER, timeout=30)
    assert j2.status == story_jobs.DONE

    j3 = story_jobs.wait(story_jobs.start_video(story.id, OWNER).id, OWNER, timeout=60)
    assert j3.status == story_jobs.DONE
    final = store.get(story.id, OWNER)
    assert final.final_uri
    assert os.path.getsize(story_service.local_path(final.final_uri)) > 1000
    assert final.timeline_json
    tl = story_timeline.normalize(final.timeline_json)
    vclips = story_timeline.track(tl, "video")["clips"]
    assert len(vclips) == 3
    assert vclips[1]["join"] == "bridge"
    assert vclips[2]["join"] == "dissolve"


def test_live_story_supports_five_minute_length(tmp_path, monkeypatch):
    store = story_store.LocalStoryStore(str(tmp_path / "stories.json"))
    monkeypatch.setattr(story_jobs, "get_store", lambda: store)
    st = live_story.create_story_record(
        OWNER,
        "A documentary about solar microgrids powering mountain villages.",
        length="5 minutes",
    )
    assert st.target_seconds == 300
    assert st.scene_count >= 20
    assert st.scene_count * st.duration >= 240
