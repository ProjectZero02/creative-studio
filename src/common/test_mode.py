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
"""Test Mode: an admin uses the real studio without paying for generation.

An admin turns it on for their own account (Settings > Admin, or the green
Test Mode pill under a page title). While it is on, that person still sees
and edits all their real media, but:

* pages that have a placeholder path (Image, Video, Music, Voice, chat and
  prompt helpers) return placeholder results, through ``mock_enabled()``;
* Film Studio steps that generate media are refused with a short message;
* as a backstop, every Google Gen AI, Lyria and Text-to-Speech call made for
  that person raises :class:`TestModeBlocked` before it leaves the server.

Who the work is for comes from the page state (the signed-in email) or, in
worker threads, from ``usage.acting_for`` / ``usage.in_context``.

The list of people with Test Mode on is the ``test_mode_users`` app setting.
It is read with a very short cache, so turning it on takes effect on every
server instance within a few seconds.

Local runs started in mock mode (``GENMEDIA_MOCK_GENERATION`` or Story
Studio demo mode) are always in Test Mode and cannot turn it off.
"""

from __future__ import annotations

import functools
import logging
import threading
import time

from common.error_handling import GenerationError

logger = logging.getLogger(__name__)

SETTING = "test_mode_users"
CACHE_SECONDS = 3.0
MESSAGE = "Test Mode is on, so nothing new is generated. Turn it off to generate."

_lock = threading.Lock()
_cache: tuple[float, frozenset[str]] | None = None


class TestModeBlocked(GenerationError):
    """A paid call was stopped because Test Mode is on."""

    __test__ = False  # not a pytest test class

    def __init__(self, message: str = MESSAGE):
        super().__init__(message)


def _norm(email: str | None) -> str:
    return (email or "").strip().lower()


def forced() -> bool:
    """True when the whole server runs in mock mode (local runs only)."""
    from common.mock_generation import env_mock_enabled

    if env_mock_enabled():
        return True
    try:
        from services.story_service import is_mock_mode

        return is_mock_mode()
    except Exception:  # pylint: disable=broad-except
        return False


def users() -> frozenset[str]:
    """Emails with Test Mode on (fresh within a few seconds)."""
    global _cache
    with _lock:
        if _cache and time.monotonic() - _cache[0] < CACHE_SECONDS:
            return _cache[1]
    try:
        from common import app_settings

        stored = app_settings.read_fresh().get(SETTING) or []
        value = frozenset(_norm(e) for e in stored if _norm(e))
    except Exception:  # pylint: disable=broad-except
        logger.warning("test_mode: could not read the setting", exc_info=True)
        # Keep the last known list rather than dropping everyone out of
        # Test Mode because of one failed read.
        with _lock:
            return _cache[1] if _cache else frozenset()
    with _lock:
        _cache = (time.monotonic(), value)
    return value


def is_on_for(email: str | None) -> bool:
    """Test Mode is on for this person (or for the whole server)."""
    if forced():
        return True
    email = _norm(email)
    return bool(email) and email in users()


def current_email() -> str:
    """Who the current work is for: the page's user, else the usage owner."""
    try:
        import mesop as me  # pylint: disable=import-outside-toplevel

        from state.state import AppState  # pylint: disable=import-outside-toplevel

        email = me.state(AppState).user_email
        if email:
            return str(email)
    except Exception:  # pylint: disable=broad-except
        pass
    try:
        from common import usage

        return usage.current_owner()
    except Exception:  # pylint: disable=broad-except
        return ""


def user_on() -> bool:
    """Test Mode is on for the person this work is for (not counting forced)."""
    email = _norm(current_email())
    return bool(email) and email in users()


def active() -> bool:
    """Test Mode applies to the current work."""
    return forced() or user_on()


def set_for(email: str, on: bool) -> None:
    """Turn Test Mode on or off for one person."""
    global _cache
    from common import app_settings

    email = _norm(email)
    if not email:
        return
    current = set(app_settings.read_fresh().get(SETTING) or [])
    current = {_norm(e) for e in current if _norm(e)}
    if on:
        current.add(email)
    else:
        current.discard(email)
    app_settings.set_value(SETTING, sorted(current))
    with _lock:
        _cache = None


def guard(what: str = "") -> None:
    """Raise :class:`TestModeBlocked` when Test Mode applies to this work."""
    if user_on():
        logger.info(
            "Test Mode: blocked %s for %s", what or "a paid call", current_email()
        )
        raise TestModeBlocked()


def clear_cache() -> None:
    global _cache
    with _lock:
        _cache = None


# ---------------------------------------------------------------------------
# Backstop: stop paid client calls for people in Test Mode
# ---------------------------------------------------------------------------

_installed = False


def _wrap_sync(fn, what):
    @functools.wraps(fn)
    def run(*args, **kwargs):
        guard(what)
        return fn(*args, **kwargs)

    run._test_mode_guard = True  # type: ignore[attr-defined]
    return run


def _wrap_async(fn, what):
    @functools.wraps(fn)
    async def run(*args, **kwargs):
        guard(what)
        return await fn(*args, **kwargs)

    run._test_mode_guard = True  # type: ignore[attr-defined]
    return run


def _wrap_async_cm(fn, what):
    """For async context managers such as ``client.aio.live.connect``."""

    @functools.wraps(fn)
    def run(*args, **kwargs):
        guard(what)
        return fn(*args, **kwargs)

    run._test_mode_guard = True  # type: ignore[attr-defined]
    return run


def _patch(owner, name: str, wrapper, what: str) -> None:
    fn = getattr(owner, name, None)
    if fn is None or getattr(fn, "_test_mode_guard", False):
        return
    setattr(owner, name, wrapper(fn, what))


def install_guard() -> None:
    """Patch the Google client libraries once per process."""
    global _installed
    if _installed:
        return
    _installed = True
    try:
        from google.genai import _api_client

        api = _api_client.BaseApiClient
        _patch(api, "request", _wrap_sync, "a Gen AI call")
        _patch(api, "request_streamed", _wrap_sync, "a Gen AI call")
        _patch(api, "async_request", _wrap_async, "a Gen AI call")
        _patch(api, "async_request_streamed", _wrap_async, "a Gen AI call")
    except Exception:  # pylint: disable=broad-except
        logger.warning("test_mode: could not guard google.genai", exc_info=True)
    try:
        from google.genai import live

        _patch(live.AsyncLive, "connect", _wrap_async_cm, "a Live session")
    except Exception:  # pylint: disable=broad-except
        logger.warning("test_mode: could not guard google.genai live", exc_info=True)
    try:
        from google.cloud import texttospeech, texttospeech_v1beta1

        for mod in (texttospeech, texttospeech_v1beta1):
            for name in ("synthesize_speech", "streaming_synthesize"):
                _patch(
                    mod.TextToSpeechClient, name, _wrap_sync, "a Text-to-Speech call"
                )
            _patch(
                mod.TextToSpeechLongAudioSynthesizeClient,
                "synthesize_long_audio",
                _wrap_sync,
                "a Text-to-Speech call",
            )
    except Exception:  # pylint: disable=broad-except
        logger.warning("test_mode: could not guard Text-to-Speech", exc_info=True)
    try:
        from google.cloud import aiplatform

        _patch(
            aiplatform.gapic.PredictionServiceClient,
            "predict",
            _wrap_sync,
            "a Vertex AI predict call",
        )
    except Exception:  # pylint: disable=broad-except
        logger.warning("test_mode: could not guard Vertex predict", exc_info=True)
