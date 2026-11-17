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
"""Settings typed in the prompt: parse, fit to real model limits, strip."""

import pytest

from common import prompt_settings as ps
from common.prompt_settings import Applied, SettingLimits, Skipped
from config.gemini_image_models import get_gemini_image_model_config
from config.lyria_models import get_lyria_model_config
from config.video_studio_models import limits as studio_limits
from config.video_studio_models import model_display_name


def _values(text, kinds, noun="image"):
    return [(m.kind, m.value) for m in ps.parse(text, kinds, noun)]


def _video(model_id, mode="t2v", always=None):
    lim = studio_limits(model_id, mode)
    return SettingLimits.from_studio_limits(
        lim,
        model_display_name(model_id),
        always_sound=model_id.startswith("gemini-omni") if always is None else always,
    )


OMNI = "gemini-omni-1.2-flash"
OMNI_720 = "gemini-omni-flash-preview"
VEO = "3.1-fast"


def _banana():
    return SettingLimits.from_image_config(
        get_gemini_image_model_config("gemini-nano-banana-2.1"),
    )


# --- aspect ratios -----------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "a fox at 16:9",
        "a fox, 16:9",
        "16:9 a fox",
        "a fox in 16x9",
        "a fox at 16 by 9.",
        "a fox, aspect ratio 16:9",
        "a fox (16:9)",
        "make it 16:9",
        "a fox 16:9 aspect ratio",
    ],
)
def test_ratio_forms(text):
    assert _values(text, ps.IMAGE_KINDS) == [("aspect", "16:9")]


@pytest.mark.parametrize(
    "text",
    [
        "A 16:9 TV on the wall",
        "a 4x5 photo print on a desk",
        "meet me at 4:30",
        "a 2x4 plank",
        "a portrait of a woman",
        "landscape photography of hills",
    ],
)
def test_ratio_false_positives(text):
    assert _values(text, ps.IMAGE_KINDS) == []


def test_ratio_words_need_a_cue():
    assert _values("a lake, in landscape.", ps.IMAGE_KINDS) == [("aspect", "16:9")]
    assert _values("a tower in portrait format", ps.IMAGE_KINDS) == [("aspect", "9:16")]
    assert _values("logo, square format", ps.IMAGE_KINDS) == [("aspect", "1:1")]


# --- sizes and resolutions ---------------------------------------------------


def test_image_size():
    assert _values("a cat in 4K", ps.IMAGE_KINDS) == [("image_size", "4K")]
    assert _values("a cat, 2k", ps.IMAGE_KINDS) == [("image_size", "2K")]
    assert _values("a 4K TV showing a cat", ps.IMAGE_KINDS) == []


def test_resolution():
    kinds = ps.VIDEO_KINDS
    assert _values("a fox running in 1080p", kinds, "video") == [
        ("resolution", "1080p"),
    ]
    assert _values("a fox, 720p", kinds, "video") == [("resolution", "720p")]
    assert _values("a fox in 4K.", kinds, "video") == [("resolution", "4k")]
    assert _values("a fox 2160p", kinds, "video") == [("resolution", "4k")]


# --- durations ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text,value",
    [
        ("a fox, 8 seconds", 8),
        ("a fox for 8s", 8),
        ("an 8-second clip of a fox", 8),
        ("a fox, 6 sec", 6),
        ("a fox 10 seconds long", 10),
    ],
)
def test_duration_forms(text, value):
    assert _values(text, ps.VIDEO_KINDS, "video") == [("duration", value)]


@pytest.mark.parametrize(
    "text",
    ["a fox, 8", "disco in the 80s", "8 foxes", "at 10:30s"],
)
def test_duration_needs_a_unit(text):
    assert [k for k, _ in _values(text, ps.VIDEO_KINDS, "video")] == []


# --- counts ------------------------------------------------------------------


def test_counts_per_noun():
    assert _values("give me 2 images of a cat", ps.IMAGE_KINDS) == [("count", 2)]
    assert _values("three options, a cat", ps.IMAGE_KINDS) == [("count", 3)]
    assert _values("2 videos of a fox", ps.VIDEO_KINDS, "video") == [("count", 2)]
    assert _values("2 clips of a fox", ps.VIDEO_KINDS, "video") == [("count", 2)]
    assert _values("2 tracks of jazz", ps.MUSIC_KINDS, "track") == [("count", 2)]
    # Another page's noun is not a count here.
    assert _values("2 videos of a cat", ps.IMAGE_KINDS) == []
    assert _values("2 cats", ps.IMAGE_KINDS) == []


# --- audio and instrumental --------------------------------------------------


@pytest.mark.parametrize(
    "text,value",
    [
        ("a fox, Generate audio on.", True),
        ("a fox, audio on", True),
        ("a fox, with sound", True),
        ("a fox, audio off", False),
        ("a fox, no audio", False),
        ("a fox without sound.", False),
        ("a fox, silent", False),
        ("make a silent video", False),
    ],
)
def test_audio(text, value):
    assert _values(text, ps.VIDEO_KINDS, "video") == [("audio", value)]


@pytest.mark.parametrize(
    "text",
    ["a silent monk in a temple", "a forest with sound of birds", "muted colours"],
)
def test_audio_false_positives(text):
    assert _values(text, ps.VIDEO_KINDS, "video") == []


def test_instrumental():
    assert _values("lofi beat, instrumental", ps.MUSIC_KINDS, "track") == [
        ("instrumental", True),
    ]
    assert _values("jazz with no vocals", ps.MUSIC_KINDS, "track") == [
        ("instrumental", True),
    ]


def test_kinds_not_asked_for_are_ignored():
    # Voice passes no kinds: its text is spoken word for word.
    assert ps.parse("Say this slowly, 8 seconds, 16:9, no audio", set()) == []
    assert _values("a cat, 8 seconds, no audio", ps.IMAGE_KINDS) == []


# --- fitting to real model limits --------------------------------------------


def _fit(text, kinds, lim):
    return ps.fit(ps.parse(text, kinds, lim.count_noun), lim)


def test_omni_duration_snaps_with_note():
    lim = _video(OMNI)
    [r] = _fit("a fox, 20 seconds", ps.VIDEO_KINDS, lim)
    assert isinstance(r, Applied)
    assert r.value == max(lim.durations) and r.requested == 20
    assert r.note() == f"Gemini Omni 1.2 Flash goes up to {max(lim.durations)} s."


def test_omni_short_duration_snaps_up():
    [r] = _fit("a fox, 1 second", ps.VIDEO_KINDS, _video(OMNI))
    assert r.value == 3 and "starts at 3 s" in r.note()


def test_veo_discrete_durations():
    lim = _video(VEO)
    [r] = _fit("a fox, 5 seconds", ps.VIDEO_KINDS, lim)
    assert r.value in lim.durations
    if 5 not in lim.durations:
        assert "makes" in r.note()


def test_720p_only_model():
    [r] = _fit("a fox in 4K.", ps.VIDEO_KINDS, _video(OMNI_720))
    assert r.value == "720p"
    assert r.note() == "Gemini Omni Flash (Preview) makes 720p only."


def test_banana_one_image_at_a_time():
    [r] = _fit("2 images of a cat", ps.IMAGE_KINDS, _banana())
    assert r.value == 1
    assert r.note() == "Gemini Nano Banana 2.1 makes one image at a time."


def test_unsupported_aspect_is_skipped():
    [r] = _fit("a fox, 4:3", ps.VIDEO_KINDS, _video(OMNI))
    assert isinstance(r, Skipped)
    assert "can't make 4:3" in r.note()


def test_omni_sound():
    [on] = _fit("a fox, with sound", ps.VIDEO_KINDS, _video(OMNI))
    [off] = _fit("a fox, no audio", ps.VIDEO_KINDS, _video(OMNI))
    assert isinstance(on, Skipped) and on.note().endswith("always adds sound.")
    assert isinstance(off, Skipped) and off.note().endswith("can't make silent video.")


def test_veo3_audio_toggle():
    [r] = _fit("a fox, no audio", ps.VIDEO_KINDS, _video(VEO))
    assert isinstance(r, Applied) and r.value is False


def test_video_input_modes_ignore_aspect_and_length():
    lim = _video(OMNI, mode="edit")
    results = _fit("make it night, 16:9, 8 seconds", ps.VIDEO_KINDS, lim)
    assert all(isinstance(r, Skipped) and not r.note() for r in results)


def test_last_value_of_a_kind_wins():
    [r] = _fit("a fox at 16:9, no wait, 9:16", ps.VIDEO_KINDS, _video(OMNI))
    assert r.value == "9:16"


def test_lyria_limits():
    lyria2 = SettingLimits.from_lyria_config(get_lyria_model_config("2"))
    lyria3 = SettingLimits.from_lyria_config(get_lyria_model_config("3-clip-preview"))
    [r] = _fit("6 tracks of jazz", ps.MUSIC_KINDS, lyria2)
    assert r.value == 4 and "goes up to 4 tracks" in r.note()
    [r] = _fit("jazz, instrumental", ps.MUSIC_KINDS, lyria3)
    assert isinstance(r, Applied)
    [r] = _fit("jazz, instrumental", ps.MUSIC_KINDS, lyria2)
    assert isinstance(r, Skipped) and not r.note()


# --- stripping ---------------------------------------------------------------


def test_strip_keeps_the_sentence():
    text = "A fox runs through snow, 8 seconds, 16:9, Generate audio on."
    out = ps.strip(text, ps.parse(text, ps.VIDEO_KINDS, "video"))
    assert out == "A fox runs through snow."


def test_strip_small_words_around_values():
    text = "a cat at 16:9 in 4K"
    assert ps.strip(text, ps.parse(text, ps.IMAGE_KINDS)) == "a cat"
    text = "Give me 2 images of a red bike"
    assert ps.strip(text, ps.parse(text, ps.IMAGE_KINDS)) == "a red bike"
    text = "a fox for 8 seconds in the rain"
    assert (
        ps.strip(text, ps.parse(text, ps.VIDEO_KINDS, "video")) == "a fox in the rain"
    )


def test_strip_never_empties_the_prompt():
    assert ps.strip("16:9", ps.parse("16:9", ps.IMAGE_KINDS)) == "16:9"


def test_strip_keeps_instrumental():
    text = "lofi beat, instrumental"
    assert ps.strip(text, ps.parse(text, ps.MUSIC_KINDS, "track")) == text


# --- apply and undo ----------------------------------------------------------


def test_apply_reports_changes_and_notice():
    run = ps.apply(
        "a fox, 12 seconds, 16:9",
        ps.VIDEO_KINDS,
        _video(OMNI),
        current={"aspect": "9:16", "duration": 4, "resolution": "720p"},
    )
    assert run.prompt == "a fox"
    assert run.changes == {"aspect": "16:9", "duration": 12}
    assert run.previous == {"aspect": "9:16", "duration": 4}
    # Changes are listed in the order they were typed.
    assert run.notice == "From your prompt: 12 s (was 4 s), 16:9 (was 9:16)."
    previous, phrases = ps.read_undo(run.undo_json)
    assert previous == run.previous
    assert ["aspect", "16:9"] in phrases


def test_apply_no_change_no_notice():
    run = ps.apply("a fox at 16:9", ps.VIDEO_KINDS, _video(OMNI), {"aspect": "16:9"})
    assert run.changes == {} and run.notice == "" and run.undo_json == ""
    assert run.prompt == "a fox"


def test_apply_skips_undone_phrases():
    first = ps.apply("A 16:9 TV, 16:9", ps.IMAGE_KINDS, _banana(), {"aspect": "1:1"})
    _, phrases = ps.read_undo(first.undo_json)
    ignored = ps.ignored_list(ps.add_ignored("", phrases))
    again = ps.apply(
        "A 16:9 TV, 16:9",
        ps.IMAGE_KINDS,
        _banana(),
        {"aspect": "1:1"},
        ignored=ignored,
    )
    assert again.changes == {}
    assert again.prompt == "A 16:9 TV, 16:9"


def test_apply_translates_through_tr():
    def tr(key, english, **fmt):
        return "[" + key + "]" + english.format(**fmt)

    run = ps.apply("2 images of a cat", ps.IMAGE_KINDS, _banana(), {"count": 1}, tr=tr)
    assert run.notice.startswith("[settings.one_at_a_time]")


def test_read_undo_tolerates_junk():
    assert ps.read_undo("") == ({}, [])
    assert ps.read_undo("not json") == ({}, [])
    assert ps.ignored_list("nope") == []
