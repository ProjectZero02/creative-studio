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
"""App-wide admin settings: the "Show demos" switch and the side menu."""

import pytest

from common import app_settings


@pytest.fixture
def local_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "LOCAL_PATH", str(tmp_path / "app_settings.json"))
    monkeypatch.setattr(app_settings, "_local", lambda: True)
    app_settings.clear_cache()
    yield app_settings
    app_settings.clear_cache()


def test_demos_are_hidden_by_default(local_settings):
    assert local_settings.get("show_demos") is False


def test_set_value_saves_and_refreshes(local_settings):
    local_settings.set_value("show_demos", True)
    assert local_settings.get("show_demos") is True
    local_settings.clear_cache()
    assert local_settings.get("show_demos") is True  # read back from the file


def test_unknown_setting_is_refused(local_settings):
    with pytest.raises(KeyError):
        local_settings.set_value("nope", 1)


def test_side_menu_hides_demo_group(local_settings):
    from components import side_nav
    from config.default import get_welcome_page_config

    demos = [p for p in get_welcome_page_config() if p.get("group") == side_nav.DEMO_GROUP]
    assert {p["display"] for p in demos} >= {"Fashion", "Interiors", "Product 360", "Brand kit"}


def test_old_saved_demo_switch_is_reset_once(local_settings):
    import json

    with open(local_settings.LOCAL_PATH, "w", encoding="utf-8") as f:
        json.dump({"show_demos": True}, f)  # saved before settings_version
    assert local_settings.get("show_demos") is False
    local_settings.set_value("show_demos", True)  # an admin turns it on again
    local_settings.clear_cache()
    assert local_settings.get("show_demos") is True
