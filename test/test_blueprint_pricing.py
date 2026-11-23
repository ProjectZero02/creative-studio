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
"""Story Studio's blueprint cost works with dynamic catalog pricing."""

from config import pricing
from services import story_director


def _no_fetch(*_a, **_k):
    raise AssertionError("the blueprint must never fetch the billing catalog")


def test_blueprint_uses_list_prices_without_a_cached_catalog(monkeypatch):
    pricing.clear_price_cache()
    monkeypatch.setattr(pricing, "_fetch_catalog_skus", _no_fetch)
    bp = story_director.setup_blueprint(30, video_model="veo-3.1-fast-generate-001")
    assert bp["cost"]["video"] > 0
    assert bp["cost"]["total"] > 0


def test_blueprint_prefers_a_cached_catalog_price(monkeypatch):
    pricing.clear_price_cache()
    monkeypatch.setattr(pricing, "_fetch_catalog_skus", _no_fetch)
    monkeypatch.setattr(
        pricing,
        "cached_unit_rate",
        lambda model, kind: pricing.UnitRate(1.0, "s", "now") if kind == "video" else None,
    )
    bp = story_director.setup_blueprint(30, video_model="veo-3.1-fast-generate-001")
    seconds = bp["cost"]["video"]
    assert seconds == round(seconds)  # 1.0 per second, so whole dollars
    assert seconds >= 20


def test_cached_unit_rate_never_fetches(monkeypatch):
    pricing.clear_price_cache()
    monkeypatch.setattr(pricing, "_fetch_catalog_skus", _no_fetch)
    assert pricing.cached_unit_rate("veo-3.1", "video") is None
