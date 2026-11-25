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
"""What each model call costs, for the usage page and Story Studio's estimate.

Every model the app calls has an entry in the price book below: Google's list
price (https://cloud.google.com/vertex-ai/generative-ai/pricing and
https://cloud.google.com/text-to-speech/pricing, checked 2026-11-25) and the
exact Cloud Billing Catalog SKU it is billed under. When the catalog can be
read, its current price wins ("dynamic"); otherwise the book price is used
("list"). Either way a known model is never left unpriced.

How each kind of call is billed:

* Veo: per second of output, by model, resolution and audio on/off.
* Gemini Omni (video): per token. Output video is 1,931 / 5,792 / 8,688 /
  17,376 tokens a second at 360p / 720p / 1080p / 4K; every input (prompt,
  images, and the earlier clips of a chat thread) is billed as input tokens.
  The tokens the API reports are used when present; otherwise the output is
  estimated from seconds and resolution.
* Gemini image models: per token; an image's output tokens depend on its size.
* Gemini text and Live: per token, input and output, audio at its own rate.
* Gemini TTS: per token (text in; audio out at 25 tokens a second).
* Chirp 3 HD: per character. Imagen, Lyria, Virtual Try-On: per item.

Estimates are not a bill: free tiers (Chirp's first 1M characters a month),
discounts, committed use, credits and taxes are not included. Failed calls
cost 0.
"""

from __future__ import annotations

import datetime
import json
import logging
import math
import re
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

PRICE_BOOK_DATE = "2026-11-25"
PRICE_CACHE_TTL_SECONDS = 12 * 60 * 60
CATALOG_RETRY_SECONDS = 30 * 60  # after a failed read, wait before trying again
_CATALOG_BASE_URL = "https://cloudbilling.googleapis.com/v1"
_BILLING_SCOPE = "https://www.googleapis.com/auth/cloud-billing.readonly"
VERTEX_SERVICE = "Vertex AI"
TTS_SERVICE = "Cloud Text-to-Speech API"


@dataclass(frozen=True)
class TokenRates:
    """USD per million input/output tokens."""

    input_per_million: float
    output_per_million: float
    effective_time: str


@dataclass(frozen=True)
class UnitRate:
    """USD per billing unit (a second of video, an image, a character...)."""

    price_per_unit: float
    unit: str
    effective_time: str


# ---------------------------------------------------------------------------
# Price book
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Price:
    """A list price and the exact catalog SKU description it comes from."""

    usd: float
    sku: str = ""  # catalog description; "" when the catalog has none
    service: str = VERTEX_SERVICE


# Veo: USD per second of output, by (resolution, audio).
def _veo(
    sku_720a,
    p720a,
    sku_720,
    p720,
    sku_1080a,
    p1080a,
    sku_1080,
    p1080,
    sku_4ka=None,
    p4ka=None,
    sku_4k=None,
    p4k=None,
):
    table = {
        ("720p", True): Price(p720a, sku_720a),
        ("720p", False): Price(p720, sku_720),
        ("1080p", True): Price(p1080a, sku_1080a),
        ("1080p", False): Price(p1080, sku_1080),
    }
    if p4ka is not None:
        table[("4k", True)] = Price(p4ka, sku_4ka)
        table[("4k", False)] = Price(p4k, sku_4k)
    return table


VEO_PER_SECOND: dict[str, dict[tuple[str, bool], Price]] = {
    # Veo 3.1 bills under the "Veo 3" SKUs.
    "standard": _veo(
        "Veo 3 Audio Video Generation",
        0.40,
        "Veo 3 Video Generation",
        0.20,
        "Veo 3 Audio Video Generation",
        0.40,
        "Veo 3 Video Generation",
        0.20,
        "Veo 3 4k Audio Video Generation",
        0.60,
        "Veo 3 4k Video Generation",
        0.40,
    ),
    "fast": _veo(
        "Veo 3 Fast 720p Audio Video Generation",
        0.10,
        "Veo 3 Fast Video 720p Generation",
        0.08,
        "Veo 3 Fast 1080p Audio Video Generation",
        0.12,
        "Veo 3 Fast 1080p Video Generation",
        0.10,
        "Veo 3 Fast 4k Audio Video Generation",
        0.30,
        "Veo 3 Fast 4k Video Generation",
        0.25,
    ),
    # Veo 3.1 Lite has no catalog SKU yet: list price only (720p and 1080p).
    "lite": _veo("", 0.05, "", 0.03, "", 0.08, "", 0.05),
}

# Gemini Omni output video tokens per second, by resolution.
OMNI_TOKENS_PER_SECOND = {"360p": 1931, "720p": 5792, "1080p": 8688, "4k": 17376}
# Upscale output tokens per second, by target resolution (from the step below).
OMNI_UPSCALE_TOKENS_PER_SECOND = {"720p": 2896, "1080p": 2896, "4k": 11584}
OMNI_IMAGE_INPUT_TOKENS = 1120


@dataclass(frozen=True)
class TokenModel:
    """USD per million tokens. `sku` is the catalog description prefix
    (e.g. "Gemini 4 Neon Global"); `skus` names exact SKUs where the
    catalog does not follow the "<prefix> <Modality> <Input|Output>" form."""

    input: float
    output: float
    sku: str = ""
    audio_input: float | None = None
    audio_output: float | None = None
    image_output: float | None = None
    video_output: float | None = None
    long_input: float | None = None  # prompts over LONG_CONTEXT_TOKENS
    long_output: float | None = None
    service: str = VERTEX_SERVICE
    skus: dict = field(default_factory=dict)
    # Output tokens per image, by image size, for the image models.
    image_tokens: dict = field(default_factory=dict)
    # A promotional price until a date: (YYYY-MM-DD it ends, {rate: usd}).
    promo: tuple | None = None


LONG_CONTEXT_TOKENS = 200_000
CACHED_INPUT_SHARE = 0.10  # cached prompt tokens bill at 10% of input

_PRO3 = "Gemini 3.0 Pro / 3.1 Pro / 3 Pro Image -"

TOKEN_MODELS: dict[str, TokenModel] = {
    # Text
    "gemini-4-neon": TokenModel(3.00, 15.00, "Gemini 4 Neon Global", audio_input=3.00),
    "gemini-4-hydrogen": TokenModel(
        1.50, 7.50, "Gemini 4 Hydrogen Global", audio_input=1.50
    ),
    "gemini-4-argon": TokenModel(
        4.00, 20.00, "Gemini 4 Argon Global", audio_input=4.00
    ),
    "gemini-4-carbon": TokenModel(
        4.00, 20.00, "Gemini 4 Carbon Global", audio_input=4.00
    ),
    "gemini-3.8-flash": TokenModel(
        1.50, 7.50, "Gemini 3.8 Flash Global", audio_input=1.50
    ),
    "gemini-3.7-flash": TokenModel(
        1.50, 7.50, "Gemini 3.7 Flash Global", audio_input=1.50
    ),
    "gemini-3.6-flash": TokenModel(
        1.50, 7.50, "Gemini 3.6 Flash Global", audio_input=1.50
    ),
    "gemini-3.5-flash": TokenModel(
        1.50, 9.00, "Gemini 3.5 Flash Global", audio_input=1.50
    ),
    "gemini-3.5-flash-lite": TokenModel(
        0.30, 2.50, "Gemini 3.5 Flash Lite Global", audio_input=0.30
    ),
    "gemini-3.1-flash-lite": TokenModel(
        0.25, 1.50, "Gemini 3.1 Flash Lite Global", audio_input=0.50
    ),
    "gemini-3-flash": TokenModel(0.50, 3.00, "Gemini 3 Flash", audio_input=1.00),
    "gemini-3.1-pro": TokenModel(
        2.00, 12.00, _PRO3, audio_input=2.00, long_input=4.00, long_output=18.00
    ),
    "gemini-3-pro": TokenModel(
        2.00, 12.00, _PRO3, audio_input=2.00, long_input=4.00, long_output=18.00
    ),
    "gemini-2.5-pro": TokenModel(
        1.25,
        10.00,
        "Gemini 2.5 Pro",
        audio_input=1.25,
        long_input=2.50,
        long_output=15.00,
    ),
    "gemini-2.5-flash": TokenModel(0.30, 2.50, "Gemini 2.5 Flash GA", audio_input=1.00),
    "gemini-2.5-flash-lite": TokenModel(
        0.10, 0.40, "Gemini 2.5 Flash Lite", audio_input=0.30
    ),
    # Live (voice chat)
    "gemini-3.8-live": TokenModel(
        0.75,
        4.50,
        "Gemini 3.8 Live",
        audio_input=3.00,
        audio_output=12.00,
        skus={
            "input": "Gemini 3.8 Live Text Input - Online Predictions",
            "output": "Gemini 3.8 Live Text Output - Online Predictions",
            "audio_input": "Gemini 3.8 Live Audio Input - Online Predictions",
            "audio_output": "Gemini 3.8 Live Audio Output - Online Predictions",
        },
    ),
    "gemini-3.1-flash-live": TokenModel(
        0.75, 4.50, "Gemini 3.1 Flash Live", audio_input=3.00, audio_output=12.00
    ),
    "gemini-2.5-flash-live": TokenModel(
        0.50, 2.00, "Gemini 2.5 Flash Live", audio_input=3.00, audio_output=12.00
    ),
    # Images (tokens per image by size: 0.5k / 1k / 2k / 4k)
    "gemini-nano-banana-2.1": TokenModel(
        1.50,
        7.50,
        "Gemini Nano Banana 2.1 Global",
        image_output=30.00,
        image_tokens={"1k": 1120, "2k": 1680, "4k": 3770},
    ),
    "gemini-3.1-flash-image": TokenModel(
        0.50,
        3.00,
        "Gemini 3.1 Flash Image Global",
        image_output=60.00,
        image_tokens={"0.5k": 747, "1k": 1120, "2k": 1680, "4k": 2520},
    ),
    "gemini-3.1-flash-lite-image": TokenModel(
        0.25,
        1.50,
        "Gemini 3.1 Flash Lite Image Global",
        image_output=30.00,
        image_tokens={"1k": 1120},
    ),
    "gemini-3-pro-image": TokenModel(
        2.00,
        12.00,
        _PRO3,
        image_output=120.00,
        long_input=4.00,
        long_output=18.00,
        image_tokens={"1k": 1120, "2k": 1120, "4k": 2000},
    ),
    # Video (Omni bills video output per token)
    "gemini-omni-1.2-flash": TokenModel(
        1.50, 9.00, "Gemini Omni 1.2 Global", video_output=12.00
    ),
    "gemini-omni-flash": TokenModel(
        1.50, 9.00, "Gemini Omni Flash Global", video_output=17.50
    ),
    "gemini-omni-1.1-flash": TokenModel(1.50, 9.00, "", video_output=17.50),
    # Speech (Cloud Text-to-Speech API)
    "gemini-2.5-flash-tts": TokenModel(
        0.50,
        0.0,
        audio_output=10.00,
        service=TTS_SERVICE,
        skus={
            "input": "Cloud TTS API text input token count for Gemini 2.5 Flash TTS",
            "audio_output": "Cloud TTS API audio output token count for Gemini 2.5 Flash",
        },
    ),
    "gemini-2.5-flash-lite-tts": TokenModel(
        0.50, 0.0, audio_output=10.00, service=TTS_SERVICE
    ),
    "gemini-2.5-pro-tts": TokenModel(
        1.00,
        0.0,
        audio_output=20.00,
        service=TTS_SERVICE,
        skus={
            "input": "Cloud TTS API text input token count for Gemini 2.5 Pro",
            "audio_output": "Cloud TTS API audio output token count for Gemini 2.5 Pro",
        },
    ),
    "gemini-3.1-flash-tts": TokenModel(
        1.00,
        0.0,
        audio_output=20.00,
        service=TTS_SERVICE,
        skus={
            "input": "Cloud TTS API text input token count for Gemini 3 Flash TTS",
            "audio_output": "Cloud TTS API audio output token count for Gemini 3 Flash",
        },
    ),
    "gemini-3.8-flash-tts": TokenModel(
        1.00,
        0.0,
        audio_output=18.00,
        service=TTS_SERVICE,
        skus={
            "input": "Cloud TTS API text input token count for Gemini 3.8 Flash TTS",
            "audio_output": "Cloud TTS API audio output token count for Gemini 3.8 Flash",
        },
        promo=("2027-01-01", {"input": 0.50, "audio_output": 9.00}),
    ),
    "gemini-3.8-flash-lite-tts": TokenModel(
        1.00,
        0.0,
        audio_output=12.00,
        service=TTS_SERVICE,
        skus={
            "input": "Cloud TTS API text input token count for Gemini 3.8 Flash Lite TTS",
            "audio_output": "Cloud TTS API audio output token count for Gemini 3.8 Flash Lite",
        },
        promo=("2027-01-01", {"input": 0.50, "audio_output": 6.00}),
    ),
}
TOKEN_MODELS["gemini-3.1-flash-image-preview"] = TOKEN_MODELS["gemini-3.1-flash-image"]

# Per-item models: model key -> (price, unit). Quantity comes from the call.
UNIT_MODELS: dict[str, tuple[Price, str]] = {
    "lyria-002": (
        Price(0.06, "Count of samples for Lyria2 music generation model"),
        "track",
    ),
    "lyria-3-pro": (Price(0.08, "Lyria 3 Audio Ouptut - Predictions"), "track"),
    "lyria-3-clip": (Price(0.04, "Lyria 3 Clip Audio Ouptut - Predictions"), "track"),
    "lyria-3": (Price(0.04, "Lyria 3 Clip Audio Ouptut - Predictions"), "track"),
    "virtual-try-on": (Price(0.06, "Virtual Try-On Generation (output)"), "image"),
    "imagen-4.0-generate": (Price(0.04, "Imagen 4 Generation (output)"), "image"),
    "imagen-4.0-fast-generate": (
        Price(0.02, "Imagen 4 Fast Generation (output)"),
        "image",
    ),
    "imagen-4.0-ultra-generate": (
        Price(0.06, "Imagen 4 Ultra Generation (output)"),
        "image",
    ),
    "imagen-3.0-generate": (Price(0.04, "Imagen 3 Generation (output)"), "image"),
    "imagen-3.0-fast-generate": (
        Price(0.02, "Imagen 3 Fast Generation (output)"),
        "image",
    ),
    # $30 per 1M characters after the monthly free 1M (not counted here).
    "chirp-3-hd": (
        Price(30 / 1e6, "Count of characters for Chirp3-HD voices", TTS_SERVICE),
        "character",
    ),
}

TTS_AUDIO_TOKENS_PER_SECOND = 25
TTS_CHARS_PER_TOKEN = 4  # text input tokens when the API does not report them
WAV_BYTES_PER_SECOND = 24000 * 2  # 24 kHz, 16-bit mono


# ---------------------------------------------------------------------------
# Model names
# ---------------------------------------------------------------------------


def model_key(model: str) -> str:
    """'veo-3.1-fast-generate-001' -> 'veo-3.1-fast-generate';
    'gemini-omni-1.1-flash-preview' -> 'gemini-omni-1.1-flash'."""
    m = (model or "").strip().lower().rsplit("/", 1)[-1]
    m = re.sub(r"-(preview|latest|exp)(?=-|$)", "", m)
    m = re.sub(r"-\d{2}-\d{4}$", "", m)  # dated previews
    if m in UNIT_MODELS or m in TOKEN_MODELS:  # e.g. lyria-002
        return m
    return re.sub(r"-\d{3}$", "", m)  # -001


def _veo_family(key: str) -> str:
    if "lite" in key:
        return "lite"
    if "fast" in key:
        return "fast"
    return "standard"


def _resolution(value, default: str = "720p") -> str:
    v = str(value or "").strip().lower().replace(" ", "")
    if v in ("4k", "2160p", "2160"):
        return "4k"
    if v in ("1080p", "1080"):
        return "1080p"
    if v in ("360p", "360"):
        return "360p"
    if v in ("720p", "720"):
        return "720p"
    return default


def _image_size(value) -> str:
    v = str(value or "").strip().lower()
    if v in ("512", "0.5k", "0.5"):
        return "0.5k"
    if v in ("2k", "2048"):
        return "2k"
    if v in ("4k", "4096"):
        return "4k"
    return "1k"


def kind_of(model: str, units: dict | None = None) -> str:
    """'video', 'image', 'music', 'speech', 'live' or 'text'."""
    units = units or {}
    name = (model or "").lower()
    if units.get("video_seconds_generated") or "veo" in name or "omni" in name:
        return "video"
    if "lyria" in name:
        return "music"
    if (
        units.get("characters_synthesized") is not None
        or "tts" in name
        or "chirp" in name
    ):
        return "speech"
    if "live" in name:
        return "live"
    if (
        "image" in name
        or "imagen" in name
        or "banana" in name
        or "vto" in name
        or "try-on" in name
    ):
        return "image"
    return "text"


# ---------------------------------------------------------------------------
# Cloud Billing Catalog
# ---------------------------------------------------------------------------

_lock = threading.Lock()
# service display name -> (fetched at, {normalised description: sku})
_catalogs: dict[str, tuple[float, dict[str, dict]]] = {}
_failed_at: dict[str, float] = {}


def _monotonic() -> float:
    return time.monotonic()


def clear_price_cache() -> None:
    """Forget catalog prices (tests and controlled refreshes)."""
    with _lock:
        _catalogs.clear()
        _failed_at.clear()


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _index(skus: list[dict]) -> dict[str, dict]:
    """Description -> SKU, preferring a global SKU over a regional one."""
    out: dict[str, dict] = {}
    for sku in skus:
        key = _normalise(sku.get("description", ""))
        if not key:
            continue
        regions = sku.get("serviceRegions") or []
        if key not in out or "global" in regions:
            out[key] = sku
    return out


def _catalog(service: str, fetch: bool) -> dict[str, dict] | None:
    now = _monotonic()
    with _lock:
        cached = _catalogs.get(service)
        if cached and now - cached[0] < PRICE_CACHE_TTL_SECONDS:
            return cached[1]
        if not fetch:
            return None
        failed = _failed_at.get(service)
        if failed is not None and now - failed < CATALOG_RETRY_SECONDS:
            return None
    try:
        index = _index(_fetch_catalog_skus(service))
    except Exception:
        logger.warning("Could not read the %s price catalog", service, exc_info=True)
        with _lock:
            _failed_at[service] = now
        return None
    with _lock:
        _catalogs[service] = (now, index)
        _failed_at.pop(service, None)
    return index


def _get_catalog_skus(service: str = VERTEX_SERVICE) -> list[dict]:
    """All SKUs of a billing service (cached as an index)."""
    index = _catalog(service, fetch=True) or {}
    return list(index.values())


def _fetch_catalog_skus(service: str = VERTEX_SERVICE) -> list[dict]:
    from google.auth import default
    from google.auth.transport.requests import Request

    credentials, _ = default(scopes=[_BILLING_SCOPE])
    credentials.refresh(Request())
    headers = {"Authorization": f"Bearer {credentials.token}"}
    services = _get_all("/services", headers, "services")
    # Exact name: other services (marketplace listings, "Vertex AI Search")
    # also contain the words "Vertex AI".
    match = next(
        (
            item
            for item in services
            if str(item.get("displayName", "")).strip().lower() == service.lower()
        ),
        None,
    )
    if not match or not match.get("serviceId"):
        raise RuntimeError(f"Billing service {service!r} was not found")
    return _get_all(f"/services/{match['serviceId']}/skus", headers, "skus")


def _get_all(path: str, headers: dict[str, str], field_name: str) -> list[dict]:
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
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
        rows.extend(payload.get(field_name, []))
        page_token = payload.get("nextPageToken", "")
        if not page_token:
            return rows


def sku_price(sku: dict) -> tuple[float, str] | None:
    """USD per base unit of a SKU and its effective time. A free tier
    (price 0 up to some amount) is skipped: the paid rate is returned."""
    pricing_info = sku.get("pricingInfo") or []
    if not pricing_info:
        return None
    expression = pricing_info[-1].get("pricingExpression") or {}
    rates = sorted(
        expression.get("tieredRates") or [],
        key=lambda r: float(r.get("startUsageAmount") or 0),
    )
    amounts = [
        float((r.get("unitPrice") or {}).get("units") or 0)
        + float((r.get("unitPrice") or {}).get("nanos") or 0) / 1e9
        for r in rates
    ]
    paid = [a for a in amounts if a > 0]
    if not amounts:
        return None
    amount = paid[0] if paid else amounts[0]
    conversion = float(expression.get("baseUnitConversionFactor") or 1)
    return amount / conversion, str(pricing_info[-1].get("effectiveTime", ""))


def _catalog_price(
    description: str, service: str, fetch: bool
) -> tuple[float, str] | None:
    if not description:
        return None
    index = _catalog(service, fetch)
    if not index:
        return None
    sku = index.get(_normalise(description))
    return sku_price(sku) if sku else None


def _token_sku_candidates(
    prefix: str, modality: str, direction: str, long: bool
) -> list[str]:
    """The description forms the catalog uses for "<prefix> <Modality> <Dir>"."""
    p = _normalise(prefix)
    long_part = " long" if long else ""
    stems = [f"{p} {modality} {direction}{long_part}"]
    if modality == "text" and direction == "output":
        stems.append(f"{p} text output thinking on{long_part}")
    out = []
    for stem in stems:
        out += [f"{stem} predictions", f"{stem} online predictions", stem]
    return out


# ---------------------------------------------------------------------------
# Rates
# ---------------------------------------------------------------------------

_TOKEN_RATE_FORMS = {
    "input": ("text", "input", False),
    "output": ("text", "output", False),
    "audio_input": ("audio", "input", False),
    "audio_output": ("audio", "output", False),
    "image_output": ("image", "output", False),
    "video_output": ("video", "output", False),
    "long_input": ("text", "input", True),
    "long_output": ("text", "output", True),
}


@dataclass
class _Quote:
    """Rates used for one estimate, and whether any came from the catalog."""

    dynamic: bool = False
    effective_time: str = ""


def _token_rate(
    model: TokenModel, rate: str, fetch: bool, quote: _Quote, at: float | None
) -> float | None:
    """USD per million tokens for one rate of a token model."""
    book = getattr(model, rate)
    if book is None:
        return None
    if model.promo:
        until, promo_rates = model.promo
        when = datetime.datetime.fromtimestamp(at or time.time(), datetime.UTC).date()
        if rate in promo_rates and when.isoformat() < until:
            return promo_rates[rate]
    descriptions = []
    if rate in model.skus:
        descriptions = [model.skus[rate]]
    elif model.sku:
        descriptions = _token_sku_candidates(model.sku, *_TOKEN_RATE_FORMS[rate])
    for description in descriptions:
        found = _catalog_price(description, model.service, fetch)
        if found is not None:
            quote.dynamic = True
            quote.effective_time = quote.effective_time or found[1]
            return found[0] * 1e6
    return book


def _unit_rate(price: Price, fetch: bool, quote: _Quote) -> float:
    found = _catalog_price(price.sku, price.service, fetch)
    if found is not None:
        quote.dynamic = True
        quote.effective_time = quote.effective_time or found[1]
        return found[0]
    return price.usd


def _generic_token_model(key: str, fetch: bool) -> TokenModel | None:
    """A Gemini model missing from the book, found in the catalog by name
    ("gemini-9-flash" -> "Gemini 9 Flash [Global] Text Input ...")."""
    if not key.startswith("gemini"):
        return None
    words = " ".join(key.replace(".", " ").replace("-", " ").split())
    for prefix in (f"{words} global", words):
        model = TokenModel(0.0, 0.0, prefix)
        quote = _Quote()
        rates = {}
        for rate in ("input", "output"):
            for description in _token_sku_candidates(prefix, *_TOKEN_RATE_FORMS[rate]):
                found = _catalog_price(description, VERTEX_SERVICE, fetch)
                if found is not None:
                    rates[rate] = found[0] * 1e6
                    quote.effective_time = found[1]
                    break
        if len(rates) == 2:
            return TokenModel(rates["input"], rates["output"], model.sku)
    return None


def token_model_for(model: str, fetch: bool = True) -> TokenModel | None:
    key = model_key(model)
    if key in TOKEN_MODELS:
        return TOKEN_MODELS[key]
    return _generic_token_model(key, fetch)


def get_token_rates(model: str, fetch: bool = True) -> TokenRates | None:
    """Text input/output USD per million tokens for a Gemini model."""
    spec = token_model_for(model, fetch)
    if spec is None:
        return None
    quote = _Quote()
    return TokenRates(
        _token_rate(spec, "input", fetch, quote, None),
        _token_rate(spec, "output", fetch, quote, None),
        quote.effective_time,
    )


def video_rate_per_second(
    model: str, resolution: str = "720p", audio: bool = True, fetch: bool = True
) -> float | None:
    """USD per second of output video for Veo or Gemini Omni."""
    cost, _ = estimate_details(
        model,
        {
            "video_seconds_generated": 1,
            "resolution": resolution,
            "generate_audio": audio,
        },
        fetch=fetch,
    )
    return cost


def image_cost(model: str, size: str = "1k", fetch: bool = True) -> float | None:
    """USD for one generated image (output only)."""
    cost, _ = estimate_details(
        model, {"images_generated": 1, "image_size": size}, fetch=fetch
    )
    return cost


def cached_unit_rate(model: str, kind: str) -> UnitRate | None:
    """A per-unit price without ever reading the catalog (list price unless
    the catalog is already cached). For live UI estimates."""
    if kind == "video":
        rate = video_rate_per_second(model, fetch=False)
        return UnitRate(rate, "s", "") if rate is not None else None
    if kind == "image":
        rate = image_cost(model, fetch=False)
        return UnitRate(rate, "image", "") if rate is not None else None
    found = UNIT_MODELS.get(model_key(model))
    if found:
        return UnitRate(_unit_rate(found[0], False, _Quote()), found[1], "")
    return None


# ---------------------------------------------------------------------------
# Estimates
# ---------------------------------------------------------------------------


def _n(units: dict, *names: str) -> float:
    for name in names:
        value = units.get(name)
        if value is not None:
            try:
                return float(value)
            except TypeError, ValueError:
                continue
    return 0.0


def _source(quote: _Quote) -> dict:
    if quote.dynamic:
        return {
            "pricing_status": "dynamic",
            "pricing_source": "cloud_billing_catalog",
            "pricing_effective_time": quote.effective_time,
        }
    return {"pricing_status": "list", "pricing_source": f"price_book_{PRICE_BOOK_DATE}"}


def _veo_estimate(key: str, units: dict, fetch: bool) -> tuple[float, dict]:
    family = _veo_family(key)
    table = VEO_PER_SECOND[family]
    resolution = _resolution(units.get("resolution"))
    if resolution == "360p":
        resolution = "720p"
    if resolution == "4k" and ("4k", True) not in table:
        resolution = "1080p"
    audio = units.get("generate_audio")
    audio = True if audio is None else bool(audio)
    seconds = _n(units, "video_seconds_generated")
    made = units.get("videos_generated")
    if made is not None and units.get("duration_seconds"):
        seconds = float(made) * float(units["duration_seconds"])
    quote = _Quote()
    rate = _unit_rate(table[(resolution, audio)], fetch, quote)
    return seconds * rate, {
        **_source(quote),
        "pricing_unit": "s",
        "price_per_unit": rate,
        "pricing_basis": f"{seconds:g} s at {resolution}{' with audio' if audio else ''}",
    }


def _unit_estimate(key: str, units: dict, fetch: bool) -> tuple[float, dict] | None:
    found = UNIT_MODELS.get(key)
    if not found:
        return None
    price, unit = found
    if unit == "character":
        quantity = _n(units, "characters_synthesized")
    elif unit == "image":
        quantity = _n(units, "images_generated", "sample_count", "num_images")
    else:
        quantity = _n(units, "sample_count") or 1.0
    quote = _Quote()
    rate = _unit_rate(price, fetch, quote)
    return quantity * rate, {
        **_source(quote),
        "pricing_unit": unit,
        "price_per_unit": rate,
        "pricing_basis": f"{quantity:g} {unit}",
    }


def _token_estimate(
    model: str, spec: TokenModel, units: dict, fetch: bool, at: float | None
) -> tuple[float, dict]:
    quote = _Quote()
    kind = kind_of(model, units)
    measured = True

    prompt = _n(units, "prompt_tokens") + _n(units, "tool_use_prompt_tokens")
    cached = min(_n(units, "cached_prompt_tokens"), prompt)
    audio_in = min(_n(units, "prompt_audio_tokens"), prompt)
    candidates = _n(units, "candidates_tokens")
    thoughts = _n(units, "thoughts_tokens")
    image_out = _n(units, "output_image_tokens")
    video_out = _n(units, "output_video_tokens")
    audio_out = _n(units, "output_audio_tokens")

    if kind == "speech":
        if not prompt:
            measured = False
            prompt = math.ceil(
                _n(units, "characters_synthesized") / TTS_CHARS_PER_TOKEN
            )
        if not audio_out:
            measured = False
            seconds = _n(units, "audio_seconds")
            if not seconds and units.get("audio_bytes"):
                seconds = max(0.0, _n(units, "audio_bytes") - 44) / WAV_BYTES_PER_SECOND
            audio_out = seconds * TTS_AUDIO_TOKENS_PER_SECOND
        candidates = 0.0
    elif kind == "video" and spec.video_output is not None and not video_out:
        # No token report: estimate output tokens from seconds and resolution.
        measured = False
        seconds = _n(units, "video_seconds_generated")
        resolution = _resolution(units.get("resolution"))
        if units.get("omni_mode") == "upscale":
            per_second = OMNI_UPSCALE_TOKENS_PER_SECOND.get(resolution, 2896)
        else:
            per_second = OMNI_TOKENS_PER_SECOND[resolution]
        video_out = seconds * per_second
        if not prompt:
            prompt = (
                _n(units, "input_video_seconds") * OMNI_TOKENS_PER_SECOND[resolution]
            )
            prompt += _n(units, "input_image_count") * OMNI_IMAGE_INPUT_TOKENS
    elif spec.image_output is not None and not image_out:
        images = _n(units, "images_generated", "sample_count", "num_images")
        if images:
            measured = False
            size = _image_size(units.get("image_size"))
            per_image = spec.image_tokens.get(size) or spec.image_tokens.get("1k", 1120)
            image_out = images * per_image
            candidates = max(candidates, image_out)

    text_out = max(0.0, candidates - image_out - video_out - audio_out) + thoughts
    long = prompt > LONG_CONTEXT_TOKENS and spec.long_input is not None
    r_in = _token_rate(spec, "long_input" if long else "input", fetch, quote, at)
    r_out = _token_rate(spec, "long_output" if long else "output", fetch, quote, at)
    r_audio_in = _token_rate(spec, "audio_input", fetch, quote, at) or r_in
    r_audio_out = _token_rate(spec, "audio_output", fetch, quote, at) or 0.0
    r_image_out = _token_rate(spec, "image_output", fetch, quote, at) or 0.0
    r_video_out = _token_rate(spec, "video_output", fetch, quote, at) or 0.0

    plain_in = max(0.0, prompt - cached - audio_in)
    cost = (
        plain_in * r_in
        + cached * r_in * CACHED_INPUT_SHARE
        + audio_in * r_audio_in
        + text_out * r_out
        + image_out * r_image_out
        + video_out * r_video_out
        + audio_out * r_audio_out
    ) / 1e6
    details = {
        **_source(quote),
        "pricing_basis": "reported tokens" if measured else "estimated tokens",
        "input_price_per_million": r_in,
        "output_price_per_million": r_out,
        "tokens_in": round(prompt),
        "tokens_out": round(text_out + image_out + video_out + audio_out),
    }
    if image_out:
        details["image_output_price_per_million"] = r_image_out
    if video_out:
        details["video_output_price_per_million"] = r_video_out
    if audio_out:
        details["audio_output_price_per_million"] = r_audio_out
    return cost, details


def estimate_details(
    model: str,
    units: dict | None,
    status: str = "success",
    *,
    fetch: bool = True,
    at: float | None = None,
) -> tuple[float | None, dict]:
    """The cost of one call and how it was priced. `fetch=False` never reads
    the catalog (list prices unless it is already cached)."""
    if status != "success":
        return 0.0, {"pricing_status": "not_applicable"}
    units = units or {}
    key = model_key(model)
    if key.startswith("veo"):
        return _veo_estimate(key, units, fetch)
    unit_priced = _unit_estimate(key, units, fetch)
    if unit_priced is not None:
        return unit_priced
    spec = token_model_for(model, fetch)
    if spec is not None:
        return _token_estimate(model, spec, units, fetch, at)
    return None, {"pricing_status": "unavailable"}


def estimate(
    model: str, units: dict | None, status: str = "success", *, fetch: bool = True
) -> float | None:
    """Estimated dollars for one call, or None for a model with no price."""
    return estimate_details(model, units, status, fetch=fetch)[0]
