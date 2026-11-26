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
"""The Live voice agent's tools, instructions and per-call logic.

Two kinds of tools:

* **Job tools** (generate_image, edit_image, generate_video) start a
  background job in :mod:`services.live_jobs` and return nothing yet. The
  Live API keeps talking (``NON_BLOCKING``); the result is sent when the job
  finishes with ``WHEN_IDLE``, so the agent mentions it at the next pause.
* **Screen tools** (open_page, show_job, download, end_call, read_page,
  fill_fields) run in the browser: the server sends ``{"type": "ui", ...}``
  and waits for the result.

A call runs in one of two modes. **Fill only** (the default) only reads and
fills the fields of the page in front of the presenter (see
:mod:`services.page_forms`): the job tools are not even declared, so the
model cannot start a generation; the presenter presses Generate. **Do it for
me** adds the job tools, which run generations in the background.

``LiveCall`` holds no Gemini session itself; the router wires it to one, and
the offline :class:`ScriptedAgent` drives it the same way for tests and demos
without a model.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from google.genai import types

from common.lang_detect import detect_lang, follow_user_rule, lang_name, speech_code
from config.voice import DEFAULT_LANGUAGE, DEFAULT_VOICE, VOICES as VOICE_NAMES
from services.live_jobs import DONE, FAILED, JobLimitError, LiveJob, LiveJobs
from services.story_models import ASPECT_RATIOS as STORY_ASPECTS
from services.story_models import STEP_IDS, STYLES

logger = logging.getLogger(__name__)

Send = Callable[[dict], Awaitable[None]]

FILL, ACT = "fill", "act"
MODES = (FILL, ACT)
# Tools a Fill only call has: read and fill the page, move around, look.
FILL_TOOLS = {
    "read_page",
    "fill_fields",
    "open_page",
    "list_jobs",
    "show_job",
    "download",
    "end_call",
}

PAGES = {
    "home": "/home",
    "image": "/nano-banana",
    "video": "/veo",
    "music": "/lyria",
    "voice": "/voice",
    "story": "/story",
    "library": "/library",
}
JOB_PAGE = {
    "image": "/nano-banana",
    "video": "/veo",
    "music": "/lyria",
    "voice": "/voice",
    "story": "/story",
}
UI_TIMEOUT_S = 10.0
# How long a story tool waits for its background step to start before it
# opens the page, so the page can follow that step's progress.
STORY_START_WAIT_S = 3.0

IMAGE_ASPECTS = ("1:1", "16:9", "9:16", "4:3", "3:4")
VIDEO_ASPECTS = ("16:9", "9:16")
STORY_STYLES = tuple(s["id"] for s in STYLES)
STORY_STEPS = tuple(s for s in STEP_IDS if s != "stories")
# Tools the model keeps talking through (Behavior.NON_BLOCKING): media jobs,
# and the fix planner, which watches the whole film with Gemini.
NON_BLOCKING_TOOLS = {
    "generate_image",
    "edit_image",
    "generate_video",
    "generate_music",
    "generate_voice",
    "create_story",
    "continue_story",
    "render_film",
    "plan_film_fix",
    "run_film_fix",
}

SYSTEM_PROMPT = """You are the voice of Creative Studio, a studio built on Google's media models. You run the app for the presenter while an audience watches the screen.

How you talk:
- Short and warm. One sentence per reply, two at most. Never read out URLs, ids or long prompts.
- Always speak out loud. Before every tool call, say in a few words what you are doing ("On it, starting the fox image."), and after it, say what happened. Never call a tool or start a job in silence.
- When a job finishes you get its result. Say so in a few words at the next pause, e.g. "Image 1 is ready." Do not open it unless asked or nothing else is happening on screen.

How you work:
- Use generate_image, edit_image, generate_video, generate_music, generate_voice and the Film Studio tools (create_story, continue_story, render_film, story_status, open_story). Job tools run in the background, so start several at once when asked ("while that runs, make a video..." or "make some calm piano music").
- Write rich prompts for the models from what the presenter says: subject, style, lighting, camera, or genre, instruments, mood. Keep their words and intent.
- Jobs have short names: "image 1", "video 1", "music 1", "voice 1", "story 1". "The image" or "the story" means the latest one unless the presenter says otherwise. Say which one you act on.
- When the presenter dislikes something in a finished film, call plan_film_fix with their words (and the moment in seconds if they name one). Planning takes a little while: say you are watching the film, and keep talking if they speak. When the plan arrives, say in one sentence what will change and whether it costs a new render, then wait for a yes before run_film_fix.
- For Film Studio, move one step at a time with continue_story (approve scenario, build set, paint storyboard, then render film) so the presenter stays in control. When they ask for the whole film in one go, call continue_story with all_steps true. The screen moves through each Film Studio page as the steps run; say which step is on screen.
- edit_image needs a finished image. If it is still rendering, say so and offer to edit it once it is ready.
- Use show_job to bring a result on screen, open_page to move between studios, download to save a file to the presenter's computer, and end_call when they say goodbye.
- If a job fails, say why in plain words and offer to retry.
- Only do media tasks in this app. Politely decline anything else."""


FILL_PROMPT = """You are the voice of Creative Studio, a studio built on Google's media models. You help the presenter fill in the page in front of them while an audience watches the screen.

How you talk:
- Short and warm. One sentence per reply, two at most. Never read out URLs, ids or long prompts.
- Always speak out loud. Before every tool call, say in a few words what you are doing ("Let me set that up."), and after it, say what you set. Never fill the page in silence.

How you work:
- You only fill in fields. You never start a generation and never say you did: the presenter presses Generate (or Plan the fix) themselves.
- Call read_page first to see the page's fields, their current values and the allowed choices. When the presenter changes page you get a [Screen] note with the new page and its fields: you are already there, so do not open it again.
- Call fill_fields with only the fields to change, as a JSON object of field name to value. Use the choices exactly as listed.
- Turn a short request into a rich prompt of one or two sentences: subject, action, style, lighting, camera, or genre, instruments, mood, tempo. Keep their words and intent.
- After filling, say in a few words what you set, e.g. "Done: a tall fox video, eight seconds, with sound. Press Generate when ready."
- If a field was refused, say why in plain words and use an allowed value.
- If the fields they want are on another studio, use open_page, then read_page.
- In Film Studio, the Create step has the film's idea and settings, and the Edit step has the Fix with AI box (fix_request, and fix_time for a moment of the film).
- When asked to generate, fill the fields and tell them it is ready for them to press Generate.
- Only do media tasks in this app. Politely decline anything else."""

PAGE_NOTE = """
- You can also fill the page in front of the presenter: read_page shows its fields and fill_fields sets them, without pressing Generate. Use this when they ask you to fill or set up the page rather than to make something."""


def system_prompt(mode: str = FILL, lang: str = "en") -> str:
    """Instructions for a call in `mode` (FILL or ACT). `lang` is the site
    language, used when the presenter's own language is not clear yet."""
    base = FILL_PROMPT if mode == FILL else SYSTEM_PROMPT + PAGE_NOTE
    return base + "\n\n" + follow_user_rule(lang)


def _resolve_voice(voice: str) -> str:
    """Match a requested voice name case-insensitively, or fall back to default."""
    target = (voice or "").strip().lower()
    for name in VOICE_NAMES:
        if name.lower() == target:
            return name
    return DEFAULT_VOICE


def _prop(
    kind: str, desc: str, choices: list[str] | tuple[str, ...] = ()
) -> types.Schema:
    """One parameter. `choices` become a schema enum, so the model can only
    send an allowed value."""
    if choices:
        return types.Schema(type=kind, description=desc, enum=list(choices))
    return types.Schema(type=kind, description=desc)


def _schema(props: dict[str, tuple], required: list[str]) -> types.Schema:
    """`props` maps a name to (type, description) or (type, description, choices)."""
    return types.Schema(
        type="OBJECT",
        properties={name: _prop(*spec) for name, spec in props.items()},
        required=required,
    )


def tool_declarations(async_tools: bool = True, mode: str = ACT) -> list[types.Tool]:
    """The call's tools. A Fill only call gets FILL_TOOLS alone."""
    tools = _all_declarations(async_tools)
    if mode == FILL:
        keep = [f for f in tools[0].function_declarations if f.name in FILL_TOOLS]
        return [types.Tool(function_declarations=keep)]
    return tools


def _all_declarations(async_tools: bool = True) -> list[types.Tool]:
    job = types.Behavior.NON_BLOCKING if async_tools else None
    screen = types.Behavior.BLOCKING if async_tools else None

    def fd(name, description, props=None, required=None, behavior=None):
        kwargs: dict[str, Any] = {"name": name, "description": description}
        if props:
            kwargs["parameters"] = _schema(props, required or [])
        if behavior is not None:
            kwargs["behavior"] = behavior
        return types.FunctionDeclaration(**kwargs)

    return [
        types.Tool(
            function_declarations=[
                fd(
                    "generate_image",
                    "Start an image job in Image Studio. Runs in the background; the result arrives later.",
                    {
                        "prompt": ("STRING", "A detailed image prompt."),
                        "aspect_ratio": ("STRING", "Default 1:1.", IMAGE_ASPECTS),
                    },
                    ["prompt"],
                    job,
                ),
                fd(
                    "edit_image",
                    "Edit a finished image (for example change the time of day or the style). Runs in the background.",
                    {
                        "instruction": (
                            "STRING",
                            "What to change, written as an edit instruction.",
                        ),
                        "image": (
                            "STRING",
                            "Which image, e.g. 'image 1'. Empty means the latest image.",
                        ),
                    },
                    ["instruction"],
                    job,
                ),
                fd(
                    "generate_video",
                    "Start a short video job (8 seconds, with sound) in Video Studio. Runs in the background.",
                    {
                        "prompt": (
                            "STRING",
                            "A detailed video prompt: subject, action, camera, mood.",
                        ),
                        "from_image": (
                            "STRING",
                            "Optional: animate this finished image, e.g. 'image 1'.",
                        ),
                        "aspect_ratio": ("STRING", "Default 16:9.", VIDEO_ASPECTS),
                    },
                    ["prompt"],
                    job,
                ),
                fd(
                    "generate_music",
                    "Start a music track job in Music Studio (Lyria). Runs in the background.",
                    {
                        "prompt": (
                            "STRING",
                            "A detailed music prompt: genre, mood, instruments, tempo.",
                        ),
                        "lyrics": (
                            "STRING",
                            "Optional lyrics to sing; omit for instrumental music.",
                        ),
                    },
                    ["prompt"],
                    job,
                ),
                fd(
                    "generate_voice",
                    "Generate spoken audio (TTS) in Voice Studio. Runs in the background.",
                    {
                        "script": ("STRING", "The exact text to be spoken aloud."),
                        "voice": (
                            "STRING",
                            f"Optional voice name (default {DEFAULT_VOICE}). Allowed: "
                            + ", ".join(VOICE_NAMES)
                            + ".",
                            VOICE_NAMES,
                        ),
                        "language": (
                            "STRING",
                            "BCP-47 code of the script's language: 'ar-EG' for Arabic, "
                            "'en-US' for English. Empty means the script's own language.",
                        ),
                    },
                    ["script"],
                    job,
                ),
                fd(
                    "create_story",
                    "Start a new Film Studio film from an idea and write its scenario. Runs in the background.",
                    {
                        "idea": (
                            "STRING",
                            "The film idea in a sentence or two.",
                        ),
                        "length": (
                            "STRING",
                            "Optional total film length, e.g. '30 seconds' or '1 minute'.",
                        ),
                        "aspect_ratio": ("STRING", "Optional.", STORY_ASPECTS),
                        "style": ("STRING", "Optional visual style.", STORY_STYLES),
                        "language": (
                            "STRING",
                            "Optional language the film is spoken in, e.g. 'English' or "
                            "'Arabic'. Empty means the language of the idea.",
                        ),
                    },
                    ["idea"],
                    job,
                ),
                fd(
                    "continue_story",
                    "Advance a Film Studio film by one step (approve scenario, build set, paint storyboard, or render film), or with all_steps through every remaining step to the finished film. The screen follows each step.",
                    {
                        "story": (
                            "STRING",
                            "Optional story title or id. Empty means the latest story.",
                        ),
                        "all_steps": (
                            "BOOLEAN",
                            "True to run every remaining step in turn (approve, set, storyboard, film) when the presenter asks for the whole film.",
                        ),
                    },
                    [],
                    job,
                ),
                fd(
                    "render_film",
                    "Render the Film Studio film once every scene has a storyboard frame. Runs in the background.",
                    {
                        "story": (
                            "STRING",
                            "Optional story title or id. Empty means the latest story.",
                        )
                    },
                    [],
                    job,
                ),
                fd(
                    "plan_film_fix",
                    "Plan a Fix with AI for a finished Film Studio film: Gemini watches the film and decides what to change (lines, pictures, the set, music, cuts, or the story). Changes nothing yet. Takes a little while; the plan arrives when it is ready.",
                    {
                        "request": (
                            "STRING",
                            "What the presenter dislikes or wants changed, in their words.",
                        ),
                        "at_seconds": (
                            "NUMBER",
                            "Optional moment of the film in seconds, e.g. 12.5.",
                        ),
                        "story": (
                            "STRING",
                            "Optional story title or id. Empty means the latest story.",
                        ),
                    },
                    ["request"],
                    job,
                ),
                fd(
                    "run_film_fix",
                    "Run the fix planned by plan_film_fix, after the presenter said yes. Runs in the background.",
                    behavior=job,
                ),
                fd(
                    "story_status",
                    "Check a Film Studio film's current step, active job progress, and whether a film is ready.",
                    {
                        "story": (
                            "STRING",
                            "Optional story title or id. Empty means the latest story.",
                        )
                    },
                    [],
                ),
                fd(
                    "open_story",
                    "Open a Film Studio film on screen at the requested or current step.",
                    {
                        "story": (
                            "STRING",
                            "Optional story title or id. Empty means the latest story.",
                        ),
                        "step": (
                            "STRING",
                            "Optional step to open (editor is Scenes, video is Edit).",
                            STORY_STEPS,
                        ),
                    },
                    [],
                    screen,
                ),
                fd(
                    "list_jobs",
                    "List every job in this call with its status, and what page is on screen.",
                ),
                fd(
                    "show_job",
                    "Bring a job's result on screen (opens its studio).",
                    {
                        "job": (
                            "STRING",
                            "e.g. 'image 1', 'video 1', or empty for the latest.",
                        )
                    },
                    [],
                    screen,
                ),
                fd(
                    "open_page",
                    "Go to a page of the app.",
                    {"page": ("STRING", "The page to open.", tuple(PAGES))},
                    ["page"],
                    screen,
                ),
                fd(
                    "download",
                    "Download a finished result to the presenter's computer.",
                    {
                        "job": (
                            "STRING",
                            "e.g. 'image 2', or empty for the latest image.",
                        )
                    },
                    [],
                    screen,
                ),
                fd(
                    "read_page",
                    "Read the fields of the page on screen: each field's name, label, kind, current value and allowed choices or range.",
                    behavior=screen,
                ),
                fd(
                    "fill_fields",
                    "Fill fields of the page on screen, as if the presenter typed them. Never presses Generate. Returns what changed and what was refused.",
                    {
                        "values_json": (
                            "STRING",
                            'A JSON object of field name to new value, e.g. {"prompt": "A red fox in snow", "aspect_ratio": "9:16", "sound": true}.',
                        )
                    },
                    ["values_json"],
                    screen,
                ),
                fd(
                    "end_call",
                    "Hang up when the presenter says goodbye.",
                    behavior=screen,
                ),
            ]
        )
    ]


def page_params(job: LiveJob) -> dict:
    """Query params so the studio shows the same model and input as the job."""
    if job.kind == "story":
        story_id = str(job.params.get("story_id") or "")
        if not story_id:
            return {}
        return {
            "id": story_id,
            "step": str(job.params.get("story_step") or "scenario"),
        }
    if job.kind != "video":
        return {}
    from config.video_studio_models import DEFAULT_STUDIO_MODEL_ID

    params = {"veo_model": DEFAULT_STUDIO_MODEL_ID}
    if job.source_uri.startswith("gs://"):
        params["image_path"] = job.source_uri
    return params


def job_summary(job: LiveJob) -> dict:
    data = {
        "job": job.handle,
        "status": job.status,
        "prompt": job.prompt[:160],
    }
    if job.source_job:
        data["from"] = job.source_job
    if job.status == FAILED:
        data["error"] = job.error
    return data


@dataclass
class Deferred:
    """A job tool's answer that is sent when the job finishes."""

    job: LiveJob


class LiveCall:
    """Tool handling for one call. ``send`` pushes JSON to the browser."""

    def __init__(
        self, owner: str, send: Send, jobs: LiveJobs, mode: str = ACT, lang: str = "en"
    ):
        self.owner = owner
        # The site language: the fallback when a request has no letters.
        self.lang = lang if lang in ("en", "ar") else "en"
        self.send = send
        self.jobs = jobs
        self.mode = mode if mode in MODES else FILL
        # (story_id, FixPlan) waiting for the presenter's yes.
        self.pending_fix = None
        self.planning = False  # plan_film_fix is running
        self.screen = "/home"
        self.ended = False
        self.latest_story_id = ""
        self._waiters: dict[str, asyncio.Future] = {}
        # Story job id -> (story_jobs id, step) last put on screen.
        self._story_view: dict[str, tuple[str, str]] = {}

    # -- browser round trips ----------------------------------------------

    async def ui(self, action: str, args: dict, wait: bool = True) -> dict:
        call_id = uuid.uuid4().hex[:10]
        message = {"type": "ui", "id": call_id, "action": action, "args": args}
        if not wait:
            await self.send(message)
            return {"ok": True}
        future = asyncio.get_running_loop().create_future()
        self._waiters[call_id] = future
        try:
            await self.send(message)
            return await asyncio.wait_for(future, UI_TIMEOUT_S)
        except TimeoutError:
            return {"ok": False, "error": "The screen did not answer in time."}
        finally:
            self._waiters.pop(call_id, None)

    def ui_result(self, call_id: str, result: dict) -> None:
        future = self._waiters.get(call_id)
        if future and not future.done():
            future.set_result(result or {"ok": True})

    # -- tools ------------------------------------------------------------

    async def run_tool(self, name: str, args: dict | None) -> dict | Deferred:
        args = args or {}
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            return {"error": f"Unknown tool {name}."}
        if self.mode == FILL and name not in FILL_TOOLS:
            return {
                "error": "Fill only mode: fill the fields with fill_fields instead. "
                "The presenter presses Generate."
            }
        try:
            return await handler(**{k: v for k, v in args.items() if v is not None})
        except TypeError as exc:
            return {"error": f"Bad arguments for {name}: {exc}"}
        except JobLimitError as exc:
            return {"error": str(exc)}
        except ValueError as exc:
            return {"error": str(exc)}

    async def _start(
        self,
        kind: str,
        prompt: str,
        aspect_ratio: str = "",
        source: LiveJob | None = None,
        params: dict[str, Any] | None = None,
    ) -> Deferred:
        job = self.jobs.submit(
            self.owner,
            kind,
            prompt,
            aspect_ratio=aspect_ratio,
            source=source,
            params=params,
        )
        # Show the work: go to the studio, type the prompt, point at Generate.
        await self.ui(
            "compose",
            {
                "page": JOB_PAGE[kind],
                "params": page_params(job),
                "prompt": job.prompt,
                "job": job.public(),
            },
            wait=False,
        )
        self.screen = JOB_PAGE[kind]
        return Deferred(job)

    async def _tool_generate_image(
        self, prompt: str, aspect_ratio: str = "1:1"
    ) -> Deferred:
        return await self._start("image", prompt, aspect_ratio)

    async def _tool_edit_image(
        self, instruction: str, image: str = ""
    ) -> dict | Deferred:
        source = self.jobs.resolve(self.owner, image, kind="image")
        if source is None:
            return {"error": "There is no image yet. Make one first."}
        if source.status != DONE:
            return {
                "error": f"{source.handle} is still {source.status}. Edit it once it is ready."
            }
        return await self._start("image", instruction, source.aspect_ratio, source)

    async def _tool_generate_video(
        self, prompt: str, from_image: str = "", aspect_ratio: str = "16:9"
    ) -> dict | Deferred:
        source = None
        if from_image.strip():
            source = self.jobs.resolve(self.owner, from_image, kind="image")
            if source is None or source.status != DONE:
                return {"error": "That image is not ready yet, so I can't animate it."}
        return await self._start("video", prompt, aspect_ratio, source)

    async def _tool_generate_music(self, prompt: str, lyrics: str = "") -> Deferred:
        params = {"lyrics": lyrics.strip()} if lyrics.strip() else None
        return await self._start("music", prompt, params=params)

    async def _tool_generate_voice(
        self, script: str, voice: str = "", language: str = ""
    ) -> Deferred:
        params = {
            "voice": _resolve_voice(voice),
            # Spoken in the script's own language (Arabic text, Arabic voice).
            "language": (language or "").strip()
            or speech_code(detect_lang(script) or self.lang)
            or DEFAULT_LANGUAGE,
        }
        return await self._start("voice", script, params=params)

    async def _start_story(
        self, story, action: str, step: str, prompt: str, extra: dict | None = None
    ) -> Deferred:
        self.latest_story_id = story.id
        job = self.jobs.submit(
            self.owner,
            "story",
            prompt,
            params={
                "story_id": story.id,
                "story_action": action,
                "story_step": step,
                "story_title": story.title,
                **(extra or {}),
            },
        )
        # Open the page once the step runs, so it shows that step's progress
        # (opened earlier, it finds no running job to follow).
        end = asyncio.get_running_loop().time() + STORY_START_WAIT_S
        while (
            not job.params.get("story_job_id")
            and job.status not in (DONE, FAILED)
            and asyncio.get_running_loop().time() < end
        ):
            await asyncio.sleep(0.05)
        await self.show_story(job, step)
        return Deferred(job)

    async def show_story(self, job: LiveJob, step: str = "") -> None:
        """Put a story job's current step on screen, once per step."""
        story_id = str(job.params.get("story_id") or "")
        if not story_id:
            return
        step = str(job.params.get("story_step") or step or "scenario")
        key = (str(job.params.get("story_job_id") or ""), step)
        if self._story_view.get(job.id) == key:
            return
        self._story_view[job.id] = key
        await self.ui(
            "navigate",
            {"page": "/story", "params": {"id": story_id, "step": step}},
            wait=False,
        )
        self.screen = "/story"

    async def _tool_create_story(
        self,
        idea: str,
        length: str = "",
        aspect_ratio: str = "",
        style: str = "",
        language: str = "",
        **setup: Any,
    ) -> Deferred:
        """``setup``: Story Studio's other setup choices (Home's Film fields:
        speech_mode, camera, pacing, video_model, scene_count, scene_seconds,
        script); not in the model's declaration."""
        from services import live_story

        allowed = {
            "speech_mode",
            "camera",
            "pacing",
            "video_model",
            "scene_count",
            "scene_seconds",
            "script",
        }
        story = live_story.create_story_record(
            self.owner,
            idea,
            length=length,
            aspect_ratio=aspect_ratio,
            style=style,
            # Unset: the idea's own language (Arabic idea, Arabic film).
            language=language or lang_name(detect_lang(idea) or self.lang),
            **{k: v for k, v in setup.items() if k in allowed},
        )
        return await self._start_story(story, "scenario", "scenario", story.idea)

    async def _tool_continue_story(
        self, story: str = "", all_steps: bool = False
    ) -> dict | Deferred:
        from services import live_story

        found = live_story.resolve_story(self.owner, story, self.latest_story_id)
        if found is None:
            return {"error": "There is no story yet. Create one first."}
        self.latest_story_id = found.id
        action = live_story.next_step_action(found)
        if action != "done" and all_steps:
            label = found.title or found.idea[:60]
            return await self._start_story(
                found, "all", live_story.step_page(action), f"whole film: {label}"
            )
        if action == "done":
            return {
                "story_id": found.id,
                "title": found.title or found.idea[:60],
                "step": "video",
                "has_film": True,
                "note": "The film is already rendered.",
            }
        if action == "approve":
            approved = live_story.approve_story(found.id, self.owner)
            await self.ui(
                "navigate",
                {"page": "/story", "params": {"id": approved.id, "step": "set"}},
                wait=False,
            )
            self.screen = "/story"
            return {
                "story_id": approved.id,
                "title": approved.title or approved.idea[:60],
                "step": "set",
                "approved": True,
                "note": "Scenario approved. Call continue_story again to build the set.",
            }
        step = "video" if action == "video" else action
        label = found.title or found.idea[:60]
        return await self._start_story(found, action, step, f"{action}: {label}")

    async def _tool_render_film(self, story: str = "") -> dict | Deferred:
        from services import live_story

        found = live_story.resolve_story(self.owner, story, self.latest_story_id)
        if found is None:
            return {"error": "There is no story yet. Create one first."}
        self.latest_story_id = found.id
        problem = live_story.check_render_ready(found)
        if problem:
            return {"error": problem}
        label = found.title or found.idea[:60]
        return await self._start_story(found, "video", "video", f"render: {label}")

    async def _tool_story_status(self, story: str = "") -> dict:
        from services import live_story

        found = live_story.resolve_story(self.owner, story, self.latest_story_id)
        if found is None:
            return {"error": "There is no story yet."}
        self.latest_story_id = found.id
        return live_story.story_status_summary(found, self.owner)

    async def _tool_open_story(self, story: str = "", step: str = "") -> dict:
        from services import live_story

        found = live_story.resolve_story(self.owner, story, self.latest_story_id)
        if found is None:
            return {"error": "There is no story yet."}
        self.latest_story_id = found.id
        target = live_story.open_step_for(found, step)
        result = await self.ui(
            "navigate",
            {"page": "/story", "params": {"id": found.id, "step": target}},
        )
        self.screen = "/story"
        return {
            "story_id": found.id,
            "title": found.title or found.idea[:60],
            "step": target,
            "url": f"/story?id={found.id}&step={target}",
            "ok": bool(result.get("ok")),
        }

    async def _tool_plan_film_fix(
        self, request: str, at_seconds: str = "", story: str = ""
    ) -> dict:
        from services import live_story, story_fix

        found = live_story.resolve_story(self.owner, story, self.latest_story_id)
        if found is None:
            return {"error": "There is no story yet."}
        if not found.final_uri:
            return {"error": "This film is not rendered yet, so there is nothing to fix."}
        self.latest_story_id = found.id
        try:
            seconds = float(at_seconds) if str(at_seconds).strip() else None
        except ValueError:
            seconds = None
        self.pending_fix = None
        self.planning = True
        try:
            plan = await asyncio.to_thread(
                story_fix.plan_fix, found.id, self.owner, request, -1, seconds
            )
        except Exception as exc:  # a planner failure is said, not raised
            logger.exception("Live: fix planning failed")
            return {"error": f"Could not plan the fix: {str(exc)[:160]}"}
        finally:
            self.planning = False
        if not plan.runnable:
            self.pending_fix = None
            return {"question": plan.question or "What exactly should change?"}
        story_set = story_fix.story_set_of(found)
        steps = story_fix.plan_steps(found, plan, story_set)
        self.pending_fix = (found.id, plan)
        await self.ui(
            "navigate",
            {"page": "/story", "params": {"id": found.id, "step": "video"}},
            wait=False,
        )
        self.screen = "/story"
        return {
            "summary": plan.summary,
            "changes": [c.summary for c in plan.changes if c.summary],
            "steps": [s.label for s in steps],
            "costs_money": any(s.paid for s in steps),
            "note": "Tell the presenter what will change and ask before run_film_fix.",
        }

    async def _tool_run_film_fix(self) -> dict | Deferred:
        import json

        if self.pending_fix is None:
            if self.planning:
                return {
                    "error": "The fix plan is still being made. Wait for it, then ask."
                }
            return {"error": "Plan the fix first with plan_film_fix."}
        story_id, plan = self.pending_fix
        self.pending_fix = None
        from services import live_story

        found = live_story.resolve_story(self.owner, story_id, story_id)
        if found is None:
            return {"error": "The story is gone."}
        return await self._start_story(
            found,
            "fix",
            "video",
            f"fix: {plan.summary[:60] or 'film'}",
            {"fix_plan_json": json.dumps(plan.to_dict())},
        )

    async def _tool_list_jobs(self) -> dict:
        return {
            "on_screen": self.screen,
            "jobs": [job_summary(j) for j in self.jobs.list(self.owner)],
        }

    async def _tool_show_job(self, job: str = "") -> dict:
        found = self.jobs.resolve(self.owner, job)
        if found is None:
            return {"error": "There are no jobs yet."}
        result = await self.ui(
            "show_job",
            {
                "page": JOB_PAGE[found.kind],
                "params": page_params(found),
                "job": found.public(),
            },
        )
        self.screen = JOB_PAGE[found.kind]
        return {**job_summary(found), "shown": bool(result.get("ok"))}

    async def _tool_open_page(self, page: str) -> dict:
        route = PAGES.get((page or "").strip().lower())
        if route is None:
            return {"error": f"No page called {page}. Pages: {', '.join(PAGES)}."}
        result = await self.ui("navigate", {"page": route})
        self.screen = route
        return {"opened": page, "ok": bool(result.get("ok"))}

    async def _tool_download(self, job: str = "") -> dict:
        found = self.jobs.resolve(self.owner, job, kind="" if job else "image")
        if found is None:
            return {"error": "There is nothing to download yet."}
        if found.status != DONE:
            return {"error": f"{found.handle} is not finished yet."}
        result = await self.ui("download", {"job": found.public()})
        return {"downloaded": found.handle, **result}

    def screen_changed(self, path: str, fields=None) -> str:
        """The browser reports the page on screen. Returns a note for the
        model when the presenter moved by themselves (the agent's own moves
        already set `screen`), else ""."""
        if path == self.screen:
            return ""
        self.screen = path
        note = f"[Screen] The presenter opened {path}."
        rows = fields if isinstance(fields, list) else []
        shown = []
        for f in rows[:12]:
            if not isinstance(f, dict) or not f.get("name"):
                continue
            value = f.get("value")
            if isinstance(value, str) and len(value) > 60:
                value = value[:60] + "..."
            shown.append(f"{f['name']}={value!r}")
        if shown:
            note += " Its fields: " + ", ".join(shown) + "."
        elif self.mode == FILL:
            note += " It has no fields to fill."
        return note + " Do not reply to this note."

    async def _tool_read_page(self) -> dict:
        result = await self.ui("read_page", {})
        if not result.get("ok", True):
            return {"error": result.get("error") or "Could not read the page."}
        fields = result.get("fields") or []
        out = {"page": result.get("page") or self.screen, "fields": fields}
        if not fields:
            out["note"] = "This page has no fields you can fill. Open a studio first."
        return out

    async def _tool_fill_fields(self, values_json: str = "", **values) -> dict:
        import json

        if values_json:
            try:
                parsed = json.loads(values_json)
            except ValueError:
                return {"error": "values_json must be a JSON object."}
            if not isinstance(parsed, dict):
                return {"error": "values_json must be a JSON object."}
            values = {**values, **parsed}
        if not values:
            return {"error": "Name at least one field to fill."}
        result = await self.ui("fill", {"fields": values})
        if not result.get("ok", True):
            return {"error": result.get("error") or "Could not fill the page."}
        return {
            "changed": result.get("changed") or {},
            "refused": result.get("refused") or {},
        }

    async def _tool_end_call(self) -> dict:
        self.ended = True
        await self.ui("end_call", {}, wait=False)
        return {"ok": True}

    # -- job results ------------------------------------------------------

    @staticmethod
    def job_result(job: LiveJob) -> dict:
        if job.status == DONE:
            if job.kind == "story":
                action = job.params.get("story_action") or "step"
                step = job.params.get("story_step") or ""
                out: dict[str, Any] = {
                    "job": job.handle,
                    "status": "done",
                    "story_id": job.params.get("story_id", ""),
                    "title": job.params.get("story_title", ""),
                    "step": step,
                    "has_film": bool(job.params.get("has_film")),
                    "note": (
                        f"Story {action} is ready (took {int(job.public()['seconds'])} seconds)."
                    ),
                }
                if job.params.get("has_film") and job.display_url:
                    out["film_url"] = job.display_url
                return out
            what = "edit" if job.is_edit else job.kind
            return {
                "job": job.handle,
                "status": "done",
                "note": (
                    f"The {what} is ready (took {int(job.public()['seconds'])} seconds). "
                    "It is in the job tray; use show_job to open it."
                ),
            }
        return {"job": job.handle, "status": "failed", "error": job.error}


# ---------------------------------------------------------------------------
# Offline agent: understands a few typed commands, for tests and demos without
# a model (GENMEDIA_MOCK_GENERATION or no Live access).
# ---------------------------------------------------------------------------


class ScriptedAgent:
    """Maps simple typed requests to the same tools the model would call."""

    def __init__(
        self,
        call: LiveCall,
        say: Callable[[str], Awaitable[None]],
        lang: str = "",
    ):
        self.call = call
        self.say = say
        # Language of the last request (the site language before the first),
        # so job updates come in the language the presenter types in.
        self.lang = lang if lang in ("en", "ar") else getattr(call, "lang", "en")

    async def handle(self, text: str) -> None:
        said = (text or "").strip()
        low = said.lower()
        if not low:
            return
        self.lang = detect_lang(said) or self.lang
        if detect_lang(said) == "ar":
            await self._handle_ar(said)
            return
        if any(w in low for w in ("bye", "hang up", "end call")):
            await self.say("Thanks, talk soon.")
            await self.call.run_tool("end_call", {})
        elif "download" in low:
            out = await self.call.run_tool("download", {"job": _ref(low)})
            await self.say(out.get("error") or f"Downloading {out['downloaded']}.")
        elif "story status" in low:
            out = await self.call.run_tool("story_status", {})
            if "error" in out:
                await self.say(out["error"])
            else:
                film = (
                    "film ready"
                    if out.get("has_film")
                    else f"next: {out['next_action']}"
                )
                await self.say(f"{out['title']} is at {out['step']} ({film}).")
        elif any(p in low for p in ("whole film", "all the steps", "finish the film")):
            out = await self.call.run_tool("continue_story", {"all_steps": True})
            if isinstance(out, Deferred):
                await self.say(f"Making the whole film: {out.job.handle}.")
            else:
                await self.say(out.get("error") or out.get("note") or "Done.")
        elif any(p in low for p in ("render the film", "render film")):
            out = await self.call.run_tool("render_film", {})
            await self._started(out, "Rendering the film")
        elif any(
            p in low for p in ("next step", "continue story", "continue the story")
        ):
            out = await self.call.run_tool("continue_story", {})
            if isinstance(out, Deferred):
                await self.say(f"Continuing the story: {out.job.handle}.")
            else:
                await self.say(out.get("error") or out.get("note") or "Done.")
        elif re.search(r"\bstory\s+(about|of)\b", low) or low.startswith(
            ("make a story", "create a story", "start a story")
        ):
            idea = (
                re.sub(
                    r"^.*?\bstory\s*(about|of)?\s*",
                    "",
                    said,
                    flags=re.I,
                ).strip()
                or said
            )
            out = await self.call.run_tool("create_story", {"idea": idea})
            await self._started(out, "Starting the story")
        elif low.startswith("say "):
            script = said[4:].strip()
            out = await self.call.run_tool("generate_voice", {"script": script})
            await self._started(out, "Starting the voice")
        elif any(w in low for w in ("music", "song", "track")) and not low.startswith(
            ("show", "go back", "open")
        ):
            prompt = (
                re.sub(
                    r"^(make|generate|create|play)?\s*(some|a)?\s*(music|song|track)\s*(of|about)?\s*",
                    "",
                    said,
                    flags=re.I,
                ).strip()
                or said
            )
            out = await self.call.run_tool("generate_music", {"prompt": prompt})
            await self._started(out, "Starting the music")
        elif low.startswith(("edit", "make it", "change")):
            instruction = re.sub(
                r"^(edit( it| the image)?( to| so)?|make it|change it to)\s*",
                "",
                said,
                flags=re.I,
            )
            out = await self.call.run_tool(
                "edit_image", {"instruction": instruction or said}
            )
            await self._started(out, "Editing")
        elif "video" in low and not low.startswith(("show", "go back", "open")):
            prompt = re.sub(r"^.*?video( of)?\s*", "", said, flags=re.I) or said
            out = await self.call.run_tool("generate_video", {"prompt": prompt})
            await self._started(out, "Starting the video")
        elif any(
            w in low for w in ("image", "picture", "photo")
        ) and not low.startswith(("show", "go back", "open")):
            prompt = (
                re.sub(r"^.*?(image|picture|photo)( of)?\s*", "", said, flags=re.I)
                or said
            )
            out = await self.call.run_tool("generate_image", {"prompt": prompt})
            await self._started(out, "Starting the image")
        elif low.startswith(("show", "go back")):
            out = await self.call.run_tool("show_job", {"job": _ref(low)})
            await self.say(out.get("error") or f"Here's {out['job']}.")
        elif low.startswith("open"):
            if "story" in low and self.call.latest_story_id:
                out = await self.call.run_tool("open_story", {})
                await self.say(out.get("error") or f"Opening {out['title']}.")
            else:
                page = next((p for p in PAGES if p in low), "home")
                await self.call.run_tool("open_page", {"page": page})
                await self.say(f"Opening {page}.")
        elif "status" in low or "jobs" in low:
            out = await self.call.run_tool("list_jobs", {})
            parts = [f"{j['job']} is {j['status']}" for j in out["jobs"]] or [
                "Nothing is running"
            ]
            await self.say(", ".join(parts) + ".")
        else:
            await self.say(
                "Offline mode understands: image of…, video of…, music of…, say …, "
                "make a story about …, next step, the whole film, render the film, story status, "
                "edit…, show image 1, download, open video."
            )

    async def _handle_ar(self, said: str) -> None:
        """The same requests typed in Arabic, answered in Arabic. Prompts,
        ideas and scripts keep the presenter's own Arabic words."""
        n = _ar_norm(said)
        starts = lambda *words: bool(re.match(rf"^\s*(?:{'|'.join(words)})(?!\w)", n))  # noqa: E731
        has = lambda *words: bool(re.search(rf"(?<!\w)(?:{'|'.join(words)})", n))  # noqa: E731
        browsing = starts("اعرض", "ارني", "اريني", "ورني", "ارجع", "افتح")
        if has(
            "مع السلامه",
            "وداعا",
            "باي",
            "انه المكالمه",
            "انهي المكالمه",
            "انهاء المكالمه",
            "اقفل المكالمه",
            "اغلق المكالمه",
        ):
            await self.say("شكراً، إلى اللقاء.")
            await self.call.run_tool("end_call", {})
        elif re.search(
            r"(?<!\w)(?:نزل|نزلي|حمل|حملي|تنزيل|تحميل)(?!\w)", n
        ) and not has("اصنع", "اعمل", "ارسم", "انشئ", "ولد"):
            out = await self.call.run_tool("download", {"job": _ref_ar(n)})
            await self.say(
                _ar_error(out["error"])
                if out.get("error")
                else f"جارٍ تنزيل {_ar_handle(out['downloaded'])}."
            )
        elif has("حاله القصه", "حاله الفيلم"):
            out = await self.call.run_tool("story_status", {})
            if "error" in out:
                await self.say(_ar_error(out["error"]))
            else:
                film = (
                    "الفيلم جاهز"
                    if out.get("has_film")
                    else f"التالي: {out['next_action']}"
                )
                await self.say(f"«{out['title']}» عند خطوة {out['step']} ({film}).")
        elif has(
            "الفيلم كامل",
            "الفيلم كله",
            "كامل الفيلم",
            "كل الخطوات",
            "اكمل الفيلم",
            "كمل الفيلم",
        ):
            out = await self.call.run_tool("continue_story", {"all_steps": True})
            if isinstance(out, Deferred):
                await self.say(f"جارٍ صنع الفيلم كاملاً: {_ar_handle(out.job.handle)}.")
            else:
                await self.say(
                    _ar_error(out.get("error") or out.get("note") or "") or "تم."
                )
        elif has("صدر الفيلم", "انتج الفيلم", "اخرج الفيلم", "رندر", "ارندر"):
            out = await self.call.run_tool("render_film", {})
            await self._started(out, "جارٍ إخراج الفيلم")
        elif has("الخطوه التاليه", "تابع القصه", "اكمل القصه", "كمل القصه"):
            out = await self.call.run_tool("continue_story", {})
            if isinstance(out, Deferred):
                await self.say(f"متابعة القصة: {_ar_handle(out.job.handle)}.")
            else:
                await self.say(
                    _ar_error(out.get("error") or out.get("note") or "") or "تم."
                )
        elif has("قصه", "فيلم") and not browsing:
            m = re.search(r"(?:قصة|قصه|فيلم)[ًٌٍَُِّْـ]*\s*(?:(?:عن|حول)\s+)?(.*)$", said)
            idea = (m.group(1).strip() if m else "") or said
            out = await self.call.run_tool(
                "create_story", {"idea": idea, "language": "Arabic"}
            )
            await self._started(out, "بدء القصة")
        elif starts("قل", "قولي", "انطق", "اقرا"):
            script = re.sub(r"^\s*\S+\s*", "", said, count=1).strip() or said
            out = await self.call.run_tool("generate_voice", {"script": script})
            await self._started(out, "بدء الصوت")
        elif has("موسيقي", "اغنيه", "لحن", "مقطوعه") and not browsing:
            prompt = (
                _ar_after(
                    said,
                    r"موسيقى|موسيقي|أغنية|اغنية|أغنيه|اغنيه|لحن|لحنًا|مقطوعة|مقطوعه",
                )
                or said
            )
            out = await self.call.run_tool("generate_music", {"prompt": prompt})
            await self._started(out, "بدء الموسيقى")
        elif starts("عدل", "غير", "اجعلها", "اجعله", "خليها", "خليه"):
            instruction = re.sub(r"^\s*\S+\s*", "", said, count=1).strip() or said
            out = await self.call.run_tool("edit_image", {"instruction": instruction})
            await self._started(out, "جارٍ التعديل")
        elif has("فيديو", "مقطع") and not browsing:
            prompt = _ar_after(said, r"فيديو|فيديوًا|مقطع|مقطعًا") or said
            out = await self.call.run_tool("generate_video", {"prompt": prompt})
            await self._started(out, "بدء الفيديو")
        elif has("صوره", "رسمه", "لوحه") and not browsing:
            prompt = _ar_after(said, r"صورة|صوره|رسمة|رسمه|لوحة|لوحه") or said
            out = await self.call.run_tool("generate_image", {"prompt": prompt})
            await self._started(out, "بدء الصورة")
        elif starts("اعرض", "ارني", "اريني", "ورني", "ارجع"):
            out = await self.call.run_tool("show_job", {"job": _ref_ar(n)})
            await self.say(
                _ar_error(out["error"])
                if out.get("error")
                else f"هذه {_ar_handle(out['job'])}."
            )
        elif starts("افتح"):
            if has("القصه", "الفيلم") and self.call.latest_story_id:
                out = await self.call.run_tool("open_story", {})
                await self.say(
                    _ar_error(out["error"])
                    if out.get("error")
                    else f"فتح «{out['title']}»."
                )
            else:
                page = next((p for words, p in _AR_PAGES if has(*words)), "home")
                await self.call.run_tool("open_page", {"page": page})
                await self.say(f"فتح {_AR_PAGE_NAMES[page]}.")
        elif has("الحاله", "المهام", "الاعمال", "شو صار", "وين وصل"):
            out = await self.call.run_tool("list_jobs", {})
            parts = [
                f"{_ar_handle(j['job'])} {_AR_STATUS.get(j['status'], j['status'])}"
                for j in out["jobs"]
            ] or ["لا شيء قيد التشغيل"]
            await self.say("، ".join(parts) + ".")
        else:
            await self.say(
                "الوضع دون اتصال يفهم: صورة لـ…، فيديو لـ…، موسيقى…، قل …، "
                "قصة عن …، الخطوة التالية، الفيلم كاملاً، صدّر الفيلم، حالة القصة، "
                "عدّل…، اعرض الصورة 1، نزّل، افتح الفيديو."
            )

    async def _started(self, out: dict | Deferred, verb: str) -> None:
        arabic = self.lang == "ar"
        if isinstance(out, Deferred):
            handle = _ar_handle(out.job.handle) if arabic else out.job.handle
            await self.say(f"{verb}: {handle}.")
        elif arabic:
            await self.say(_ar_error(out.get("error", "")) or "تم.")
        else:
            await self.say(out.get("error", "Done."))

    async def on_job_done(self, job: LiveJob) -> None:
        if self.lang == "ar":
            handle = _ar_handle(job.handle)
            if job.status == DONE:
                await self.say(f"{handle} جاهزة.")
            else:
                await self.say(f"فشلت {handle}: {_ar_error(job.error or '')}")
            return
        if job.status == DONE:
            await self.say(f"{job.handle.capitalize()} is ready.")
        else:
            await self.say(f"{job.handle.capitalize()} failed: {job.error}")


# Arabic for the offline agent (job handles stay "image 1" for the tools).
_AR_KIND = {
    "image": "الصورة",
    "video": "الفيديو",
    "music": "الموسيقى",
    "voice": "الصوت",
    "story": "القصة",
}
_AR_STATUS = {
    "queued": "في الانتظار",
    "running": "قيد التشغيل",
    "done": "جاهزة",
    "failed": "فشلت",
}
# (words, page) in the order they are checked, on normalised text.
_AR_PAGES = (
    (("الصور", "صوره", "صور"), "image"),
    (("الفيديو", "فيديو"), "video"),
    (("الموسيقي", "موسيقي"), "music"),
    (("الصوت", "صوت"), "voice"),
    (("القصه", "قصه", "الفيلم", "فيلم", "الافلام"), "story"),
    (("المكتبه", "مكتبه"), "library"),
    (("الرئيسيه", "البدايه"), "home"),
)
_AR_PAGE_NAMES = {
    "home": "الصفحة الرئيسية",
    "image": "استوديو الصور",
    "video": "استوديو الفيديو",
    "music": "استوديو الموسيقى",
    "voice": "استوديو الصوت",
    "story": "استوديو الأفلام",
    "library": "المكتبة",
}
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def _ar_norm(text: str) -> str:
    """Arabic text for matching: no diacritics or tatweel, one alef, one
    yeh, teh marbuta as heh, Western digits."""
    t = re.sub(r"[ً-ْٰـ]", "", text or "")
    t = re.sub(r"[أإآٱ]", "ا", t).replace("ى", "ي").replace("ة", "ه")
    return t.translate(_AR_DIGITS).strip()


def _ar_after(said: str, keywords: str) -> str:
    """What follows the media word: "اصنع صورة لثعلب في الثلج" -> "ثعلب في الثلج".
    Keeps the presenter's own words (diacritics and all)."""
    m = re.search(rf"(?:{keywords})[ً-ْـ]*\s*(.*)$", said, re.S)
    rest = (m.group(1) if m else "").strip()
    rest = re.sub(r"^(?:عن|من|حول|فيها|فيه)\s+", "", rest)
    if rest.startswith("لل"):
        rest = "ال" + rest[2:]  # للقمر -> القمر
    elif re.match(r"^ل[^\sيوا]\S{1,}", rest):
        rest = rest[1:]  # لثعلب -> ثعلب (but ليلية, لون stay)
    elif rest.startswith("لـ"):
        rest = rest[2:].lstrip()
    return rest.strip(" .،")


def _ref_ar(norm: str) -> str:
    """ "الصوره 2" -> "image 2" (for LiveJobs.resolve)."""
    kinds = (
        (("صوره", "الصوره", "صور"), "image"),
        (("فيديو", "الفيديو", "مقطع"), "video"),
        (("موسيقي", "الموسيقي", "اغنيه", "لحن"), "music"),
        (("صوت", "الصوت"), "voice"),
        (("قصه", "القصه", "فيلم", "الفيلم"), "story"),
    )
    kind = next(
        (
            k
            for words, k in kinds
            if re.search(rf"(?<!\w)(?:{'|'.join(words)})(?!\w)", norm)
        ),
        "",
    )
    number = re.search(r"\d+", norm)
    if kind and number:
        return f"{kind} {number.group(0)}"
    return kind or (number.group(0) if number else "")


def _ar_handle(handle: str) -> str:
    """ "image 1" -> "الصورة 1"."""
    kind, _, number = (handle or "").partition(" ")
    name = _AR_KIND.get(kind)
    return f"{name} {number}".strip() if name else handle


def _ar_error(message: str) -> str:
    """A tool's English error in Arabic (common/i18n_ar/live.py), else as is."""
    if not message:
        return ""
    from common.i18n import tx_lang  # pylint: disable=import-outside-toplevel
    from common.i18n_ar.live import AR_TEXT  # pylint: disable=import-outside-toplevel

    text = AR_TEXT.get(message) or tx_lang("ar", message)
    return re.sub(
        r"\b(image|video|music|voice|story) (\d+)\b",
        lambda m: _ar_handle(m.group(0)),
        text,
    )


def _ref(text: str) -> str:
    match = re.search(r"(image|video|music|voice|story)\s*(\d+)", text)
    if match:
        return f"{match.group(1)} {match.group(2)}"
    if "video" in text:
        return "video"
    if any(w in text for w in ("music", "song", "track")):
        return "music"
    if any(w in text for w in ("voice", "speech")):
        return "voice"
    if "story" in text:
        return "story"
    if any(w in text for w in ("image", "picture", "edit")):
        return "image"
    return ""
