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


def _sku(description: str, dollars_per_million: float) -> dict:
    return {
        "description": description,
        "pricingInfo": [
            {
                "effectiveTime": "2026-11-23T00:00:00Z",
                "pricingExpression": {
                    "baseUnitConversionFactor": 1_000_000,
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
