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
"""Cost of each model call: the price book, the catalog, and the units."""

import datetime
from types import SimpleNamespace

import pytest

from common import analytics, usage
from config import pricing

# conftest stubs the catalog fetch for every test; keep the real one.
_REAL_FETCH = pricing._fetch_catalog_skus


def _sku(description, usd_per_unit, *, tiers=None, regions=("global",)):
    rates = tiers or [(0, usd_per_unit)]
    return {
        "description": description,
        "serviceRegions": list(regions),
        "pricingInfo": [
            {
                "effectiveTime": "2026-11-25T00:00:00Z",
                "pricingExpression": {
                    "baseUnit": "count",
                    "baseUnitConversionFactor": 1,
                    "tieredRates": [
                        {
                            "startUsageAmount": start,
                            "unitPrice": {
                                "units": int(price),
                                "nanos": round((price % 1) * 1e9),
                            },
                        }
                        for start, price in rates
                    ],
                },
            }
        ],
    }


def _catalog(monkeypatch, skus_by_service):
    calls = []

    def fetch(service=pricing.VERTEX_SERVICE):
        calls.append(service)
        return skus_by_service.get(service, [])

    monkeypatch.setattr(pricing, "_fetch_catalog_skus", fetch)
    pricing.clear_price_cache()
    return calls


# --- model names ---------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "key"),
    [
        ("veo-3.1-fast-generate-001", "veo-3.1-fast-generate"),
        ("gemini-omni-1.1-flash-preview", "gemini-omni-1.1-flash"),
        ("gemini-2.5-flash-lite-preview-tts", "gemini-2.5-flash-lite-tts"),
        ("lyria-3-pro-preview", "lyria-3-pro"),
        ("publishers/google/models/gemini-4-neon", "gemini-4-neon"),
    ],
)
def test_model_key(model, key):
    assert pricing.model_key(model) == key


# --- Veo: per second by resolution and audio -----------------------------


@pytest.mark.parametrize(
    ("model", "resolution", "audio", "per_second"),
    [
        ("veo-3.1-fast-generate-001", "720p", True, 0.10),
        ("veo-3.1-fast-generate-001", "720p", False, 0.08),
        ("veo-3.1-fast-generate-001", "1080p", True, 0.12),
        ("veo-3.1-fast-generate-001", "1080p", False, 0.10),
        ("veo-3.1-fast-generate-001", "4k", True, 0.30),
        ("veo-3.1-fast-generate-001", "4k", False, 0.25),
        ("veo-3.1-generate-001", "720p", True, 0.40),
        ("veo-3.1-generate-001", "1080p", True, 0.40),
        ("veo-3.1-generate-001", "4k", True, 0.60),
        ("veo-3.1-generate-001", "1080p", False, 0.20),
        ("veo-3.1-generate-001", "4k", False, 0.40),
        ("veo-3.1-lite-generate-001", "720p", True, 0.05),
        ("veo-3.1-lite-generate-001", "1080p", True, 0.08),
        ("veo-3.1-lite-generate-001", "1080p", False, 0.05),
    ],
)
def test_veo_is_priced_by_resolution_and_audio(model, resolution, audio, per_second):
    cost, details = pricing.estimate_details(
        model,
        {
            "video_seconds_generated": 8,
            "resolution": resolution,
            "generate_audio": audio,
        },
    )
    assert cost == pytest.approx(8 * per_second)
    assert details["pricing_status"] == "list"
    assert details["price_per_unit"] == pytest.approx(per_second)


def test_veo_bills_the_videos_it_returned():
    units = {
        "video_seconds_generated": 16,
        "duration_seconds": 8,
        "videos_generated": 1,
        "resolution": "720p",
        "generate_audio": True,
    }
    assert pricing.estimate("veo-3.1-fast-generate-001", units) == pytest.approx(0.8)


# --- Gemini Omni: tokens ---------------------------------------------------


@pytest.mark.parametrize(
    ("resolution", "tokens_per_second"),
    [("360p", 1931), ("720p", 5792), ("1080p", 8688), ("4k", 17376)],
)
def test_omni_estimates_output_tokens_from_seconds(resolution, tokens_per_second):
    cost, details = pricing.estimate_details(
        "gemini-omni-1.2-flash",
        {"video_seconds_generated": 10, "resolution": resolution},
    )
    assert cost == pytest.approx(10 * tokens_per_second * 12.00 / 1e6)
    assert details["pricing_basis"] == "estimated tokens"


def test_omni_720p_matches_googles_seven_cents_a_second():
    rate = pricing.video_rate_per_second("gemini-omni-1.2-flash", "720p")
    assert rate == pytest.approx(0.07, abs=0.001)


def test_omni_flash_has_its_own_video_rate():
    rate = pricing.video_rate_per_second("gemini-omni-flash-preview", "720p")
    assert rate == pytest.approx(5792 * 17.50 / 1e6)


def test_omni_uses_the_tokens_the_api_reported():
    units = {
        "video_seconds_generated": 10,
        "resolution": "720p",
        "prompt_tokens": 120_000,  # earlier clips of the chat thread
        "candidates_tokens": 60_000,
        "output_video_tokens": 60_000,
    }
    cost, details = pricing.estimate_details("gemini-omni-1.2-flash", units)
    assert cost == pytest.approx((120_000 * 1.50 + 60_000 * 12.00) / 1e6)
    assert details["pricing_basis"] == "reported tokens"


def test_omni_upscale_uses_upscale_token_rates():
    cost = pricing.estimate(
        "gemini-omni-1.2-flash",
        {"video_seconds_generated": 10, "resolution": "4k", "omni_mode": "upscale"},
    )
    assert cost == pytest.approx(10 * 11584 * 12.00 / 1e6)


# --- Gemini images: tokens by size -----------------------------------------


@pytest.mark.parametrize(
    ("model", "size", "price"),
    [
        ("gemini-nano-banana-2.1", "1K", 1120 * 30 / 1e6),
        ("gemini-nano-banana-2.1", "4K", 3770 * 30 / 1e6),
        ("gemini-3.1-flash-image", "1K", 1120 * 60 / 1e6),
        ("gemini-3.1-flash-image", "2K", 1680 * 60 / 1e6),
        ("gemini-3-pro-image", "4K", 2000 * 120 / 1e6),
    ],
)
def test_image_models_are_priced_by_size(model, size, price):
    assert pricing.estimate(
        model, {"images_generated": 1, "image_size": size}
    ) == pytest.approx(price)


def test_image_models_use_reported_image_tokens():
    units = {
        "images_generated": 1,
        "prompt_tokens": 2_000,
        "candidates_tokens": 1_220,
        "output_image_tokens": 1_120,
    }
    cost = pricing.estimate("gemini-nano-banana-2.1", units)
    assert cost == pytest.approx((2_000 * 1.5 + 100 * 7.5 + 1_120 * 30) / 1e6)


# --- Gemini text and Live --------------------------------------------------


def test_text_tokens_with_thinking_tools_cache_and_audio():
    units = {
        "prompt_tokens": 1_000_000,
        "tool_use_prompt_tokens": 500_000,
        "cached_prompt_tokens": 100_000,
        "prompt_audio_tokens": 200_000,
        "candidates_tokens": 1_000_000,
        "thoughts_tokens": 500_000,
    }
    cost = pricing.estimate("gemini-3.1-flash-lite", units)
    plain = 1_500_000 - 100_000 - 200_000
    expected = (plain * 0.25 + 100_000 * 0.025 + 200_000 * 0.50 + 1_500_000 * 1.5) / 1e6
    assert cost == pytest.approx(expected)


def test_neon_text_price():
    cost = pricing.estimate(
        "gemini-4-neon", {"prompt_tokens": 1_000_000, "candidates_tokens": 1_000_000}
    )
    assert cost == pytest.approx(18.0)


def test_long_prompts_use_long_context_rates():
    cost = pricing.estimate(
        "gemini-2.5-pro", {"prompt_tokens": 300_000, "candidates_tokens": 1_000}
    )
    assert cost == pytest.approx((300_000 * 2.5 + 1_000 * 15) / 1e6)


def test_live_bills_audio_in_and_out():
    units = {
        "prompt_tokens": 10_000,
        "prompt_audio_tokens": 8_000,
        "candidates_tokens": 6_000,
        "output_audio_tokens": 5_000,
    }
    cost = pricing.estimate("gemini-3.8-live", units)
    expected = (2_000 * 0.75 + 8_000 * 3.0 + 1_000 * 4.5 + 5_000 * 12.0) / 1e6
    assert cost == pytest.approx(expected)
    assert pricing.kind_of("gemini-3.8-live", units) == "live"


def test_unknown_model_is_unpriced_and_failures_are_free():
    cost, details = pricing.estimate_details("mystery-model", {"prompt_tokens": 5})
    assert cost is None and details["pricing_status"] == "unavailable"
    assert (
        pricing.estimate("veo-3.1-generate", {"video_seconds_generated": 8}, "failure")
        == 0
    )


# --- Speech ----------------------------------------------------------------


def test_gemini_tts_bills_text_tokens_and_audio_seconds():
    cost = pricing.estimate(
        "gemini-2.5-flash-tts",
        {"characters_synthesized": 1_000, "audio_seconds": 60},
    )
    assert cost == pytest.approx((250 * 0.50 + 60 * 25 * 10.00) / 1e6)


def test_gemini_tts_falls_back_to_wav_bytes():
    cost = pricing.estimate(
        "gemini-2.5-flash-tts",
        {"characters_synthesized": 0, "audio_bytes": 44 + 48_000 * 10},
    )
    assert cost == pytest.approx(10 * 25 * 10.00 / 1e6)


def test_tts_promo_price_ends_on_new_year():
    units = {"characters_synthesized": 0, "audio_seconds": 40}
    december = datetime.datetime(2026, 12, 1, tzinfo=datetime.UTC).timestamp()
    january = datetime.datetime(2027, 1, 2, tzinfo=datetime.UTC).timestamp()
    promo, _ = pricing.estimate_details("gemini-3.8-flash-tts", units, at=december)
    full, _ = pricing.estimate_details("gemini-3.8-flash-tts", units, at=january)
    assert promo == pytest.approx(1_000 * 9.0 / 1e6)
    assert full == pytest.approx(1_000 * 18.0 / 1e6)


@pytest.mark.parametrize(
    ("model", "units", "price"),
    [
        ("chirp-3-hd", {"characters_synthesized": 1_000_000}, 30.0),
        ("lyria-002", {"sample_count": 2}, 0.12),
        ("lyria-3-pro-preview", {"sample_count": 1}, 0.08),
        ("lyria-3-clip-preview", {"sample_count": 1}, 0.04),
        ("virtual-try-on-001", {"images_generated": 2}, 0.12),
        ("imagen-4.0-ultra-generate-001", {"sample_count": 1}, 0.06),
    ],
)
def test_per_item_models(model, units, price):
    assert pricing.estimate(model, units) == pytest.approx(price)


# --- Cloud Billing Catalog -------------------------------------------------


def test_catalog_price_wins_and_is_marked_dynamic(monkeypatch):
    _catalog(
        monkeypatch,
        {
            pricing.VERTEX_SERVICE: [
                _sku("Veo 3 Fast 1080p Audio Video Generation", 0.2)
            ]
        },
    )
    cost, details = pricing.estimate_details(
        "veo-3.1-fast-generate-001",
        {"video_seconds_generated": 5, "resolution": "1080p", "generate_audio": True},
    )
    assert cost == pytest.approx(1.0)
    assert details["pricing_status"] == "dynamic"
    assert details["pricing_effective_time"] == "2026-11-25T00:00:00Z"


def test_catalog_token_skus_are_matched_exactly(monkeypatch):
    _catalog(
        monkeypatch,
        {
            pricing.VERTEX_SERVICE: [
                # Look-alikes that must not be picked.
                _sku("CodeMender Gemini 4 Neon Global Text Input", 9e-6),
                _sku(
                    "Gemini 4 Neon Cyber Permissive Global Text Output - Online Predictions",
                    9e-5,
                ),
                _sku("Gemini 4 Neon Global Text Input - Batch Predictions", 1e-7),
                # The real ones.
                _sku("Gemini 4 Neon Global Text Input - Online Predictions", 4e-6),
                _sku("Gemini 4 Neon Global Text Output - Online Predictions", 2e-5),
            ]
        },
    )
    rates = pricing.get_token_rates("gemini-4-neon")
    assert rates.input_per_million == pytest.approx(4.0)
    assert rates.output_per_million == pytest.approx(20.0)


def test_catalog_skips_a_free_tier(monkeypatch):
    _catalog(
        monkeypatch,
        {
            pricing.TTS_SERVICE: [
                _sku(
                    "Count of characters for Chirp3-HD voices",
                    0,
                    tiers=[(0, 0.0), (1_000_000, 0.00003)],
                )
            ]
        },
    )
    assert pricing.estimate(
        "chirp-3-hd", {"characters_synthesized": 1_000_000}
    ) == pytest.approx(30.0)


def test_catalog_fetch_picks_the_exact_vertex_service(monkeypatch):
    seen = []

    class Credentials:
        token = "t"

        def refresh(self, request):
            pass

    monkeypatch.setattr("google.auth.default", lambda scopes: (Credentials(), "p"))

    def fake_get_all(path, headers, field):
        seen.append(path)
        if field == "services":
            return [
                {
                    "displayName": "Dace IT with Sense Traffic Pulse and Vertex AI",
                    "serviceId": "market",
                },
                {"displayName": "Vertex AI Search", "serviceId": "search"},
                {"displayName": "Vertex AI", "serviceId": "vertex"},
            ]
        return []

    monkeypatch.setattr(pricing, "_get_all", fake_get_all)
    _REAL_FETCH(pricing.VERTEX_SERVICE)
    assert seen[-1] == "/services/vertex/skus"


def test_catalog_is_cached_and_a_failure_is_not_retried_at_once(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(pricing, "_monotonic", lambda: clock[0])
    calls = _catalog(monkeypatch, {pricing.VERTEX_SERVICE: []})
    pricing.estimate("veo-3.1-generate", {"video_seconds_generated": 1})
    pricing.estimate("veo-3.1-generate", {"video_seconds_generated": 1})
    assert calls == [pricing.VERTEX_SERVICE]
    clock[0] += pricing.PRICE_CACHE_TTL_SECONDS
    pricing.estimate("veo-3.1-generate", {"video_seconds_generated": 1})
    assert len(calls) == 2

    failures = []

    def broken(service=pricing.VERTEX_SERVICE):
        failures.append(service)
        raise RuntimeError("offline")

    monkeypatch.setattr(pricing, "_fetch_catalog_skus", broken)
    pricing.clear_price_cache()
    assert pricing.estimate(
        "veo-3.1-generate", {"video_seconds_generated": 1}
    ) == pytest.approx(0.4)
    pricing.estimate("veo-3.1-generate", {"video_seconds_generated": 1})
    assert len(failures) == 1


def test_fetch_false_never_reads_the_catalog(monkeypatch):
    def no_fetch(service=pricing.VERTEX_SERVICE):
        raise AssertionError("must not fetch")

    monkeypatch.setattr(pricing, "_fetch_catalog_skus", no_fetch)
    pricing.clear_price_cache()
    assert pricing.video_rate_per_second(
        "veo-3.1-generate-001", "4k", fetch=False
    ) == pytest.approx(0.6)
    assert pricing.cached_unit_rate("veo-3.1", "video").price_per_unit == pytest.approx(
        0.4
    )


# --- Usage events ----------------------------------------------------------


def test_usage_event_stores_how_it_was_priced():
    recorded = usage.event(
        "a@x",
        "veo-3.1-fast-generate-001",
        "success",
        {"video_seconds_generated": 8, "resolution": "4k", "generate_audio": True},
    )
    assert recorded["cost"] == pytest.approx(2.4)
    assert recorded["pricing_status"] == "list"
    assert recorded["pricing_unit"] == "s"
    assert recorded["kind"] == "video"


def test_summary_reports_unpriced_events_separately():
    now = 1_800_000_000.0
    events = [
        usage.event("a@x", "mystery-model", "success", {"prompt_tokens": 1}, at=now)
    ]
    summary = usage.summarize(events, 7, now=now)
    assert summary["total"]["unpriced"] == 1
    assert summary["total"]["cost"] is None


# --- Units captured from responses -----------------------------------------


def test_usage_metadata_splits_tokens_by_modality():
    meta = SimpleNamespace(
        prompt_token_count=3_000,
        candidates_token_count=1_200,
        thoughts_token_count=50,
        prompt_tokens_details=[
            SimpleNamespace(modality="TEXT", token_count=1_000),
            SimpleNamespace(modality=SimpleNamespace(value="AUDIO"), token_count=2_000),
        ],
        candidates_tokens_details=[
            SimpleNamespace(modality="MediaModality.IMAGE", token_count=1_120),
        ],
    )
    out = analytics.extract_usage_metadata(SimpleNamespace(usage_metadata=meta))
    assert out["prompt_tokens"] == 3_000
    assert out["prompt_audio_tokens"] == 2_000
    assert out["output_image_tokens"] == 1_120
    assert "prompt_text_tokens" not in out


def test_interaction_usage_is_captured():
    interaction = SimpleNamespace(
        usage=SimpleNamespace(
            total_input_tokens=50_000,
            total_output_tokens=57_920,
            total_cached_tokens=None,
            total_thought_tokens=None,
            total_tool_use_tokens=None,
            input_tokens_by_modality=[SimpleNamespace(modality="video", tokens=40_000)],
            output_tokens_by_modality=[
                SimpleNamespace(modality="video", tokens=57_920)
            ],
        )
    )
    out = analytics.extract_interaction_usage(interaction)
    assert out == {
        "prompt_tokens": 50_000,
        "candidates_tokens": 57_920,
        "prompt_video_tokens": 40_000,
        "output_video_tokens": 57_920,
    }


def test_live_usage_adds_up_over_a_session():
    from routers.live_router import add_live_usage

    totals = {}
    meta = SimpleNamespace(
        prompt_token_count=100,
        response_token_count=60,
        prompt_tokens_details=[SimpleNamespace(modality="AUDIO", token_count=80)],
        response_tokens_details=[SimpleNamespace(modality="AUDIO", token_count=50)],
    )
    add_live_usage(totals, meta)
    add_live_usage(totals, meta)
    assert totals == {
        "prompt_tokens": 200,
        "candidates_tokens": 120,
        "prompt_audio_tokens": 160,
        "output_audio_tokens": 100,
    }


def test_wrapper_spans_can_skip_the_usage_event(monkeypatch):
    calls = []
    monkeypatch.setattr(usage, "record", lambda *a, **k: calls.append(a))
    with analytics.track_model_call("veo-3.1-generate-001", count_usage=False):
        pass
    with analytics.track_model_call("veo-3.1-generate-001"):
        pass
    assert len(calls) == 1


def test_wav_seconds():
    from models.gemini_tts import pcm_to_wav, wav_seconds

    assert wav_seconds(pcm_to_wav(b"\0\0" * 24000 * 3)) == pytest.approx(3.0)
