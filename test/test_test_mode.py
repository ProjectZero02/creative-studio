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
"""Test Mode: per-admin switch that stops paid generation."""

import pytest

from common import app_settings, mock_generation, test_mode, usage
from common.error_handling import GenerationError


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """App settings in a temp JSON file, with no server-wide mock mode."""
    monkeypatch.setattr(app_settings, "LOCAL_PATH", str(tmp_path / "s.json"))
    monkeypatch.setattr(app_settings, "_local", lambda: True)
    monkeypatch.setattr(test_mode, "forced", lambda: False)
    monkeypatch.delenv("GENMEDIA_MOCK_GENERATION", raising=False)
    app_settings.clear_cache()
    test_mode.clear_cache()
    yield
    app_settings.clear_cache()
    test_mode.clear_cache()


def test_off_by_default(settings_file):
    assert not test_mode.is_on_for("admin@example.test")
    with usage.acting_for("admin@example.test"):
        assert not test_mode.user_on()
        assert not mock_generation.mock_enabled()
        test_mode.guard()  # no raise


def test_on_for_one_person_only(settings_file):
    test_mode.set_for("Admin@Example.test", True)
    assert test_mode.is_on_for("admin@example.test")
    assert not test_mode.is_on_for("other@example.test")
    with usage.acting_for("admin@example.test"):
        assert mock_generation.mock_enabled()
        with pytest.raises(test_mode.TestModeBlocked):
            test_mode.guard()
    with usage.acting_for("other@example.test"):
        assert not mock_generation.mock_enabled()
        test_mode.guard()


def test_turn_off_again(settings_file):
    test_mode.set_for("admin@example.test", True)
    test_mode.set_for("admin@example.test", False)
    assert not test_mode.is_on_for("admin@example.test")


def test_setting_keeps_other_settings(settings_file):
    app_settings.set_value("show_demos", True)
    test_mode.set_for("admin@example.test", True)
    app_settings.clear_cache()
    assert app_settings.get("show_demos") is True
    assert app_settings.get("test_mode_users") == ["admin@example.test"]


def test_blocked_is_a_generation_error(settings_file):
    assert issubclass(test_mode.TestModeBlocked, GenerationError)
    assert "Test Mode" in str(test_mode.TestModeBlocked())


def test_forced_counts_for_everyone(monkeypatch):
    monkeypatch.setattr(test_mode, "forced", lambda: True)
    assert test_mode.is_on_for("anyone@example.test")
    assert test_mode.is_on_for("")


def test_genai_guard_blocks_requests(settings_file):
    from google.genai import _api_client

    test_mode.install_guard()
    assert getattr(_api_client.BaseApiClient.request, "_test_mode_guard", False)
    test_mode.set_for("admin@example.test", True)

    class Fake:
        pass

    with usage.acting_for("admin@example.test"):
        with pytest.raises(test_mode.TestModeBlocked):
            _api_client.BaseApiClient.request(Fake(), "post", "x", {})


def test_story_jobs_refuse_paid_steps(settings_file, monkeypatch):
    from services import story_jobs

    monkeypatch.setattr(story_jobs, "is_mock_mode", lambda: False)
    test_mode.set_for("admin@example.test", True)
    with pytest.raises(test_mode.TestModeBlocked):
        story_jobs._refuse_in_test_mode("admin@example.test", "clips")
    story_jobs._refuse_in_test_mode("admin@example.test", "export")
    story_jobs._refuse_in_test_mode("other@example.test", "clips")
