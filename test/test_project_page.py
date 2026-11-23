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
"""Project page (/project?id=): its API, media list, strings and route."""

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services import chat_store
from services.chat_store import LocalChatStore

ME = "me@example.com"
OTHER = "other@example.com"


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = LocalChatStore(str(tmp_path))
    chat_store.set_store(s)
    monkeypatch.setattr(chat_store, "_mocked", lambda: True)
    yield s
    chat_store.set_store(None)


def client_for(email):
    from routers import chats_router

    app = FastAPI()

    @app.middleware("http")
    async def who(request, call_next):
        request.scope["MESOP_USER_EMAIL"] = email
        return await call_next(request)

    app.include_router(chats_router.router)
    return TestClient(app)


def job(job_id, kind="image", status="done", url=None, **extra):
    return {
        "id": job_id,
        "kind": kind,
        "status": status,
        "handle": f"{kind} 1",
        "prompt": f"prompt {job_id}",
        "display_url": f"https://example.com/{job_id}" if url is None else url,
        "mime_type": "",
        **extra,
    }


def chat_with(*jobs, chat_id="c1", title="Chat"):
    return {
        "id": chat_id,
        "title": title,
        "messages": [
            {"role": "user", "text": "make it", "jobs": []},
            {"role": "assistant", "text": "ok", "jobs": list(jobs)},
        ],
    }


# -- media ----------------------------------------------------------------


def test_chat_media_keeps_finished_safe_jobs_newest_first():
    newer = chat_with(
        job("a"),
        job("running", status="running"),
        job("failed", status="failed"),
        job("nourl", url=""),
        job("js", url="javascript:alert(1)"),
        job("proto", url="//evil.test/x.png"),
        job("local", kind="video", url="/media/x.mp4", mime_type="video/mp4"),
        job("mock", url="data:image/svg+xml;base64,AAAA"),
        chat_id="new",
        title="Newer",
    )
    older = chat_with(
        job("b", kind="music"),
        job("film", kind="story", params={"has_film": True}),
        chat_id="old",
    )
    rows = chat_store.chat_media([newer, older])
    assert [r["id"] for r in rows] == ["mock", "local", "a", "film", "b"]
    first = rows[0]
    assert first["chat_id"] == "new" and first["chat_title"] == "Newer"
    assert rows[3]["has_film"] is True and rows[4]["has_film"] is False
    assert set(first) == {
        "id",
        "kind",
        "handle",
        "prompt",
        "display_url",
        "mime_type",
        "has_film",
        "chat_id",
        "chat_title",
    }


def test_chat_media_counts_a_job_once_and_caps():
    stale = {"role": "assistant", "text": "", "jobs": [job("a", status="running")]}
    chat = chat_with(job("a"), job("b"), job("c"))
    chat["messages"].insert(0, stale)
    assert [r["id"] for r in chat_store.chat_media([chat])] == ["c", "b", "a"]
    assert len(chat_store.chat_media([chat], limit=2)) == 2
    assert chat_store.chat_media([{"id": "x", "messages": []}]) == []


# -- API ------------------------------------------------------------------


def test_api_project_page(store):
    me = client_for(ME)
    pid = me.post("/api/projects", json={"name": "Launch"}).json()["project"]["id"]
    body = chat_with(job("img"), job("vid", kind="video"))
    body.pop("id")
    body["project_id"] = pid
    cid = me.post("/api/chats", json=body).json()["chat"]["id"]
    me.post("/api/chats", json={"title": "loose", "messages": body["messages"]})

    r = me.get(f"/api/projects/{pid}")
    assert r.status_code == 200
    data = r.json()
    assert data["project"]["name"] == "Launch"
    assert [c["id"] for c in data["chats"]] == [cid]
    assert "messages" not in data["chats"][0]
    assert [m["id"] for m in data["media"]] == ["vid", "img"]
    assert all(m["chat_id"] == cid for m in data["media"])

    # Someone else's project, or one that does not exist, is not found.
    assert client_for(OTHER).get(f"/api/projects/{pid}").status_code == 404
    assert me.get("/api/projects/nope").status_code == 404


def test_api_deleting_a_project_moves_its_chats_back_to_recents(store):
    me = client_for(ME)
    pid = me.post("/api/projects", json={"name": "Launch"}).json()["project"]["id"]
    ids = {
        me.post("/api/chats", json={"title": t, "project_id": pid}).json()["chat"]["id"]
        for t in ("one", "two")
    }
    assert me.delete(f"/api/projects/{pid}").json() == {"ok": True}
    assert me.get(f"/api/projects/{pid}").status_code == 404
    recents = me.get("/api/chats?project=").json()["chats"]
    assert {c["id"] for c in recents} == ids
    assert all(c["project_id"] == "" for c in recents)


# -- page, side menu and strings --------------------------------------------


def test_project_route_is_registered():
    from mesop.runtime import runtime

    import pages.project  # noqa: F401  pylint: disable=unused-import

    assert runtime().get_page_config(path="/project") is not None
    main_py = os.path.join(os.path.dirname(__file__), "..", "src", "main.py")
    with open(main_py, encoding="utf-8") as f:
        assert "import pages.project\n" in f.read()


def test_project_strings_have_english_and_arabic():
    from common import i18n
    from components.chat_nav import chat_nav
    from components.project_view import project_view

    s = project_view.strings()
    for key in ("new_chat", "chats", "media", "empty", "not_found", "rename"):
        assert s[key], key
    # The project page and the side menu read Arabic from common/i18n.py,
    # with the same English as their own fallbacks.
    for table in (project_view._STRINGS, chat_nav._STRINGS):
        for key, english in table.values():
            assert key in i18n.AR, key
            assert i18n.EN.get(key) == english, key


def test_nav_event_opens_project_page_but_not_other_sites():
    from components.chat_nav import chat_nav

    seen = []
    state = SimpleNamespace(current_page="")
    with (
        patch(
            "mesop.navigate",
            lambda url, query_params=None: seen.append((url, query_params)),
        ),
        patch("mesop.state", return_value=state),
    ):
        list(
            chat_nav.on_chat_nav(
                SimpleNamespace(value={"url": "/project", "params": {"id": "p1"}})
            )
        )
        list(chat_nav.on_chat_nav(SimpleNamespace(value={"url": "//evil.test/x"})))
    assert seen == [("/project", {"id": "p1"}), ("/home", None)]
