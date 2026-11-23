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
"""Saved Home chats and projects: local store, titles and the REST API."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services import chat_store
from services.chat_store import ChatAccessError, LocalChatStore

ME = "me@example.com"
OTHER = "other@example.com"


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = LocalChatStore(str(tmp_path))
    chat_store.set_store(s)
    monkeypatch.setattr(chat_store, "_mocked", lambda: True)
    yield s
    chat_store.set_store(None)


def msg(role, text, **extra):
    return {"role": role, "text": text, **extra}


# -- store ----------------------------------------------------------------


def test_save_get_list_owner_only(store):
    a = store.save_chat({"title": "A", "messages": [msg("user", "hi")]}, ME)
    store.save_chat({"title": "B"}, OTHER)
    assert a["owner"] == ME and a["created_at"] and a["updated_at"]
    assert [c["title"] for c in store.list_chats(ME)] == ["A"]
    assert store.get_chat(a["id"], ME)["messages"][0]["text"] == "hi"
    assert store.get_chat(a["id"], OTHER) is None
    assert store.get_chat(a["id"], "") is None
    assert store.list_chats("") == []


def test_cannot_overwrite_or_delete_someone_elses_chat(store):
    a = store.save_chat({"title": "Mine"}, ME)
    with pytest.raises(ChatAccessError):
        store.save_chat({"id": a["id"], "title": "Stolen"}, OTHER)
    with pytest.raises(ChatAccessError):
        store.save_chat({"title": "x"}, "")
    assert store.delete_chat(a["id"], OTHER) is False
    assert store.get_chat(a["id"], ME)["title"] == "Mine"
    assert store.delete_chat(a["id"], ME) is True
    assert store.get_chat(a["id"], ME) is None


def test_newest_first_and_touch(store):
    a = store.save_chat({"title": "old"}, ME)
    b = store.save_chat({"title": "new"}, ME)
    assert [c["id"] for c in store.list_chats(ME)] == [b["id"], a["id"]]
    a["pinned"] = True
    store.save_chat(a, ME, touch=False)  # pinning keeps the order
    assert [c["id"] for c in store.list_chats(ME)] == [b["id"], a["id"]]
    store.save_chat(a, ME)
    assert store.list_chats(ME)[0]["id"] == a["id"]
    assert store.get_chat(a["id"], ME)["created_at"] == a["created_at"]


def test_messages_are_cleaned_and_capped(store):
    msgs = [msg("user", f"m{i}") for i in range(chat_store.MAX_MESSAGES + 25)]
    msgs.append({"role": "system", "text": "dropped"})
    msgs.append(
        msg(
            "assistant",
            "done",
            images=["gs://b/x.png", "data:image/png;base64,AAAA", 5],
            jobs=[{"id": "j1", "kind": "image"}],
            ask={"question": "Which?", "options": ["a", "b"]},
        ),
    )
    c = store.save_chat({"messages": msgs}, ME)
    assert len(c["messages"]) == chat_store.MAX_MESSAGES
    last = c["messages"][-1]
    assert last["images"] == ["gs://b/x.png"]
    assert last["jobs"] == [{"id": "j1", "kind": "image"}]
    assert last["ask"]["options"] == ["a", "b"]
    assert all(m["role"] in ("user", "assistant") for m in c["messages"])


def test_project_delete_keeps_chats(store):
    p = store.save_project({"name": "Launch"}, ME)
    c = store.save_chat({"title": "in project", "project_id": p["id"]}, ME)
    loose = store.save_chat({"title": "loose"}, ME)
    assert [x["id"] for x in store.list_chats(ME, p["id"])] == [c["id"]]
    assert [x["id"] for x in store.list_chats(ME, "")] == [loose["id"]]
    assert store.delete_project(p["id"], OTHER) is False
    assert store.delete_project(p["id"], ME) is True
    assert store.list_projects(ME) == []
    kept = store.get_chat(c["id"], ME)
    assert kept is not None and kept["project_id"] == ""
    assert len(store.list_chats(ME)) == 2


def test_projects_owner_only(store):
    p = store.save_project({"name": "  My   folder "}, ME)
    assert p["name"] == "My folder"
    assert store.list_projects(OTHER) == []
    assert store.get_project(p["id"], OTHER) is None
    with pytest.raises(ChatAccessError):
        store.save_project({"id": p["id"], "name": "x"}, OTHER)
    with pytest.raises(ValueError):
        store.save_project({"name": " "}, ME)
    # A chat can't be filed into someone else's project.
    with pytest.raises(ValueError):
        store.save_chat({"project_id": p["id"]}, OTHER)


# -- titles ---------------------------------------------------------------


def test_trim_title():
    assert chat_store.trim_title(
        "\n  make a video of waves crashing at sunset please\nmore"
    ) == ("make a video of waves crashing")
    assert chat_store.trim_title("") == ""


def test_auto_title_mock_trims(monkeypatch):
    monkeypatch.setattr(chat_store, "_mocked", lambda: True)
    assert chat_store.auto_title("a cat on a skateboard.") == "a cat on a skateboard"


def test_auto_title_uses_gemini_and_falls_back(monkeypatch):
    import models.gemini as gemini

    monkeypatch.setattr(chat_store, "_mocked", lambda: False)
    monkeypatch.setattr(
        gemini, "rewriter", lambda text, prompt: '"Title: Skateboarding Cat Video."'
    )
    assert chat_store.auto_title("a cat on a skateboard") == "Skateboarding Cat Video"

    def boom(*_):
        raise RuntimeError("quota")

    monkeypatch.setattr(gemini, "rewriter", boom)
    assert chat_store.auto_title("a cat on a skateboard") == "a cat on a skateboard"


# -- API --------------------------------------------------------------------


def client_for(email):
    from routers import chats_router

    app = FastAPI()

    @app.middleware("http")
    async def who(request, call_next):
        request.scope["MESOP_USER_EMAIL"] = email
        return await call_next(request)

    app.include_router(chats_router.router)
    return TestClient(app)


def test_api_chat_flow(store):
    me = client_for(ME)
    r = me.post("/api/chats", json={})
    assert r.status_code == 200
    chat = r.json()["chat"]
    assert chat["title"] == "" and chat["title_source"] == "auto"

    # First messages name the chat (trimmed in mock mode).
    r = me.patch(
        f"/api/chats/{chat['id']}",
        json={
            "messages": [
                msg("user", "Video of waves at sunset over the sea, slow"),
                msg("assistant", "On it"),
            ]
        },
    )
    assert r.json()["chat"]["title"] == "Video of waves at sunset over"
    assert r.json()["chat"]["messages"][1]["text"] == "On it"

    # A user title sticks; later messages don't rename it.
    me.patch(
        f"/api/chats/{chat['id']}",
        json={"title": "Waves", "pinned": True, "job_ids": ["j1"]},
    )
    r = me.patch(
        f"/api/chats/{chat['id']}", json={"messages": [msg("user", "something else")]}
    )
    body = r.json()["chat"]
    assert body["title"] == "Waves" and body["title_source"] == "user"
    assert body["pinned"] is True and body["job_ids"] == ["j1"]

    listed = me.get("/api/chats").json()["chats"]
    assert (
        len(listed) == 1
        and "messages" not in listed[0]
        and listed[0]["message_count"] == 1
    )
    assert (
        me.get(f"/api/chats/{chat['id']}").json()["chat"]["messages"][0]["text"]
        == "something else"
    )

    assert me.delete(f"/api/chats/{chat['id']}").json() == {"ok": True}
    assert me.get(f"/api/chats/{chat['id']}").status_code == 404


def test_api_create_with_messages_gets_title(store):
    me = client_for(ME)
    r = me.post("/api/chats", json={"messages": [msg("user", "Jazz loop for a cafe")]})
    assert r.json()["chat"]["title"] == "Jazz loop for a cafe"


def test_api_repeated_create_with_page_id_makes_one_chat(store):
    me, other = client_for(ME), client_for(OTHER)
    first = me.post(
        "/api/chats", json={"id": "a1b2c3d4e5f6", "messages": [msg("user", "Hi")]}
    )
    again = me.post(
        "/api/chats",
        json={
            "id": "a1b2c3d4e5f6",
            "messages": [msg("user", "Hi"), msg("assistant", "Hello")],
        },
    )
    assert first.json()["chat"]["id"] == again.json()["chat"]["id"] == "a1b2c3d4e5f6"
    listed = me.get("/api/chats").json()["chats"]
    assert len(listed) == 1 and listed[0]["message_count"] == 2
    # Someone else can't take over that id.
    assert other.post("/api/chats", json={"id": "a1b2c3d4e5f6"}).status_code == 403
    # A malformed id is ignored and a fresh one is made.
    odd = me.post("/api/chats", json={"id": "../x"}).json()["chat"]["id"]
    assert odd != "../x" and len(odd) == 12


def test_api_owner_isolation(store):
    me, other = client_for(ME), client_for(OTHER)
    cid = me.post("/api/chats", json={"title": "secret"}).json()["chat"]["id"]
    pid = me.post("/api/projects", json={"name": "P"}).json()["project"]["id"]
    assert other.get(f"/api/chats/{cid}").status_code == 404
    assert other.patch(f"/api/chats/{cid}", json={"title": "x"}).status_code == 404
    assert other.delete(f"/api/chats/{cid}").status_code == 404
    assert other.get("/api/chats").json() == {"chats": []}
    assert other.get("/api/projects").json() == {"projects": []}
    assert other.patch(f"/api/projects/{pid}", json={"name": "x"}).status_code == 404
    assert other.delete(f"/api/projects/{pid}").status_code == 404
    # Filing your own chat into someone else's project is refused.
    ocid = other.post("/api/chats", json={}).json()["chat"]["id"]
    assert (
        other.patch(f"/api/chats/{ocid}", json={"project_id": pid}).status_code == 400
    )
    assert me.get(f"/api/chats/{cid}").json()["chat"]["title"] == "secret"


def test_api_projects_and_delete_keeps_chats(store):
    me = client_for(ME)
    pid = me.post("/api/projects", json={"name": "Launch"}).json()["project"]["id"]
    assert (
        me.patch(f"/api/projects/{pid}", json={"name": "Launch v2"}).json()["project"][
            "name"
        ]
        == "Launch v2"
    )
    assert me.post("/api/projects", json={"name": ""}).status_code == 400
    cid = me.post("/api/chats", json={"title": "c", "project_id": pid}).json()["chat"][
        "id"
    ]
    me.post("/api/chats", json={"title": "loose"})
    assert [c["id"] for c in me.get(f"/api/chats?project={pid}").json()["chats"]] == [
        cid
    ]
    assert [c["title"] for c in me.get("/api/chats?project=").json()["chats"]] == [
        "loose"
    ]
    assert me.delete(f"/api/projects/{pid}").json() == {"ok": True}
    assert me.get(f"/api/chats/{cid}").json()["chat"]["project_id"] == ""
    assert len(me.get("/api/chats").json()["chats"]) == 2


def test_api_guards(store):
    me = client_for(ME)
    assert (
        me.post(
            "/api/chats", json={}, headers={"origin": "https://evil.test"}
        ).status_code
        == 403
    )
    assert (
        me.post(
            "/api/chats", content="x", headers={"content-type": "text/plain"}
        ).status_code
        == 415
    )
    assert (
        me.post(
            "/api/chats", content="[1]", headers={"content-type": "application/json"}
        ).status_code
        == 400
    )
    cid = me.post("/api/chats", json={}).json()["chat"]["id"]
    assert me.patch(f"/api/chats/{cid}", json={"messages": "nope"}).status_code == 400
    assert (
        me.delete(
            f"/api/chats/{cid}", headers={"origin": "https://evil.test"}
        ).status_code
        == 403
    )


def test_api_requires_sign_in_when_auth_is_on(store, monkeypatch):
    from common.identity import ANONYMOUS_USER_EMAIL
    from routers import chat_router

    monkeypatch.setattr(chat_router, "require_authenticated_user", lambda _env: True)
    anon = client_for(ANONYMOUS_USER_EMAIL)
    assert anon.get("/api/chats").status_code == 403
    assert anon.post("/api/chats", json={}).status_code == 403
