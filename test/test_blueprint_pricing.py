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
"""Story Studio's blueprint cost uses the same prices as the usage page."""

import pytest

from config import pricing
from services import story_director


def _no_fetch(*_a, **_k):
    raise AssertionError("the blueprint must never fetch the billing catalog")


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    pricing.clear_price_cache()
    monkeypatch.setattr(pricing, "_fetch_catalog_skus", _no_fetch)


def test_veo_blueprint_cost_follows_resolution():
    costs = {
        res: story_director.setup_blueprint(
            32, video_model="veo-3.1-fast-generate-001", resolution=res, one_take=True
        )
        for res in ("720p", "1080p", "4k")
    }
    for res, per_second in (("720p", 0.10), ("1080p", 0.12), ("4k", 0.30)):
        bp = costs[res]
        assert bp["resolution"] == res
        assert bp["cost"]["video"] == pytest.approx(
            bp["video_seconds"] * per_second, abs=0.01
        )


def test_omni_blueprint_cost_follows_resolution():
    prices = {}
    for res in ("360p", "720p", "1080p", "4k"):
        bp = story_director.setup_blueprint(
            32, video_model="gemini-omni-1.2-flash", resolution=res, one_take=True
        )
        assert bp["resolution"] == res
        per_second = pricing.OMNI_TOKENS_PER_SECOND[res] * 12.00 / 1e6
        output = bp["video_seconds"] * per_second
        # Plus re-reading earlier turns of a multi-turn take (input tokens).
        assert output - 0.01 <= bp["cost"]["video"] <= output * 1.3
        prices[res] = bp["cost"]["video"]
    assert prices["360p"] < prices["720p"] < prices["1080p"] < prices["4k"]


def test_long_omni_takes_pay_for_rereading_earlier_turns():
    takes = [[10, 10, 10]]
    cost = story_director.blueprint_cost(
        "gemini-omni-1.2-flash",
        "720p",
        takes,
        frames=0,
        narrated_seconds=0,
        music_on=False,
    )
    output = 30 * 5792 * 12.00 / 1e6
    reread = (10 + 20) * 5792 * 1.50 / 1e6
    assert cost["video"] == pytest.approx(round(output + reread, 2))


def test_blueprint_parts_add_up():
    cost = story_director.blueprint_cost(
        "veo-3.1-generate-001",
        "1080p",
        [[8], [8]],
        frames=2,
        narrated_seconds=16,
        music_on=True,
    )
    assert cost["video"] == pytest.approx(16 * 0.40)
    assert cost["frames"] == pytest.approx(round(2 * 1120 * 30 / 1e6, 2))
    assert cost["music"] == pytest.approx(0.06)
    assert cost["voice"] > 0
    assert cost["total"] == pytest.approx(
        cost["video"] + cost["frames"] + cost["voice"] + cost["music"], abs=0.01
    )


def test_voice_off_has_no_tts_cost():
    assert story_director.setup_blueprint(30, voice_on=False)["cost"]["voice"] == 0
    assert story_director.setup_blueprint(30, voice_on=True)["cost"]["voice"] > 0


def test_blueprint_prefers_a_cached_catalog_price(monkeypatch):
    sku = {
        "description": "Veo 3 Fast 720p Audio Video Generation",
        "serviceRegions": ["global"],
        "pricingInfo": [
            {
                "effectiveTime": "now",
                "pricingExpression": {
                    "baseUnitConversionFactor": 1,
                    "tieredRates": [{"startUsageAmount": 0, "unitPrice": {"units": 1}}],
                },
            }
        ],
    }
    monkeypatch.setattr(pricing, "_fetch_catalog_skus", lambda service=None: [sku])
    pricing._get_catalog_skus(pricing.VERTEX_SERVICE)  # warm the cache
    monkeypatch.setattr(pricing, "_fetch_catalog_skus", _no_fetch)
    bp = story_director.setup_blueprint(
        32, video_model="veo-3.1-fast-generate-001", resolution="720p", one_take=True
    )
    assert bp["cost"]["video"] == pytest.approx(bp["video_seconds"] * 1.0)
