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
"""Each usage event says where it ran and what each SKU cost."""

import pytest

from common import analytics, usage
from config import pricing


def _sku(description, usd, regions=("global",)):
    return {
        "description": description,
        "serviceRegions": list(regions),
        "pricingInfo": [
            {
                "effectiveTime": "2026-11-25T00:00:00Z",
                "pricingExpression": {
                    "baseUnitConversionFactor": 1,
                    "tieredRates": [
                        {
                            "startUsageAmount": 0,
                            "unitPrice": {
                                "units": int(usd),
                                "nanos": round((usd % 1) * 1e9),
                            },
                        }
                    ],
                },
            }
        ],
    }


def _catalog(monkeypatch, skus):
    pricing.clear_price_cache()
    monkeypatch.setattr(pricing, "_fetch_catalog_skus", lambda service=None: skus)


def test_event_has_env_project_location_event_id_and_cost_by_sku(monkeypatch):
    monkeypatch.setenv("K_SERVICE", "creative-studio")
    units = {"prompt_tokens": 1000, "candidates_tokens": 500}
    e = usage.event(
        "a@x",
        "gemini-3.5-flash",
        "success",
        units,
        event_id="e1",
        project="p1",
        location="global",
        fetch=False,
    )
    assert e["event_id"] == "e1" and e["env"] == "creative-studio"
    assert e["project"] == "p1" and e["location"] == "global"
    assert e["billing_units"] == units
    assert e["cost_by_sku"] == {
        "Gemini 3.5 Flash Global Text Input": pytest.approx(0.0015),
        "Gemini 3.5 Flash Global Text Output": pytest.approx(0.0045),
    }
    assert sum(e["cost_by_sku"].values()) == pytest.approx(e["cost"])


def test_env_is_local_off_cloud_run(monkeypatch):
    monkeypatch.delenv("K_SERVICE", raising=False)
    assert usage.event("a@x", "lyria-002", "success", fetch=False)["env"] == "local"


def test_place_comes_from_config_per_model():
    project, location = usage.place_for("gemini-omni-1.2-flash")
    from config.default import Default

    assert location == Default().OMNI_LOCATION
    assert usage.place_for("lyria-3-pro")[1] == "global"


def test_cost_by_sku_for_every_kind():
    cases = [
        ("veo-3.1-fast-generate-001", {"video_seconds_generated": 4}),
        ("lyria-002", {"sample_count": 2}),
        ("chirp-3-hd", {"characters_synthesized": 1000}),
        ("gemini-omni-1.2-flash", {"video_seconds_generated": 4, "resolution": "360p"}),
        ("gemini-3.8-flash-tts", {"characters_synthesized": 400, "audio_seconds": 10}),
    ]
    for model, units in cases:
        cost, details = pricing.estimate_details(model, units, fetch=False)
        assert cost > 0, model
        assert details["cost_by_sku"], model
        assert sum(details["cost_by_sku"].values()) == pytest.approx(cost, rel=1e-4)


def test_failed_call_has_no_cost_by_sku():
    _, details = pricing.estimate_details("lyria-002", {}, "failure")
    assert details["cost_by_sku"] == {}


def test_track_model_call_passes_project_and_location(monkeypatch):
    seen = {}
    monkeypatch.setattr(usage, "record", lambda *a, **k: seen.update(k))
    with analytics.track_model_call("lyria-002") as ctx:
        ctx["project"], ctx["location"] = "p2", "europe-west4"
    assert seen["project"] == "p2" and seen["location"] == "europe-west4"
    assert seen["event_id"] == ctx["event_id"]


# Regional SKUs -------------------------------------------------------------


def test_regional_sku_is_picked_for_the_location(monkeypatch):
    _catalog(
        monkeypatch,
        [
            _sku("Count of samples for Lyria2 music generation model", 0.05),
            _sku(
                "Count of samples for Lyria2 music generation model",
                0.07,
                regions=("europe-west4",),
            ),
        ],
    )
    eu, _ = pricing.estimate_details(
        "lyria-002", {"sample_count": 1}, location="europe-west4"
    )
    us, _ = pricing.estimate_details(
        "lyria-002", {"sample_count": 1}, location="us-central1"
    )
    assert eu == pytest.approx(0.07)
    assert us == pytest.approx(0.05)  # no us-central1 SKU: global


def test_no_matching_region_or_global_falls_back_to_the_book(monkeypatch):
    _catalog(
        monkeypatch,
        [
            _sku(
                "Count of samples for Lyria2 music generation model",
                0.07,
                regions=("europe-west4",),
            )
        ],
    )
    cost, details = pricing.estimate_details(
        "lyria-002", {"sample_count": 1}, location="us-central1"
    )
    assert cost == pytest.approx(0.06) and details["pricing_status"] == "list"


def test_cost_by_sku_uses_the_catalog_description(monkeypatch):
    _catalog(monkeypatch, [_sku("Veo 3 Fast Video 720p Generation", 0.09)])
    _, details = pricing.estimate_details(
        "veo-3.1-fast-generate-001",
        {"video_seconds_generated": 2, "generate_audio": False},
    )
    assert details["cost_by_sku"] == {
        "Veo 3 Fast Video 720p Generation": pytest.approx(0.18)
    }


# Mock mode -----------------------------------------------------------------


def test_mock_mode_records_no_usage_event(monkeypatch):
    monkeypatch.setenv("GENMEDIA_MOCK_GENERATION", "true")
    monkeypatch.setenv("APP_ENV", "local")
    calls = []
    monkeypatch.setattr(usage, "record", lambda *a, **k: calls.append(a))
    from common import auto_enhance, lang_detect

    lang_detect._translate.cache_clear()
    assert lang_detect.english_for_model("مرحبا بالعالم") == "مرحبا بالعالم"
    assert (
        auto_enhance.enhance_on_send("a cat", "make it rich", enabled=True) == "a cat"
    )
    assert calls == []
