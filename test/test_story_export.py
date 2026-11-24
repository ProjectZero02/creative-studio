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
"""Story Studio v4 Phase D: preview proxy, Export menu, downloads, logo."""

import json
import os
import subprocess

import pytest
from PIL import Image

from common import brand_kit as bk
from services import story_export as ex
from services import story_jobs, story_service, story_store
from services import story_timeline as T
from services.story_models import Scene, Story


@pytest.fixture
def no_end_hold(monkeypatch):
    """These clips have a loud tone to their last frame, which a film would
    hold for a breath (story_timeline.end_hold); these tests are not about that."""
    monkeypatch.setattr(T, "end_hold", lambda *a, **k: 0.0)


OWNER = "me@example.com"
TL = T.normalize(
    {
        "width": 1280,
        "height": 720,
        "tracks": [
            {
                "kind": "video",
                "clips": [{"id": "a", "src": "a.mp4", "in": 0, "out": 4, "scene": 0}],
            },
        ],
    }
)


# -- export options -------------------------------------------------------------


def test_clean_defaults_and_bad_values():
    assert ex.clean(None, TL) == ex.defaults()
    opts = ex.clean({"short": 999, "fmt": "exe", "subs": "x", "lang": "fr"}, TL)
    assert opts == ex.defaults()


def test_clean_keeps_the_source_size_as_zero_and_audio_drops_picture_options():
    assert ex.clean({"short": 720}, TL)["short"] == 0
    assert ex.clean({"short": 1080}, TL)["short"] == 1080
    audio = ex.clean({"short": 1080, "fmt": "mp3", "subs": "burn"}, TL)
    assert (audio["short"], audio["subs"]) == (0, "none")


def test_resolution_options_mark_upscales():
    rows = {r["label"]: r["upscale"] for r in T.resolution_options(TL)}
    assert rows == {"540p": False, "720p": False, "1080p": True, "4K": True}
    odd = T.normalize({"width": 1920, "height": 1088, "tracks": []})
    assert {"short": 1088, "label": "1088p", "upscale": False} in T.resolution_options(
        odd
    )


def test_scaled_size_keeps_the_shape_and_even_sides():
    assert T.scaled_size(1280, 720, 1080) == (1920, 1080)
    assert T.scaled_size(720, 1280, 540) == (540, 960)
    assert all(v % 2 == 0 for v in T.scaled_size(1281, 721, 541))


def test_key_label_and_file_name():
    opts = ex.clean({"short": 1080, "subs": "burn", "lang": "en+ar"}, TL)
    assert ex.key(opts) == "mp4-1080-b-sub-en-ar"
    assert ex.label(opts, TL) == "1080p · MP4 (H.264) · english + arabic subtitles"
    assert (
        ex.filename("Light/house: *1*", opts, TL) == "Lighthouse 1 (1080p, en-ar).mp4"
    )
    mp3 = ex.clean({"fmt": "mp3"}, TL)
    assert ex.filename("Light", mp3, TL) == "Light.mp3"
    assert ex.label(mp3, TL) == "Audio · MP3"


def test_only_a_plain_mp4_at_source_size_is_the_film():
    assert ex.makes_film(ex.clean({}, TL), has_logo=True)
    assert not ex.makes_film(ex.clean({"fmt": "webm"}, TL), has_logo=True)
    assert not ex.makes_film(ex.clean({"short": 1080}, TL), has_logo=True)
    assert not ex.makes_film(ex.clean({"subs": "burn"}, TL), has_logo=True)
    assert ex.makes_film(ex.clean({"subs": "srt"}, TL), has_logo=True)
    assert not ex.makes_film(ex.clean({"branding": False}, TL), has_logo=True)
    assert ex.makes_film(ex.clean({"branding": False}, TL), has_logo=False)


def test_exports_keep_the_newest_and_go_stale_with_the_edit():
    story = Story(timeline_json=json.dumps(TL))
    opts = ex.clean({"fmt": "wav"}, TL)
    story.exports_json = ex.with_export(
        story, opts, "local://x.wav", "x.wav", ex.made_from(story, opts)
    )
    assert ex.ready(story, opts)["uri"] == "local://x.wav"
    tl = json.loads(story.timeline_json)
    T.track(tl, "text")["clips"].append({"text": "Hi", "start": 0, "dur": 1})
    story.timeline_json = json.dumps(tl)
    assert ex.ready(story, opts) is None
    for i in range(ex.MAX_EXPORTS + 3):
        story.exports_json = ex.with_export(
            story,
            ex.clean(
                {"short": 540 if i % 2 else 0, "fmt": ["mp4", "mov", "webm"][i % 3]}, TL
            ),
            f"u{i}",
            "n",
            "t",
        )
    assert len(ex.exports(story)) <= ex.MAX_EXPORTS


# -- render arguments -------------------------------------------------------------


def _args(fmt, **kw):
    return T.render_args(
        TL, {"a.mp4": "a.mp4"}, {"a.mp4": True}, {}, f"out.{fmt}", fmt=fmt, **kw
    )


def test_audio_only_renders_no_picture():
    args = _args("mp3")
    graph = args[args.index("-filter_complex") + 1]
    assert "[vout]" not in args and "[vout]" not in graph and "libmp3lame" in args
    assert "pcm_s16le" in _args("wav")


def test_audio_only_without_sound_is_silence():
    args = T.render_args(
        TL, {"a.mp4": "a.mp4"}, {"a.mp4": False}, {}, "out.wav", fmt="wav"
    )
    assert "anullsrc" in args[args.index("-filter_complex") + 1]


def test_formats_and_quality():
    webm = _args("webm")
    assert "libvpx-vp9" in webm and "libopus" in webm
    mov = _args("mov")
    assert mov[mov.index("-f") + 1] == "mov" and "libx264" in mov
    proxy = _args("mp4", preset=T.PROXY_PRESET, crf=T.PROXY_CRF)
    assert (
        proxy[proxy.index("-crf") + 1] == "30"
        and proxy[proxy.index("-preset") + 1] == "ultrafast"
    )


def _clip(path, seconds=2.0, size="320x180"):
    from services.story_timeline import _ffmpeg

    subprocess.run(
        [
            _ffmpeg(),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=d={seconds}:s={size}:r=24",
            "-f",
            "lavfi",
            "-i",
            f"sine=d={seconds}",
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    return str(path)


@pytest.mark.parametrize("fmt", ["webm", "mov", "mp3", "wav"])
def test_render_timeline_writes_each_format(tmp_path, fmt, no_end_hold):
    import shutil

    src = _clip(tmp_path / "a.mp4")
    tl = T.normalize(
        {
            "width": 320,
            "height": 180,
            "tracks": [
                {
                    "kind": "video",
                    "clips": [{"id": "a", "src": src, "in": 0, "out": 2}],
                },
            ],
        }
    )
    out = T.render_timeline(
        tl, lambda u, p: shutil.copyfile(u, p), str(tmp_path / f"f.{fmt}"), fmt=fmt
    )
    length, has_audio = T.probe(out)
    assert abs(length - 2.0) < 0.2 and has_audio


def test_render_timeline_scales_by_the_short_side(tmp_path):
    import shutil

    src = _clip(tmp_path / "a.mp4")
    tl = T.normalize(
        {
            "width": 320,
            "height": 180,
            "tracks": [
                {
                    "kind": "video",
                    "clips": [{"id": "a", "src": src, "in": 0, "out": 2}],
                },
            ],
        }
    )
    out = T.render_timeline(
        tl, lambda u, p: shutil.copyfile(u, p), str(tmp_path / "f.mp4"), short_side=360
    )
    assert story_service.video_size(out) == (640, 360)


# -- logo -----------------------------------------------------------------------------


def test_logo_auto_corner_is_top_right_for_portrait():
    assert bk.resolve_corner("auto", 720, 1280) == "tr"
    assert bk.resolve_corner("auto", 1280, 720) == "br"
    assert bk.resolve_corner("bl", 720, 1280) == "bl"


@pytest.mark.parametrize("size,share", [("s", 0.12), ("m", 0.16), ("l", 0.22)])
def test_logo_box_size_and_margin(size, share):
    x, y, w, h = bk.logo_box(400, 200, 1280, 720, "auto", size)
    assert w == round(720 * share) and abs(h - w / 2) <= 1
    margin = round(720 * 0.05)
    assert (x + w, y + h) == (1280 - margin, 720 - margin)
    # A tall logo is held to the same height.
    _, _, w2, h2 = bk.logo_box(100, 400, 1280, 720, "tl", size)
    assert h2 == round(720 * share) and w2 < h2


def test_logo_overlay_is_85_percent_opaque_top_right_on_portrait(tmp_path):
    logo = tmp_path / "logo.png"
    Image.new("RGBA", (200, 200), (255, 0, 0, 255)).save(logo)
    out = bk.logo_overlay_png(str(logo), 720, 1280, str(tmp_path / "o.png"))
    img = Image.open(out)
    x0, y0, x1, y1 = img.getchannel("A").getbbox()
    assert x0 > 360 and y1 < 640  # top right
    assert img.getpixel(((x0 + x1) // 2, (y0 + y1) // 2))[3] == int(255 * 0.85)


def test_clean_kit_keeps_size_and_auto():
    kit = bk.clean({"corner": "auto", "logo_size": "l"})
    assert (kit["corner"], kit["logo_size"]) == ("auto", "l")
    assert bk.clean({"logo_size": "xl"})["logo_size"] == "s"


def test_render_opts_branding_switch():
    story = Story(brand_json=json.dumps({"logo_uri": "gs://b/l.png", "logo_size": "m"}))
    on, ext, mime = story_service.render_opts(story, {"fmt": "webm"})
    assert on["logo"] == "gs://b/l.png" and on["logo_size"] == "m" and ext == "webm"
    off, _, _ = story_service.render_opts(story, {"branding": False})
    assert "logo" not in off and mime == "video/webm"


# -- jobs: first film logo, edits, proxy, export --------------------------------------


@pytest.fixture
def demo(tmp_path, monkeypatch):
    store = story_store.LocalStoryStore(str(tmp_path / "stories.json"))
    story_store.set_store(store)
    monkeypatch.setattr(story_service, "LOCAL_MEDIA_DIR", str(tmp_path / "media"))
    backend = story_service.MockStoryBackend(speed=0)
    story_service.set_backend(backend)
    yield store, backend
    story_service.set_backend(None)
    story_store.set_store(None)


def _wait(job):
    done = story_jobs.wait(job.id, OWNER, timeout=120)
    assert done is not None and done.status == "done", [
        (t.label, t.error) for t in done.tasks
    ]
    return done


def _film(store, backend, brand=""):
    story = store.save(
        Story(
            idea="A lighthouse",
            scene_count=2,
            duration=4,
            music_on=False,
            voice_on=False,
            brand_json=brand,
        ),
        OWNER,
    )
    frames = [backend.generate_frame(story, i, "") for i in range(2)]
    story.scenes = [Scene(visual="Sea", duration=4, frame_uri=f) for f in frames]
    story.approved = True
    store.save(story, OWNER)
    _wait(story_jobs.start_video(story.id, OWNER))
    return store.get(story.id, OWNER)


def _pixel(path, at, x, y):
    from services.story_timeline import _ffmpeg

    png = path + ".png"
    subprocess.run(
        [
            _ffmpeg(),
            "-v",
            "error",
            "-y",
            "-ss",
            str(at),
            "-i",
            path,
            "-frames:v",
            "1",
            png,
        ],
        check=True,
    )
    return Image.open(png).convert("RGB").getpixel((x, y))


def test_first_film_carries_the_brand_logo(demo):
    store, backend = demo
    rel = "brand/logo.png"
    path = story_service.local_path("local://" + rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGBA", (200, 200), (255, 0, 0, 255)).save(path)
    brand = json.dumps(bk.clean({"logo_uri": "local://" + rel, "corner": "br"}))
    s = _film(store, backend, brand)
    film = story_service.local_path(s.final_uri)
    w, h = story_service.video_size(film)
    x, y, lw, lh = bk.logo_box(200, 200, w, h, "br", "s")
    r, g, b = _pixel(film, 1.0, x + lw // 2, y + lh // 2)
    assert r > 150 and g < 120 and b < 120  # red logo, see-through


def test_edit_marks_the_film_and_undo_clears_it(demo):
    store, backend = demo
    s = _film(store, backend)
    original = s.timeline_json
    tl = json.loads(original)
    T.track(tl, "text")["clips"].append({"text": "Hello", "start": 0, "dur": 1})
    tl["rev"] = "abc:1"
    saved = story_jobs.save_timeline(s.id, OWNER, json.dumps(tl))
    assert saved.film_edited and json.loads(saved.timeline_json)["rev"] == "abc:1"
    assert story_jobs.preview(saved)[1] == "making"
    back = json.loads(original)
    back["rev"] = "abc:2"
    saved = story_jobs.save_timeline(s.id, OWNER, json.dumps(back))
    assert not saved.film_edited
    assert story_jobs.preview(saved) == (saved.final_uri, "film")


def test_proxy_renders_small_and_is_picked_up(demo):
    store, backend = demo
    s = _film(store, backend)
    tl = json.loads(s.timeline_json)
    T.track(tl, "video")["clips"].pop()
    story_jobs.save_timeline(s.id, OWNER, json.dumps(tl))
    story_jobs._proxy_running.add(s.id)
    story_jobs._proxy_worker(s.id, OWNER)
    s = store.get(s.id, OWNER)
    uri, state = story_jobs.preview(s)
    assert state == "ready" and uri == s.proxy_uri and "proxy_" in uri
    path = story_service.local_path(uri)
    assert min(story_service.video_size(path)) == T.PROXY_SHORT_SIDE
    assert abs(T.probe(path)[0] - T.duration(T.normalize(s.timeline_json))) < 0.2
    assert s.id not in story_jobs._proxy_running


def test_export_options_make_extra_downloads(demo):
    store, backend = demo
    s = _film(store, backend)
    film = s.final_uri
    _wait(story_jobs.start_export(s.id, OWNER, {"fmt": "mp3"}))
    s = store.get(s.id, OWNER)
    assert s.final_uri == film  # an extra download, not the film
    row = ex.ready(s, ex.clean({"fmt": "mp3"}, T.normalize(s.timeline_json)))
    assert row["uri"].endswith(".mp3") and row["name"].endswith(".mp3")
    assert T.probe(story_service.local_path(row["uri"]))[1]
    _wait(story_jobs.start_export(s.id, OWNER, {}))
    s = store.get(s.id, OWNER)
    assert s.final_uri != film and not s.film_edited
    assert story_jobs.film_timeline(s) is not None


def test_download_route_sends_an_attachment(demo, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from common.identity import ANONYMOUS_USER_EMAIL
    from routers import story_router

    store, backend = demo
    monkeypatch.setattr(story_router, "_caller", lambda request: OWNER)
    s = _film(store, backend)
    app = FastAPI()
    app.include_router(story_router.router)
    client = TestClient(app)
    res = client.get(f"/api/story/{s.id}/download/film")
    assert res.status_code == 200 and res.headers["content-type"] == "video/mp4"
    assert res.headers["content-disposition"].startswith("attachment;")
    assert len(res.content) > 1000
    assert client.get(f"/api/story/{s.id}/download/export-nope").status_code == 404
    assert client.get(f"/api/story/{s.id}/download/version-x").status_code == 404
    monkeypatch.setattr(story_router, "_caller", lambda request: ANONYMOUS_USER_EMAIL)
    assert client.get(f"/api/story/{s.id}/download/film").status_code == 404


def test_download_names():
    from routers import story_router

    story = Story(title="Sea: story", final_uri="gs://b/film_1.mp4")
    assert story_router.download_target(story, "film") == (
        "gs://b/film_1.mp4",
        "Sea story.mp4",
    )
    assert story_router.download_target(story, "alt") is None
    assert "filename*=UTF-8''" in story_router._disposition("Café.mp4")
