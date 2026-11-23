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

Token prices are loaded from the Cloud Billing Catalog API. The non-token
rates below remain list-price ballparks for units where the model response
does not expose token usage. Estimates are not a bill: discounts, committed
use, credits, and taxes are not included.

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


def _monotonic() -> float:
    return time.monotonic()


def clear_price_cache() -> None:
    """Clear cached catalog prices, primarily for tests and controlled refreshes."""
    global _catalog_cache
    _price_cache.clear()
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


def _fetch_token_rates(model: str) -> TokenRates | None:
    return parse_token_rates(model, _get_catalog_skus())


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
        if not model_words or not all(
            word in description.split() for word in model_words
        ):
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


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


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


# (substring of the model name, price) pairs; the first match wins.
VIDEO_PER_SECOND = (
    ("lite", 0.10),
    ("fast", 0.15),
    ("omni", 0.40),
    ("veo", 0.40),
)
IMAGE_PER_IMAGE = (
    ("imagen-4.0-fast", 0.02),
    ("imagen", 0.04),
    ("image", 0.039),  # Gemini image models (Nano Banana)
    ("vto", 0.06),
    ("virtual-try-on", 0.06),
)
MUSIC_PER_TRACK = 0.06
SPEECH_PER_MILLION_CHARS = (
    ("chirp", 30.0),
    ("tts", 10.0),
)


def _match(model: str, table):
    name = (model or "").lower()
    for key, price in table:
        if key in name:
            return price
    return None


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
    if kind == "video":
        secs = float(units.get("video_seconds_generated") or 0)
        return secs * (_match(model, VIDEO_PER_SECOND) or 0.40), {
            "pricing_status": "static",
            "pricing_source": "config_rate_card",
        }
    if kind == "image":
        count = int(units.get("sample_count") or units.get("num_images") or 1)
        return count * (_match(model, IMAGE_PER_IMAGE) or 0.04), {
            "pricing_status": "static",
            "pricing_source": "config_rate_card",
        }
    if kind == "music":
        return int(units.get("sample_count") or 1) * MUSIC_PER_TRACK, {
            "pricing_status": "static",
            "pricing_source": "config_rate_card",
        }
    if kind == "speech":
        chars = float(units.get("characters_synthesized") or 0)
        return chars / 1e6 * (_match(model, SPEECH_PER_MILLION_CHARS) or 10.0), {
            "pricing_status": "static",
            "pricing_source": "config_rate_card",
        }
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


def estimate(model: str, units: dict | None, status: str = "success") -> float | None:
    """Estimated dollars for one call, or ``None`` when no dynamic rate exists."""
    return estimate_details(model, units, status)[0]
