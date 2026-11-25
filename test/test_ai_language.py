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
"""AI output follows the person's language (Arabic in, Arabic out), with the
site language as the fallback. No network: model clients are faked."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from common import lang_detect
from common.lang_detect import detect_lang, english_for_model, resolve_lang
from services import live_agent, studio_chat
from services.live_agent import LiveCall, ScriptedAgent
from services.live_jobs import LiveJobs, RunResult

OWNER = "presenter@example.com"
FOX_AR = "اصنع صورة لثعلب في الثلج"


def _runners():
    def run(job):
        return RunResult(
            gcs_uri="gs://b/x.png",
            display_url="https://x.test/x.png",
            mime_type="image/png",
        )

    return {k: run for k in ("image", "video", "music", "voice")}


def _call(lang="en", mode=live_agent.ACT):
    sent = []

    async def send(message):
        sent.append(message)

    return LiveCall(OWNER, send, LiveJobs(runners=_runners()), mode, lang=lang), sent


def _agent(lang="en"):
    call, sent = _call(lang)
    said = []

    async def say(text):
        said.append(text)

    return ScriptedAgent(call, say, lang=lang), call, said, sent


# --- detection --------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "want"),
    [
        (FOX_AR, "ar"),
        ("make a red fox in snow", "en"),
        ("اصنع فيديو Veo بنسبة 16:9 بدقة 4k", "ar"),
        ("123 456", ""),
        ("", ""),
    ],
)
def test_detect_lang(text, want):
    assert detect_lang(text) == want


def test_resolve_lang_uses_text_then_site_language():
    assert resolve_lang("", lang="ar") == "ar"
    assert resolve_lang("a fox", lang="ar") == "en"
    assert resolve_lang(FOX_AR, lang="en") == "ar"
    assert resolve_lang("", None) == "en"  # outside Mesop


def test_english_for_model_keeps_text_without_arabic_or_in_mock(monkeypatch):
    assert english_for_model("a fox") == "a fox"
    monkeypatch.setattr("common.mock_generation.mock_enabled", lambda: True)
    assert english_for_model(FOX_AR) == FOX_AR


def test_english_for_model_translates_arabic(monkeypatch):
    monkeypatch.setattr("common.mock_generation.mock_enabled", lambda: False)
    lang_detect._translate.cache_clear()
    monkeypatch.setattr(lang_detect, "_translate", lambda text: "a fox in the snow")
    assert english_for_model(FOX_AR) == "a fox in the snow"


def test_english_for_model_falls_back_on_error(monkeypatch):
    monkeypatch.setattr("common.mock_generation.mock_enabled", lambda: False)

    def boom(_text):
        raise RuntimeError("no network")

    monkeypatch.setattr(lang_detect, "_translate", boom)
    assert english_for_model(FOX_AR) == FOX_AR


# --- system prompts ---------------------------------------------------------


@pytest.mark.parametrize("mode", [live_agent.FILL, live_agent.ACT])
def test_live_prompt_has_language_rule_and_site_language(mode):
    ar = live_agent.system_prompt(mode, "ar")
    en = live_agent.system_prompt(mode, "en")
    for prompt in (ar, en):
        assert "language the person uses" in prompt
        assert "field value" in prompt
    assert "use Arabic, the language the site is set to" in ar
    assert "use English, the language the site is set to" in en


def test_chat_prompt_drops_english_only_prompts():
    prompt = studio_chat.chat_prompt("ar")
    assert "may stay in English" not in prompt
    assert "use Arabic" in prompt


def test_live_config_injects_site_language():
    from routers import live_router

    cfg = live_router._live_config(None, live_agent.FILL, "", "ar")
    assert "use Arabic, the language the site is set to" in cfg.system_instruction


def test_site_lang_from_query_or_cookie():
    from routers import live_router

    ws = SimpleNamespace(query_params={"lang": "ar"}, cookies={})
    assert live_router._site_lang(ws) == "ar"
    ws = SimpleNamespace(query_params={}, cookies={"gm_lang": "ar"})
    assert live_router._site_lang(ws) == "ar"
    ws = SimpleNamespace(query_params={}, cookies={})
    assert live_router._site_lang(ws) == "en"


def test_rewriter_asks_for_the_input_language(monkeypatch):
    from models import gemini

    seen = []

    class FakeModels:
        def generate_content(self, model, contents, config):
            seen.append(contents)
            return SimpleNamespace(text="ok", usage_metadata=None)

    monkeypatch.setattr(gemini, "client", SimpleNamespace(models=FakeModels()))
    gemini.rewriter(FOX_AR, "Rewrite:")
    assert "in Arabic" in seen[0]
    gemini.rewriter("a fox", "Rewrite:")
    assert "in English" in seen[-1]


def test_fix_and_outline_prompts_follow_the_request_language():
    from services import story_director, story_fix
    from services.story_models import Story

    story = Story(idea="قصة قصيرة عن صياد في الدوحة", language="Arabic")
    assert "in Arabic" in story_fix.fix_prompt(story, "اجعل النهاية أسعد")
    assert 'summary" in English.' in story_fix.fix_prompt(story, "make it happier")
    assert (
        "brief and sequence titles and summaries in Arabic"
        in story_director.outline_prompt(story)
    )


# --- offline agent ----------------------------------------------------------


def test_offline_arabic_image_keeps_arabic_prompt_and_replies_in_arabic():
    agent, call, said, sent = _agent("en")
    asyncio.run(agent.handle(FOX_AR))
    jobs = call.jobs.list(OWNER)
    assert jobs and jobs[0].kind == "image"
    assert jobs[0].prompt == "ثعلب في الثلج"
    compose = [m for m in sent if m.get("action") == "compose"]
    assert compose and compose[0]["args"]["prompt"] == "ثعلب في الثلج"
    assert detect_lang(said[-1]) == "ar"
    assert "الصورة 1" in said[-1]


@pytest.mark.parametrize(
    ("text", "kind", "prompt"),
    [
        ("اصنع فيديو لقطة تركض على الشاطئ", "video", "قطة تركض على الشاطئ"),
        ("اعمل موسيقى هادئة على البيانو", "music", "هادئة على البيانو"),
        ("قل مرحباً بكم في الاستوديو", "voice", "مرحباً بكم في الاستوديو"),
    ],
)
def test_offline_arabic_media(text, kind, prompt):
    agent, call, said, _ = _agent()
    asyncio.run(agent.handle(text))
    job = call.jobs.list(OWNER)[0]
    assert job.kind == kind
    assert job.prompt == prompt
    assert detect_lang(said[-1]) == "ar"


def test_offline_arabic_voice_uses_arabic_speech_code():
    agent, call, _, _ = _agent()
    asyncio.run(agent.handle("قل أهلاً وسهلاً"))
    assert call.jobs.list(OWNER)[0].params["language"].startswith("ar")


def test_offline_english_still_english():
    agent, call, said, _ = _agent("ar")
    asyncio.run(agent.handle("image of a red fox in snow"))
    assert call.jobs.list(OWNER)[0].prompt == "a red fox in snow"
    assert said[-1].startswith("Starting the image")


def test_offline_help_follows_language():
    agent, _, said, _ = _agent()
    asyncio.run(agent.handle("مرحبا"))
    assert detect_lang(said[-1]) == "ar"


def test_offline_arabic_error_is_arabic():
    agent, _, said, _ = _agent()
    asyncio.run(agent.handle("عدّل الصورة لتكون ليلية"))
    assert said[-1] == "لا توجد صورة بعد. اصنع واحدة أولاً."


def test_job_done_said_in_last_request_language():
    agent, call, said, _ = _agent()
    asyncio.run(agent.handle(FOX_AR))
    job = call.jobs.list(OWNER)[0]
    job.status = "done"
    asyncio.run(agent.on_job_done(job))
    assert said[-1] == "الصورة 1 جاهزة."


def test_story_tool_defaults_to_idea_language(monkeypatch):
    from services import live_story

    got = {}

    def fake_record(owner, idea, **kw):
        got.update(kw)
        raise ValueError("stop")

    monkeypatch.setattr(live_story, "create_story_record", fake_record)
    call, _ = _call("en")
    asyncio.run(call.run_tool("create_story", {"idea": "قصة عن صياد في الدوحة"}))
    assert got["language"] == "Arabic"
    asyncio.run(call.run_tool("create_story", {"idea": "a fisherman in Doha at dawn"}))
    assert got["language"] == "English"
    call_ar, _ = _call("ar")
    asyncio.run(call_ar.run_tool("create_story", {"idea": "12345678"}))
    assert got["language"] == "Arabic"  # no letters: site language


def test_fill_fields_keeps_arabic_values():
    call, sent = _call(mode=live_agent.FILL)

    async def run():
        task = asyncio.create_task(
            call.run_tool(
                "fill_fields",
                {
                    "values_json": json.dumps(
                        {"prompt": "ثعلب في الثلج"}, ensure_ascii=False
                    )
                },
            )
        )
        while not sent:
            await asyncio.sleep(0.01)
        message = sent[0]
        assert message["args"]["fields"] == {"prompt": "ثعلب في الثلج"}
        call.ui_result(message["id"], {"changed": message["args"]["fields"]})
        return await task

    out = asyncio.run(run())
    assert out["changed"] == {"prompt": "ثعلب في الثلج"}


def test_voice_job_speaks_arabic_text_in_arabic():
    from services.live_jobs import speech_language

    assert speech_language("gemini-2.5-flash-tts", "مرحبا بكم", "en-US").startswith(
        "ar"
    )
    assert speech_language("gemini-2.5-flash-tts", "hello", "en-US") == "en-US"
    assert speech_language("chirp-3-hd", "hello", "ar-EG") == "ar-XA"


# --- chat -------------------------------------------------------------------


def test_chat_offline_arabic_reply_and_trace(monkeypatch):
    studio_chat.reset(OWNER)
    s = studio_chat.session_for(OWNER, LiveJobs(runners=_runners()))
    assert s is studio_chat.session_for(OWNER)
    out = studio_chat.send(OWNER, FOX_AR, None, None, "en")
    # The reply follows the message; the steps are app text (site language).
    assert detect_lang(out["reply"]) == "ar"
    assert out["trace"][0]["label"] == "Reading your message"
    assert out["jobs"][0]["prompt"] == "ثعلب في الثلج"
    out = studio_chat.send(OWNER, "image of a fox", None, None, "ar")
    assert out["trace"][0]["label"] == "أقرأ رسالتك"
    assert detect_lang(out["reply"]) == "en"
    studio_chat.reset(OWNER)


def test_chat_site_language_reaches_the_model():
    studio_chat.reset(OWNER)
    studio_chat.session_for(OWNER, LiveJobs(runners=_runners()))
    seen = {}

    class FakeModels:
        def generate_content(self, model, contents, config):
            seen["system"] = config.system_instruction
            part = SimpleNamespace(text="حسناً", function_call=None)
            content = SimpleNamespace(parts=[part], role="model")
            return SimpleNamespace(
                candidates=[SimpleNamespace(content=content)], usage_metadata=None
            )

    out = studio_chat.send(
        OWNER, "?", (SimpleNamespace(models=FakeModels()), "m"), None, "ar"
    )
    assert "use Arabic, the language the site is set to" in seen["system"]
    assert out["reply"] == "حسناً"
    studio_chat.reset(OWNER)


# --- Live panel strings -----------------------------------------------------


@pytest.mark.parametrize("lang", ["en", "ar"])
def test_live_strings_have_no_raw_keys(lang):
    from components.live_agent.live_agent import _strings_json_for_lang

    _strings_json_for_lang.cache_clear()
    data = json.loads(_strings_json_for_lang(lang, ""))
    raw = [k for k, v in data.items() if isinstance(v, str) and v.startswith("live.")]
    assert raw == []
    assert data["lang"] == lang
    if lang == "ar":
        for key in (
            "mute",
            "jobs",
            "hangup",
            "type",
            "avatarHint",
            "toolFill",
            "signin",
        ):
            assert detect_lang(data[key]) == "ar", key
    else:
        assert data["mute"] == "Mute microphone"


def test_live_speaking_word_is_the_panel_one():
    from components.live_agent.live_agent import _strings_json_for_lang

    _strings_json_for_lang.cache_clear()
    assert json.loads(_strings_json_for_lang("ar", ""))["speaking"] == "أتحدث"


class _FakeModels:
    def __init__(self, text):
        self.text = text
        self.contents = None

    def generate_content(self, model, contents, config=None):
        self.contents = contents
        return SimpleNamespace(text=self.text, usage_metadata=None)


def test_room_names_in_site_language(monkeypatch):
    from models import gemini

    fake = _FakeModels('{"rooms": [{"room_name": "المطبخ"}]}')
    monkeypatch.setattr(gemini, "client", SimpleNamespace(models=fake))
    assert gemini.extract_room_names_from_image("gs://b/plan.png", lang="ar") == [
        "المطبخ"
    ]
    assert "Write each room name in Arabic" in fake.contents[0]


def test_look_descriptions_and_critic_in_site_language(monkeypatch):
    from models import gemini

    fake = _FakeModels('{"article_descriptions": [], "look_description": "x"}')
    monkeypatch.setattr(gemini, "client", SimpleNamespace(models=fake))
    try:
        gemini.describe_images_and_look([], lang="ar")
    except Exception:  # noqa: BLE001  (only the prompt matters here)
        pass
    assert "Write every description in Arabic." in fake.contents


def test_vto_critique_in_site_language(monkeypatch):
    from models import vto_critique

    fake = _FakeModels(
        '{"accurate": true, "placement_analysis": "جيد", "reasoning": "جيد"}'
    )
    monkeypatch.setattr(
        vto_critique.GeminiModelSetup,
        "init",
        staticmethod(lambda **_: SimpleNamespace(models=fake)),
    )
    try:
        vto_critique.evaluate_vto_placement("gs://b/a.png", "gs://b/r.png", lang="ar")
    except Exception:  # noqa: BLE001
        pass
    assert "placement_analysis and reasoning in Arabic" in fake.contents[0]
