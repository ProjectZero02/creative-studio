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
* **Screen tools** (open_page, show_job, download, end_call) run in the
  browser: the server sends ``{"type": "ui", ...}`` and waits for the result.

``LiveCall`` holds no Gemini session itself; the router wires it to one, and
the offline :class:`ScriptedAgent` drives it the same way for tests and demos
without a model.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from google.genai import types

from services.live_jobs import DONE, FAILED, JobLimitError, LiveJob, LiveJobs

Send = Callable[[dict], Awaitable[None]]

PAGES = {
    "home": "/home",
    "image": "/nano-banana",
    "video": "/veo",
    "music": "/lyria",
    "voice": "/voice",
    "story": "/story",
    "library": "/library_v2",
}
JOB_PAGE = {"image": "/nano-banana", "video": "/veo"}
UI_TIMEOUT_S = 10.0

SYSTEM_PROMPT = """You are the voice of GenMedia Studio, a creative studio built on Google's media models. You run the app for the presenter while an audience watches the screen.

How you talk:
- Short and warm. One sentence per reply, two at most. Never read out URLs, ids or long prompts.
- Confirm and move on: "On it, starting the fox image." Never wait in silence for a job.
- When a job finishes you get its result. Say so in a few words at the next pause, e.g. "Image 1 is ready." Do not open it unless asked or nothing else is happening on screen.

How you work:
- Use generate_image, edit_image and generate_video. They run in the background, so start several at once when asked ("while that runs, make a video...").
- Write rich prompts for the models from what the presenter says: subject, style, lighting, camera. Keep their words and intent.
- Jobs have short names: "image 1", "video 1". "The image" means the latest image unless the presenter says otherwise. Say which one you act on.
- edit_image needs a finished image. If it is still rendering, say so and offer to edit it once it is ready.
- Use show_job to bring a result on screen, open_page to move between studios, download to save a file to the presenter's computer, and end_call when they say goodbye.
- If a job fails, say why in plain words and offer to retry.
- Only do media tasks in this app. Politely decline anything else."""


def _schema(props: dict[str, tuple[str, str]], required: list[str]) -> types.Schema:
    return types.Schema(
        type="OBJECT",
        properties={
            name: types.Schema(type=kind, description=desc)
            for name, (kind, desc) in props.items()
        },
        required=required,
    )


def tool_declarations(async_tools: bool = True) -> list[types.Tool]:
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
                        "aspect_ratio": (
                            "STRING",
                            "1:1, 16:9, 9:16, 4:3 or 3:4. Default 1:1.",
                        ),
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
                        "aspect_ratio": ("STRING", "16:9 or 9:16. Default 16:9."),
                    },
                    ["prompt"],
                    job,
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
                    {"page": ("STRING", "One of: " + ", ".join(PAGES))},
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
                    "end_call",
                    "Hang up when the presenter says goodbye.",
                    behavior=screen,
                ),
            ]
        )
    ]


def page_params(job: LiveJob) -> dict:
    """Query params so the studio shows the same model and input as the job."""
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

    def __init__(self, owner: str, send: Send, jobs: LiveJobs):
        self.owner = owner
        self.send = send
        self.jobs = jobs
        self.screen = "/home"
        self.ended = False
        self._waiters: dict[str, asyncio.Future] = {}

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
    ) -> Deferred:
        job = self.jobs.submit(
            self.owner, kind, prompt, aspect_ratio=aspect_ratio, source=source
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

    async def _tool_end_call(self) -> dict:
        self.ended = True
        await self.ui("end_call", {}, wait=False)
        return {"ok": True}

    # -- job results ------------------------------------------------------

    @staticmethod
    def job_result(job: LiveJob) -> dict:
        if job.status == DONE:
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

    def __init__(self, call: LiveCall, say: Callable[[str], Awaitable[None]]):
        self.call = call
        self.say = say

    async def handle(self, text: str) -> None:
        said = (text or "").strip()
        low = said.lower()
        if not low:
            return
        if any(w in low for w in ("bye", "hang up", "end call")):
            await self.say("Thanks, talk soon.")
            await self.call.run_tool("end_call", {})
        elif "download" in low:
            out = await self.call.run_tool("download", {"job": _ref(low)})
            await self.say(out.get("error") or f"Downloading {out['downloaded']}.")
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
                "Offline mode understands: image of…, video of…, edit…, show image 1, download, open video."
            )

    async def _started(self, out: dict | Deferred, verb: str) -> None:
        if isinstance(out, Deferred):
            await self.say(f"{verb}: {out.job.handle}.")
        else:
            await self.say(out.get("error", "Done."))

    async def on_job_done(self, job: LiveJob) -> None:
        if job.status == DONE:
            await self.say(f"{job.handle.capitalize()} is ready.")
        else:
            await self.say(f"{job.handle.capitalize()} failed: {job.error}")


def _ref(text: str) -> str:
    match = re.search(r"(image|video)\s*(\d+)", text)
    if match:
        return f"{match.group(1)} {match.group(2)}"
    if "video" in text:
        return "video"
    if any(w in text for w in ("image", "picture", "edit")):
        return "image"
    return ""
