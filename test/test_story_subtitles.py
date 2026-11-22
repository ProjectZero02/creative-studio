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
"""Subtitled downloads: lines per language, cues, files and timelines."""

import json

import pytest

from services import story_subtitles as subs
from services.story_models import Scene, Story
from services.story_timeline import empty_timeline, normalize, text_overlay_png, track


def _story(language="English", **kw):
    story = Story(
        id="s1",
        owner="me@example.com",
        language=language,
        scenes=[
            Scene(narration="A fox wakes up in the snow.", duration=6),
            Scene(
                narration="She runs across the frozen lake, past the old mill, "
                "and up the hill where the morning light is turning gold.",
                duration=8,
                spoken=True,
            ),
        ],
        final_uri="gs://b/film.mp4",
        **kw,
    )
    tl = empty_timeline()
    track(tl, "video")["clips"] = [
        {"id": "v0", "src": "gs://b/0.mp4", "start": 0, "in": 0, "out": 6, "scene": 0},
        {"id": "v1", "src": "gs://b/1.mp4", "start": 6, "in": 0, "out": 8, "scene": 1, "fade_in": 0.5},
    ]
    track(tl, "voice")["clips"] = [
        {"id": "n0", "src": "gs://b/n0.wav", "start": 0.3, "in": 0, "out": 3.2, "scene": 0}
    ]
    track(tl, "text")["clips"] = [{"id": "t0", "text": "My title", "start": 0, "dur": 2}]
    story.timeline_json = json.dumps(normalize(tl))
    return story


def test_split_text_keeps_cues_short_and_breaks_at_sentences():
    pieces = subs.split_text(
        "One. Two words here, and then a much longer clause that keeps going "
        "well past the limit of a single subtitle line."
    )
    assert pieces[0] == "One."
    assert all(len(p) <= subs.CUE_CHARS for p in pieces)
    assert subs.split_into("a b c d e", 2) == ["a b", "c d e"]
    assert "\n" in subs.wrap("x" * 30 + " " + "y" * 30)


def test_cues_follow_the_voice_and_the_on_camera_clip():
    story = _story()
    cues = subs.cues(story, story.timeline_json, subs.known_lines(story, "en"))
    assert cues[0].start == pytest.approx(0.3) and cues[0].end <= 3.5
    assert cues[0].text == "A fox wakes up in the snow."
    # Scene 2 starts 0.5 s early (the crossfade); speech starts after it.
    later = [c for c in cues if c.start >= 5.5]
    assert later[0].start == pytest.approx(5.5 + 0.5 + 0.15)
    assert later[-1].end <= 14
    assert len(later) >= 2  # the long line is cut into several cues
    for a, b in zip(cues, cues[1:]):
        assert a.end < b.start


def test_lines_come_from_the_story_or_a_cached_translation():
    story = _story()
    assert subs.known_lines(story, "en")[0].startswith("A fox")
    assert subs.lines_for(story, "ar") is None
    story.subtitle_lines_json = subs.with_cached_lines(story, "ar", ["ثعلب", "تركض"])
    assert subs.lines_for(story, "ar") == ["ثعلب", "تركض"]
    story.scenes[0].narration = "Changed."
    assert subs.lines_for(story, "ar") is None  # translated from older text

    arabic = _story(language="Arabic")
    assert subs.known_lines(arabic, "ar") is not None
    assert subs.known_lines(arabic, "en") is None


def test_second_language_narration_counts_as_known_lines():
    story = _story(second_on=True)  # an English story's second language is Arabic
    for sc in story.scenes:
        sc.narration_alt = "نص"
    assert subs.known_lines(story, "ar") == ["نص", "نص"]


def test_srt_and_vtt_files():
    story = _story()
    cues = subs.cues(story, story.timeline_json, subs.known_lines(story, "en"))
    srt = subs.to_srt(cues)
    assert srt.startswith("1\n00:00:00,300 --> ")
    vtt = subs.to_vtt(cues)
    assert vtt.startswith("WEBVTT\n\n00:00:00.300 --> ")


def test_variant_timeline_keeps_own_titles_and_stacks_two_languages():
    story = _story(subtitle_style="boxed")
    lines = {"en": subs.known_lines(story, "en"), "ar": ["ثعلب يستيقظ", "تركض عبر البحيرة"]}
    tl = subs.variant_timeline(story, story.timeline_json, "en+ar", lines)
    clips = track(tl, "text")["clips"]
    assert clips[0]["text"] == "My title" and "sub" not in clips[0]
    subs_clips = [c for c in clips if c.get("sub")]
    assert subs_clips and all(c["style"] == "boxed" for c in subs_clips)
    assert subs_clips[0]["text"].split("\n")[0] == "ثعلب يستيقظ"  # Arabic on top
    assert subs_clips[0]["size"] < subs.SIZES["boxed"]
    # Rebuilding replaces the old captions instead of adding more.
    again = subs.variant_timeline(story, json.dumps(tl), "en", lines)
    assert len([c for c in track(again, "text")["clips"] if c.get("sub")]) == len(
        subs.cues(story, story.timeline_json, lines["en"])
    )


def test_a_subtitled_film_is_out_of_date_when_the_edit_or_style_changes():
    story = _story()
    lines = {"en": subs.known_lines(story, "en")}
    story.film_variants_json = json.dumps(
        {"en": {"uri": "gs://b/en.mp4", "key": subs.variant_key(story, "en", lines)}}
    )
    assert subs.ready_variant(story, "en") == "gs://b/en.mp4"
    assert subs.ready_variant(story, "none") == "gs://b/film.mp4"
    assert subs.ready_variant(story, "ar") == ""
    story.subtitle_style = "bold"
    assert subs.ready_variant(story, "en") == ""


def test_translation_parsing():
    assert subs.parse_translation('{"lines": ["a", ""]}', 2) == ["a", ""]
    with pytest.raises(Exception):
        subs.parse_translation('{"lines": ["a"]}', 2)
    assert "Arabic" in subs.translation_prompt(_story(), "ar")


@pytest.mark.parametrize("style", ["clean", "boxed", "bold"])
def test_caption_pngs_draw_every_style_and_arabic(tmp_path, style):
    from PIL import Image

    out = text_overlay_png(
        {"text": "ثعلب يستيقظ\nA fox wakes up", "pos": "bottom", "size": 32,
         "style": style, "sub": True},
        640, 360, str(tmp_path / "c.png"),
    )
    img = Image.open(out)
    assert img.size == (640, 360)
    assert img.getbbox() is not None  # something was drawn
    top = img.crop((0, 0, 640, 180)).getbbox()
    assert top is None  # captions sit at the bottom


def test_subtitle_job_translates_once_then_renders(monkeypatch):
    from services import story_jobs

    story = _story()
    store = {}

    class Store:
        def get(self, sid, owner):
            return store.get(sid)

        def save(self, s):
            store[s.id] = s

    store[story.id] = story
    calls = {"translate": 0}

    class Backend:
        def translate_subtitles(self, s, code):
            calls["translate"] += 1
            return ["ثعلب", "تركض"]

        def render_timeline(self, s, timeline):
            calls["timeline"] = timeline
            return "gs://b/ar.mp4"

    monkeypatch.setattr(story_jobs, "get_store", lambda: Store())
    monkeypatch.setattr(story_jobs, "get_backend", lambda: Backend())

    def mutate(sid, owner, fn):
        fn(store[sid])
        return store[sid]

    monkeypatch.setattr(story_jobs, "mutate_story", mutate)
    job = story_jobs.start_subtitled("s1", "me@example.com", "ar")
    story_jobs.wait(job.id, "me@example.com", timeout=5)
    assert job.status == story_jobs.DONE, job.message
    assert calls["translate"] == 1
    assert subs.ready_variant(store["s1"], "ar") == "gs://b/ar.mp4"
    assert any(c.get("sub") for c in track(calls["timeline"], "text")["clips"])
    with pytest.raises(Exception):
        story_jobs.start_subtitled("s1", "me@example.com", "none")


def test_subtitle_route_is_owner_scoped(monkeypatch):
    from routers.story_router import subtitle_file

    story = _story()
    assert subtitle_file(story, "en", "srt").startswith("1\n")
    assert subtitle_file(story, "ar", "srt") is None  # not translated yet
    assert subtitle_file(story, "en", "exe") is None


def test_each_caption_line_uses_a_font_for_its_script(tmp_path, monkeypatch):
    """English + Arabic: the English line must not get the Arabic-only font
    (Noto Sans Arabic has no Latin letters, so English drew as boxes)."""
    import os

    from PIL import ImageDraw

    from services import story_timeline as tl

    latin, arabic = "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/segoeui.ttf"
    if not (os.path.exists(latin) and os.path.exists(arabic)):
        pytest.skip("needs two distinct local fonts")
    monkeypatch.setattr(tl, "FONT_CANDIDATES", (latin,))
    monkeypatch.setattr(tl, "BOLD_FONT_CANDIDATES", ())
    monkeypatch.setattr(tl, "RTL_FONT_CANDIDATES", (arabic,))
    monkeypatch.setattr(tl, "RTL_BOLD_FONT_CANDIDATES", ())
    used = {}
    real = ImageDraw.ImageDraw.text

    def spy(self, xy, text, *a, **kw):
        used.setdefault(text, set()).add(kw["font"].path)
        return real(self, xy, text, *a, **kw)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", spy)
    text_overlay_png(
        {"text": "ثعلب يستيقظ\nA fox wakes up", "pos": "bottom", "size": 32,
         "style": "boxed", "sub": True},
        640, 360, str(tmp_path / "c.png"),
    )
    assert used["A fox wakes up"] == {latin}
    assert used["ثعلب يستيقظ"] == {arabic}


def test_latin_font_list_has_no_arabic_only_font():
    from services import story_timeline as tl

    for path in tl.FONT_CANDIDATES + tl.BOLD_FONT_CANDIDATES:
        assert "Arabic" not in path
