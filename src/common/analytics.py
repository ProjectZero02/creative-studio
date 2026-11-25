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


import functools
import json
import logging
import os
import time
import uuid
from contextlib import contextmanager
from typing import Any

import mesop as me
from google.cloud import logging as cloud_logging

from state.state import AppState


class JsonFormatter(logging.Formatter):
    """Formats log records as JSON."""

    def format(self, record):
        log_object = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
            "name": record.name,
        }
        # Add extra fields if they exist
        if hasattr(record, "extra_data"):
            log_object.update(record.extra_data)
        return json.dumps(log_object)


def get_logger(name: str):
    """Creates and configures a logger."""
    logger = logging.getLogger(name)
    # Prevent duplicate logs in case of multiple calls
    if not logger.handlers:
        logger.setLevel(logging.INFO)

        # Check if we are in a Google Cloud environment (e.g., Cloud Run)
        if os.environ.get("K_SERVICE"):
            # The Google Cloud Logging handler automatically recognizes JSON fields
            # and parses them as structured logs.
            client = cloud_logging.Client()
            handler = client.get_default_handler()
        else:
            # For local development, use a standard handler with our custom JSON formatter.
            handler = logging.StreamHandler()
            handler.setFormatter(JsonFormatter())

        logger.addHandler(handler)
    return logger


# Central analytics logger
analytics_logger = get_logger("genmedia.analytics")


def extract_usage_metadata(response: Any) -> dict[str, int]:
    """Extract billable token counts from a Gemini response."""
    usage_metadata = getattr(response, "usage_metadata", None)
    if not usage_metadata:
        return {}

    fields = {
        "cached_content_token_count": "cached_prompt_tokens",
        "prompt_token_count": "prompt_tokens",
        "candidates_token_count": "candidates_tokens",
        "thoughts_token_count": "thoughts_tokens",
        "tool_use_prompt_token_count": "tool_use_prompt_tokens",
        "total_token_count": "total_tokens",
    }
    out = {
        destination: value
        for source, destination in fields.items()
        if (value := getattr(usage_metadata, source, None)) is not None
    }
    # Per-modality counts: audio input, and image/audio/video output, are
    # billed at their own rates.
    for source, prefix in (
        ("prompt_tokens_details", "prompt"),
        ("candidates_tokens_details", "output"),
    ):
        for detail in getattr(usage_metadata, source, None) or []:
            modality = getattr(detail, "modality", "") or ""
            modality = str(getattr(modality, "value", modality)).rsplit(".", 1)[-1]
            count = getattr(detail, "token_count", None)
            if count and modality.upper() in ("AUDIO", "IMAGE", "VIDEO"):
                key = f"{prefix}_{modality.lower()}_tokens"
                out[key] = out.get(key, 0) + int(count)
    return out


def extract_interaction_usage(interaction: Any) -> dict[str, int]:
    """Billable token counts from an Interactions API result (Gemini Omni)."""
    usage = getattr(interaction, "usage", None)
    if not usage:
        return {}
    out: dict[str, int] = {}
    for source, destination in (
        ("total_input_tokens", "prompt_tokens"),
        ("total_cached_tokens", "cached_prompt_tokens"),
        ("total_output_tokens", "candidates_tokens"),
        ("total_thought_tokens", "thoughts_tokens"),
        ("total_tool_use_tokens", "tool_use_prompt_tokens"),
    ):
        value = getattr(usage, source, None)
        if value is not None:
            out[destination] = int(value)
    for source, prefix in (
        ("input_tokens_by_modality", "prompt"),
        ("output_tokens_by_modality", "output"),
    ):
        for detail in getattr(usage, source, None) or []:
            modality = getattr(detail, "modality", "") or ""
            modality = str(getattr(modality, "value", modality)).rsplit(".", 1)[-1].lower()
            count = getattr(detail, "tokens", None) or getattr(detail, "token_count", None)
            if count and modality in ("audio", "image", "video"):
                key = f"{prefix}_{modality}_tokens"
                out[key] = out.get(key, 0) + int(count)
    return out


def extract_generated_image_count(response: Any) -> int:
    """Count final image parts returned by a generative response."""
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return 0
    content = getattr(candidates[0], "content", None)
    return sum(
        bool(getattr(part, "inline_data", None))
        and not getattr(part, "thought", False)
        for part in getattr(content, "parts", None) or []
    )


def log_page_view(page_name: str, session_id: str = None):
    """Logs a page view event."""
    try:
        state = me.state(AppState)
        user_email = state.user_email
    except Exception:
        user_email = "unknown"

    extra_data = {
        "event_type": "page_view",
        "page_name": page_name,
        "session_id": session_id,
        "user_email": user_email,
    }
    analytics_logger.info(f"Page view: {page_name}", extra={"extra_data": extra_data})


def log_ui_click(
    element_id: str, page_name: str, session_id: str = None, extras: dict = None,
):
    """Logs a UI click event."""
    try:
        state = me.state(AppState)
        user_email = state.user_email
    except Exception:
        user_email = "unknown"

    extra_data = {
        "event_type": "ui_click",
        "element_id": element_id,
        "page_name": page_name,
        "session_id": session_id,
        "user_email": user_email,
    }
    if extras:
        extra_data.update(extras)
    analytics_logger.info(
        f"UI Click: {element_id} on {page_name}", extra={"extra_data": extra_data},
    )


def log_model_call(
    model_name: str,
    status: str,
    duration_ms: float = 0,
    details: dict = None,
    billing_units: dict = None,
    pipeline_id: str = None,
    error: dict = None,
    count_usage: bool = True,
    event_id: str = "",
):
    """Logs a generative model call event. `count_usage=False` logs it
    without a usage event (a wrapper whose real model call is logged on
    its own)."""
    try:
        state = me.state(AppState)
        page_name = state.current_page
        session_id = state.session_id
        user_email = state.user_email
    except Exception:
        # Outside the page (threads, jobs): use who the work is for, set
        # with usage.acting_for / usage.in_context.
        from common import usage

        page_name = usage.current_page() or "unknown"
        session_id = "unknown"
        user_email = usage.current_owner() or "unknown"
    if not (details or {}).get("feature"):
        from common import usage

        if usage.current_feature():
            details = {**(details or {}), "feature": usage.current_feature()}

    extra_data = {
        "event_type": "model_call",
        "model_name": model_name,
        "status": status,  # e.g., "success", "failure"
        "duration_ms": round(duration_ms, 2),
        "page_name": page_name,
        "session_id": session_id,
        "user_email": user_email,
        "details": details or {},
    }
    if billing_units:
        extra_data["billing_units"] = billing_units
    if pipeline_id:
        extra_data["pipeline_id"] = pipeline_id
    feature = str((details or {}).get("feature") or "")
    if feature:
        extra_data["feature"] = feature
    if error:
        extra_data["error"] = error
    if event_id:
        extra_data["event_id"] = event_id

    analytics_logger.info(
        f"Model Call: {model_name} ({status})", extra={"extra_data": extra_data},
    )
    if not count_usage:
        return
    try:
        from common import usage

        usage.record(
            user_email if user_email != "unknown" else "",
            model_name,
            status,
            billing_units,
            page_name if page_name != "unknown" else "",
            str((details or {}).get("task") or ""),
            feature=feature,
            event_id=event_id,
        )
    except Exception:  # usage is best effort
        analytics_logger.warning("usage: could not queue a usage event", exc_info=True)


def track_click(element_id: str):
    """Decorator to log a UI click event on an event handler."""

    def decorator(handler_function):
        @functools.wraps(handler_function)
        def wrapper(*args, **kwargs):
            state = me.state(AppState)
            log_ui_click(
                element_id=element_id,
                page_name=state.current_page,
                session_id=state.session_id,
            )
            return handler_function(*args, **kwargs)

        return wrapper

    return decorator


def is_timeout(exc: BaseException | None) -> bool:
    """Whether an exception (or one it was raised from) is a timeout."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        name = type(exc).__name__.lower()
        if (
            isinstance(exc, TimeoutError)
            or "timeout" in name
            or "deadlineexceeded" in name
            or "timed out" in str(exc).lower()
        ):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


@contextmanager
def track_model_call(
    model_name: str, billing_units: dict = None, pipeline_id: str = None, **kwargs,
):
    """Context manager to log the duration, status, and telemetry of a model call.

    Yields a dict `ctx = {"billing_units": {...}, "details": {...}, "pipeline_id": ...,
    "event_id": ...}` which code inside the block can update dynamically.

    Set ``ctx["output_received"] = True`` right after the API returns output:
    a later exception (say, saving to GCS) is then logged as
    "failed_after_output" and priced. ``ctx["bill_on_timeout"] = True``
    around a call the server finishes even when the client gives up turns a
    timeout into "timeout_maybe_billed" (also priced).
    """
    from common.error_handling import classify_error

    count_usage = bool(kwargs.pop("count_usage", True))
    start_time = time.time()
    ctx = {
        "billing_units": billing_units or {},
        "details": kwargs,
        "pipeline_id": pipeline_id,
        "event_id": uuid.uuid4().hex,
    }
    try:
        yield ctx
        duration_ms = (time.time() - start_time) * 1000
        log_model_call(
            model_name,
            status="success",
            duration_ms=duration_ms,
            details=ctx["details"],
            billing_units=ctx["billing_units"] if ctx["billing_units"] else None,
            pipeline_id=ctx["pipeline_id"],
            count_usage=count_usage,
            event_id=ctx["event_id"],
        )
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        err_dict = classify_error(e)
        details = dict(ctx["details"])
        details["error"] = err_dict["message"]
        # Output that came back is billed even when a later step fails; a
        # client timeout on a call the server keeps running may be billed.
        status = "failure"
        if ctx.get("output_received"):
            status = "failed_after_output"
        elif ctx.get("bill_on_timeout") and is_timeout(e):
            status = "timeout_maybe_billed"
        log_model_call(
            model_name,
            status=status,
            duration_ms=duration_ms,
            details=details,
            billing_units=ctx["billing_units"] if ctx["billing_units"] else None,
            pipeline_id=ctx["pipeline_id"],
            error=err_dict,
            count_usage=count_usage,
            event_id=ctx["event_id"],
        )
        raise  # Re-raise the exception after logging
