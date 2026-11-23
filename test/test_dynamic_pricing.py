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
"""Tests for dynamic Cloud Billing token pricing."""

import pytest

from common import usage
from config import pricing


def _sku(
    description: str,
    dollars_per_million: float,
    *,
    base_unit: str = "token",
    conversion: int = 1_000_000,
) -> dict:
    return {
        "description": description,
        "pricingInfo": [
            {
                "effectiveTime": "2026-11-23T00:00:00Z",
                "pricingExpression": {
                    "baseUnit": base_unit,
                    "baseUnitConversionFactor": conversion,
                    "tieredRates": [
                        {
                            "startUsageAmount": 0,
                            "unitPrice": {
                                "currencyCode": "USD",
                                "units": int(dollars_per_million),
                                "nanos": int((dollars_per_million % 1) * 1_000_000_000),
                            },
                        }
                    ],
                },
            }
        ],
    }


def test_parse_token_rates_matches_model_input_and_output_skus():
    rates = pricing.parse_token_rates(
        "gemini-3.5-flash",
        [
            _sku("Gemini 3.5 Flash Input Token", 0.30),
            _sku("Gemini 3.5 Flash Output Token", 2.50),
        ],
    )

    assert rates is not None
    assert rates.input_per_million == pytest.approx(0.30)
    assert rates.output_per_million == pytest.approx(2.50)
    assert rates.effective_time == "2026-11-23T00:00:00Z"


def test_parse_unit_rate_matches_media_sku_and_converts_to_base_unit():
    rate = pricing.parse_unit_rate(
        "veo-3.1-fast-generate-001",
        "video",
        [_sku("Veo 3.1 Fast Video Generation", 0.15, base_unit="s", conversion=1)],
    )

    assert rate is not None
    assert rate.price_per_unit == pytest.approx(0.15)
    assert rate.unit == "s"
    assert rate.effective_time == "2026-11-23T00:00:00Z"


@pytest.mark.parametrize(
    ("model", "kind", "description", "base_unit", "conversion", "price"),
    [
        (
            "imagen-4.0-fast",
            "image",
            "Imagen 4 0 Fast Image Generation",
            "image",
            1,
            0.02,
        ),
        ("lyria-002", "music", "Lyria Music Generation Track", "track", 1, 0.06),
        ("chirp-3-hd", "speech", "Chirp 3 HD Characters", "character", 1_000_000, 30.0),
    ],
)
def test_parse_unit_rate_supports_image_music_and_speech(
    model, kind, description, base_unit, conversion, price
):
    rate = pricing.parse_unit_rate(
        model,
        kind,
        [_sku(description, price, base_unit=base_unit, conversion=conversion)],
    )

    assert rate is not None
    assert rate.price_per_unit == pytest.approx(price / conversion)


def test_parse_unit_rate_rejects_a_media_sku_with_the_wrong_billing_unit():
    rate = pricing.parse_unit_rate(
        "lyria-002",
        "music",
        [_sku("Lyria Music Generation Seconds", 0.01, base_unit="s", conversion=1)],
    )

    assert rate is None


def test_media_estimate_uses_dynamic_unit_rate(monkeypatch):
    monkeypatch.setattr(
        pricing,
        "get_unit_rate",
        lambda model, kind: pricing.UnitRate(0.15, "s", "2026-11-23T00:00:00Z"),
    )

    assert pricing.estimate(
        "veo-3.1-fast-generate", {"video_seconds_generated": 8}
    ) == pytest.approx(1.2)


def test_dynamic_media_rate_is_stored_with_the_usage_event(monkeypatch):
    monkeypatch.setattr(
        pricing,
        "get_unit_rate",
        lambda model, kind: pricing.UnitRate(0.15, "s", "2026-11-23T00:00:00Z"),
    )

    recorded = usage.event(
        "a@x",
        "veo-3.1-fast-generate",
        "success",
        {"video_seconds_generated": 8},
    )

    assert recorded["pricing_status"] == "dynamic"
    assert recorded["pricing_unit"] == "s"
    assert recorded["price_per_unit"] == pytest.approx(0.15)


def test_missing_dynamic_media_price_does_not_use_static_rate_card(monkeypatch):
    monkeypatch.setattr(pricing, "get_unit_rate", lambda model, kind: None)

    assert (
        pricing.estimate("veo-3.1-fast-generate", {"video_seconds_generated": 8})
        is None
    )


def test_dynamic_prices_are_cached_for_twelve_hours(monkeypatch):
    calls = []
    rates = pricing.TokenRates(0.30, 2.50, "2026-11-23T00:00:00Z")
    clock = [100.0]
    monkeypatch.setattr(
        pricing, "_fetch_token_rates", lambda model: calls.append(model) or rates
    )
    monkeypatch.setattr(pricing, "_monotonic", lambda: clock[0])
    pricing.clear_price_cache()

    assert pricing.get_token_rates("gemini-3.5-flash") == rates
    clock[0] += pricing.PRICE_CACHE_TTL_SECONDS - 1
    assert pricing.get_token_rates("gemini-3.5-flash") == rates
    clock[0] += 1
    assert pricing.get_token_rates("gemini-3.5-flash") == rates
    assert calls == ["gemini-3.5-flash", "gemini-3.5-flash"]


def test_models_share_the_cached_catalog(monkeypatch):
    calls = []
    clock = [100.0]
    monkeypatch.setattr(
        pricing,
        "_fetch_catalog_skus",
        lambda: (
            calls.append(True)
            or [
                _sku("Gemini 3.5 Flash Input Token", 0.30),
                _sku("Gemini 3.5 Flash Output Token", 2.50),
            ]
        ),
    )
    monkeypatch.setattr(pricing, "_monotonic", lambda: clock[0])
    pricing.clear_price_cache()

    pricing._get_catalog_skus()
    pricing._get_catalog_skus()

    assert calls == [True]


def test_missing_dynamic_price_does_not_use_static_rate_card(monkeypatch):
    monkeypatch.setattr(pricing, "get_token_rates", lambda model: None)

    assert (
        pricing.estimate(
            "gemini-3.5-flash",
            {"prompt_tokens": 1_000_000, "candidates_tokens": 1_000_000},
        )
        is None
    )

    recorded = usage.event(
        "a@x",
        "gemini-3.5-flash",
        "success",
        {"prompt_tokens": 1_000_000, "candidates_tokens": 1_000_000},
    )
    assert recorded["cost"] is None
    assert recorded["pricing_status"] == "unavailable"


def test_catalog_fetch_uses_application_default_credentials(monkeypatch):
    requested_scopes = []
    calls = []

    class Credentials:
        token = "oauth-token"

        def refresh(self, request):
            calls.append(("refresh", request))

    monkeypatch.setattr(
        "google.auth.default",
        lambda scopes: (requested_scopes.extend(scopes) or Credentials(), "project"),
    )

    def fake_get_all(path, headers, field):
        calls.append((path, headers, field))
        if field == "services":
            return [{"displayName": "Vertex AI", "serviceId": "vertex-service"}]
        return [
            _sku("Gemini 3.5 Flash Input Token", 0.30),
            _sku("Gemini 3.5 Flash Output Token", 2.50),
        ]

    monkeypatch.setattr(pricing, "_get_all", fake_get_all)
    pricing.clear_price_cache()

    rates = pricing._fetch_token_rates("gemini-3.5-flash")

    assert rates.input_per_million == pytest.approx(0.30)
    assert requested_scopes == [
        "https://www.googleapis.com/auth/cloud-billing.readonly"
    ]
    assert calls[1][0] == "/services"
    assert calls[2][0] == "/services/vertex-service/skus"
    assert calls[1][1]["Authorization"] == "Bearer oauth-token"


def test_dynamic_rates_are_stored_with_the_usage_event(monkeypatch):
    monkeypatch.setattr(
        pricing,
        "get_token_rates",
        lambda model: pricing.TokenRates(0.30, 2.50, "2026-11-23T00:00:00Z"),
    )

    recorded = usage.event(
        "a@x",
        "gemini-3.5-flash",
        "success",
        {"prompt_tokens": 1_000_000, "candidates_tokens": 1_000_000},
    )

    assert recorded["pricing_status"] == "dynamic"
    assert recorded["pricing_source"] == "cloud_billing_catalog"
    assert recorded["pricing_effective_time"] == "2026-11-23T00:00:00Z"
    assert recorded["input_price_per_million"] == pytest.approx(0.30)
    assert recorded["output_price_per_million"] == pytest.approx(2.50)


def test_summary_reports_unpriced_events_separately(monkeypatch):
    monkeypatch.setattr(pricing, "get_token_rates", lambda model: None)
    now = 1_800_000_000.0
    events = [
        usage.event(
            "a@x",
            "gemini-3.5-flash",
            "success",
            {"prompt_tokens": 100},
            at=now,
        )
    ]

    summary = usage.summarize(events, 7, now=now)

    assert summary["total"]["unpriced"] == 1
    assert summary["total"]["cost"] is None
    assert summary["models"][0]["unpriced"] == 1
    assert summary["models"][0]["cost"] is None
    assert summary["owners"][0]["unpriced"] == 1
    assert summary["owners"][0]["cost"] is None
