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
"""Cost estimates per model call, for the usage page.

Token and media-unit prices are loaded from the Cloud Billing Catalog API.
Estimates are not a bill: discounts, committed use, credits, and taxes are not
included.

A call is priced from the billing units the model wrappers already log
(see ``common.analytics.track_model_call``): seconds of video, images,
music tracks, characters of speech, or Gemini tokens. Failed calls cost 0.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger(__name__)

PRICE_CACHE_TTL_SECONDS = 12 * 60 * 60
_CATALOG_BASE_URL = "https://cloudbilling.googleapis.com/v1"
_BILLING_SCOPE = "https://www.googleapis.com/auth/cloud-billing.readonly"
_VERTEX_AI_DISPLAY_NAME = "vertex ai"
_price_cache: dict[str, tuple[float, TokenRates]] = {}
_catalog_cache: tuple[float, list[dict]] | None = None


@dataclass(frozen=True)
class TokenRates:
    """Current list prices in USD per million input/output tokens."""

    input_per_million: float
    output_per_million: float
    effective_time: str


@dataclass(frozen=True)
class UnitRate:
    """Current list price in USD per billing unit."""

    price_per_unit: float
    unit: str
    effective_time: str


def _monotonic() -> float:
    return time.monotonic()


def clear_price_cache() -> None:
    """Clear cached catalog prices, primarily for tests and controlled refreshes."""
    global _catalog_cache
    _price_cache.clear()
    _unit_price_cache.clear()
    _catalog_cache = None


def get_token_rates(model: str) -> TokenRates | None:
    """Return dynamic token prices, refreshing the cache every twelve hours."""
    key = (model or "").lower()
    cached = _price_cache.get(key)
    now = _monotonic()
    if cached and now - cached[0] < PRICE_CACHE_TTL_SECONDS:
        return cached[1]
    try:
        rates = _fetch_token_rates(model)
    except Exception:
        logger.warning("Could not load dynamic prices for %s", model, exc_info=True)
        return None
    if rates is not None:
        _price_cache[key] = (now, rates)
    return rates


_unit_price_cache: dict[tuple[str, str], tuple[float, UnitRate]] = {}


def get_unit_rate(model: str, kind: str) -> UnitRate | None:
    """Return a dynamic media-unit price, refreshing it every twelve hours."""
    key = ((model or "").lower(), kind)
    cached = _unit_price_cache.get(key)
    now = _monotonic()
    if cached and now - cached[0] < PRICE_CACHE_TTL_SECONDS:
        return cached[1]
    try:
        rate = _fetch_unit_rate(model, kind)
    except Exception:
        logger.warning(
            "Could not load dynamic %s price for %s", kind, model, exc_info=True
        )
        return None
    if rate is not None:
        _unit_price_cache[key] = (now, rate)
    return rate


def _fetch_token_rates(model: str) -> TokenRates | None:
    return parse_token_rates(model, _get_catalog_skus())


def _fetch_unit_rate(model: str, kind: str) -> UnitRate | None:
    return parse_unit_rate(model, kind, _get_catalog_skus())


def _get_catalog_skus() -> list[dict]:
    global _catalog_cache
    now = _monotonic()
    if _catalog_cache and now - _catalog_cache[0] < PRICE_CACHE_TTL_SECONDS:
        return _catalog_cache[1]
    skus = _fetch_catalog_skus()
    _catalog_cache = (now, skus)
    return skus


def _fetch_catalog_skus() -> list[dict]:
    from google.auth import default
    from google.auth.transport.requests import Request

    credentials, _ = default(scopes=[_BILLING_SCOPE])
    credentials.refresh(Request())
    headers = {"Authorization": f"Bearer {credentials.token}"}
    services = _get_all("/services", headers, "services")
    service = next(
        (
            item
            for item in services
            if _VERTEX_AI_DISPLAY_NAME in str(item.get("displayName", "")).lower()
        ),
        None,
    )
    if not service or not service.get("serviceId"):
        raise RuntimeError("Vertex AI billing service was not found")
    return _get_all(f"/services/{service['serviceId']}/skus", headers, "skus")


def _get_all(path: str, headers: dict[str, str], field: str) -> list[dict]:
    rows = []
    page_token = ""
    while True:
        params = {"pageSize": "5000"}
        if page_token:
            params["pageToken"] = page_token
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(
            f"{_CATALOG_BASE_URL}{path}?{query}", headers=headers
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.load(response)
        rows.extend(payload.get(field, []))
        page_token = payload.get("nextPageToken", "")
        if not page_token:
            return rows


def parse_token_rates(model: str, skus: list[dict]) -> TokenRates | None:
    """Extract matching input/output token prices from public catalog SKUs."""
    model_words = _normalise(model).split()
    matches: dict[str, tuple[float, str]] = {}
    for sku in skus:
        description = _normalise(sku.get("description", ""))
        if not _model_matches(model_words, description):
            continue
        direction = _token_direction(description)
        if direction:
            price = _sku_price_per_million(sku)
            if price is not None:
                pricing_info = sku.get("pricingInfo") or []
                effective_time = str(pricing_info[-1].get("effectiveTime", ""))
                matches[direction] = (price, effective_time)
    if "input" not in matches or "output" not in matches:
        return None
    return TokenRates(
        input_per_million=matches["input"][0],
        output_per_million=matches["output"][0],
        effective_time=matches["input"][1] or matches["output"][1],
    )


def parse_unit_rate(model: str, kind: str, skus: list[dict]) -> UnitRate | None:
    """Extract a model's current price for a non-token billing unit."""
    model_words = _normalise(model).split()
    for sku in skus:
        description = _normalise(sku.get("description", ""))
        if not _model_matches(model_words, description):
            continue
        if not _unit_matches(kind, sku, description):
            continue
        price, unit = _sku_price_per_unit(sku)
        if price is None:
            continue
        pricing_info = sku.get("pricingInfo") or []
        effective_time = str(pricing_info[-1].get("effectiveTime", ""))
        return UnitRate(price, unit, effective_time)
    return None


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _model_matches(model_words: list[str], description: str) -> bool:
    description_words = set(description.split())
    ignored = {"001", "002", "003", "generate", "model", "preview"}
    for word in model_words:
        if word in ignored:
            continue
        if word not in description_words:
            return False
    return bool(model_words)


def _unit_matches(kind: str, sku: dict, description: str) -> bool:
    if "token" in description or "tokens" in description:
        return False
    base_unit = _normalise(
        (sku.get("pricingInfo") or [{}])[-1]
        .get("pricingExpression", {})
        .get("baseUnit", "")
    )
    compatible_units = {
        "video": {"s", "sec", "second", "seconds"},
        "image": {"image", "images"},
        "music": {"track", "tracks", "sample", "samples"},
        "speech": {"character", "characters", "char", "chars", "1k", "1m"},
    }
    if base_unit and base_unit not in compatible_units.get(kind, set()):
        return False
    terms = {
        "video": {"video", "second", "seconds", "veo", "s"},
        "image": {"image", "images", "imagen"},
        "music": {"music", "track", "tracks", "lyria"},
        "speech": {"speech", "character", "characters", "tts", "chirp"},
    }
    return kind in terms and bool(
        (set(description.split()) | set(base_unit.split())) & terms[kind]
    )


def _token_direction(description: str) -> str | None:
    words = set(description.split())
    if "input" in words or "prompt" in words:
        return "input"
    if "output" in words or "completion" in words:
        return "output"
    return None


def _sku_price_per_million(sku: dict) -> float | None:
    pricing_info = sku.get("pricingInfo") or []
    if not pricing_info:
        return None
    expression = pricing_info[-1].get("pricingExpression") or {}
    rates = expression.get("tieredRates") or []
    tier = next((rate for rate in rates if rate.get("startUsageAmount", 0) == 0), None)
    if not tier:
        return None
    unit_price = tier.get("unitPrice") or {}
    amount = float(unit_price.get("units", 0)) + float(unit_price.get("nanos", 0)) / 1e9
    conversion = float(expression.get("baseUnitConversionFactor") or 1)
    return amount * 1_000_000 / conversion


def _sku_price_per_unit(sku: dict) -> tuple[float | None, str]:
    pricing_info = sku.get("pricingInfo") or []
    if not pricing_info:
        return None, ""
    expression = pricing_info[-1].get("pricingExpression") or {}
    rates = expression.get("tieredRates") or []
    tier = next((rate for rate in rates if rate.get("startUsageAmount", 0) == 0), None)
    if not tier:
        return None, ""
    unit_price = tier.get("unitPrice") or {}
    amount = float(unit_price.get("units", 0)) + float(unit_price.get("nanos", 0)) / 1e9
    conversion = float(expression.get("baseUnitConversionFactor") or 1)
    return amount / conversion, str(expression.get("baseUnit") or "")


def kind_of(model: str, units: dict) -> str:
    """'video', 'image', 'music', 'speech' or 'text'."""
    name = (model or "").lower()
    if units.get("video_seconds_generated") or "veo" in name:
        return "video"
    if "lyria" in name:
        return "music"
    if units.get("characters_synthesized") is not None or "tts" in name or "chirp" in name:
        return "speech"
    if "image" in name or "imagen" in name or "vto" in name or "try-on" in name:
        return "image"
    return "text"


def estimate_details(
    model: str, units: dict | None, status: str = "success"
) -> tuple[float | None, dict]:
    """Return an estimate and the pricing metadata used to calculate it."""
    if status != "success":
        return 0.0, {"pricing_status": "not_applicable"}
    units = units or {}
    kind = kind_of(model, units)
    if kind == "text":
        rates = get_token_rates(model)
        if rates is None:
            return None, {
                "pricing_status": "unavailable",
                "pricing_source": "cloud_billing_catalog",
            }
        tokens_in = float(units.get("prompt_tokens") or 0)
        tokens_in += float(units.get("tool_use_prompt_tokens") or 0)
        tokens_out = float(units.get("candidates_tokens") or 0)
        tokens_out += float(units.get("thoughts_tokens") or 0)
        cost = (
            tokens_in / 1e6 * rates.input_per_million
            + tokens_out / 1e6 * rates.output_per_million
        )
        return cost, {
            "pricing_status": "dynamic",
            "pricing_source": "cloud_billing_catalog",
            "pricing_effective_time": rates.effective_time,
            "input_price_per_million": rates.input_per_million,
            "output_price_per_million": rates.output_per_million,
        }

    rate = get_unit_rate(model, kind)
    if rate is None:
        return None, {
            "pricing_status": "unavailable",
            "pricing_source": "cloud_billing_catalog",
        }
    quantity = {
        "video": units.get("video_seconds_generated"),
        "image": units.get("images_generated"),
        "music": units.get("sample_count"),
        "speech": units.get("characters_synthesized"),
    }[kind]
    if kind == "image" and quantity is None:
        quantity = units.get("sample_count")
    if kind == "image" and quantity is None:
        quantity = units.get("num_images")
    cost = float(quantity or 0) * rate.price_per_unit
    return cost, {
        "pricing_status": "dynamic",
        "pricing_source": "cloud_billing_catalog",
        "pricing_effective_time": rate.effective_time,
        "pricing_unit": rate.unit,
        "price_per_unit": rate.price_per_unit,
    }


def estimate(model: str, units: dict | None, status: str = "success") -> float | None:
    """Estimated dollars for one call, or ``None`` when no dynamic rate exists."""
    return estimate_details(model, units, status)[0]
