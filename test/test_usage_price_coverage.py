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
"""Every model the app config names has a price, offline, and the right kind;
and the price book is checked against the catalog when it loads."""

import ast
import pathlib
import re

import pytest

from config import pricing

CONFIG = pathlib.Path(__file__).resolve().parent.parent / "src" / "config"
MODEL_ID = re.compile(
    r"^(gemini|veo|imagen|lyria|chirp|virtual-try-on)-[a-z0-9.]+(-[a-z0-9.]+)*$"
)
# Ids in config that are not billable model calls.
NOT_MODELS = {"gemini-2"}

EXPECTED_KIND = [
    ("veo", "video"),
    ("omni", "video"),
    ("lyria", "music"),
    ("tts", "speech"),
    ("chirp", "speech"),
    ("live", "live"),
    ("image", "image"),
    ("imagen", "image"),
    ("banana", "image"),
    ("try-on", "image"),
]


def config_model_ids() -> set[str]:
    ids = set()
    for path in CONFIG.rglob("*.py"):
        if path.name == "pricing.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if MODEL_ID.match(node.value) and node.value not in NOT_MODELS:
                    ids.add(node.value)
    return ids


def _expected_kind(model: str) -> str:
    for marker, kind in EXPECTED_KIND:
        if marker in model:
            return kind
    return "text"


def test_config_names_models():
    assert len(config_model_ids()) > 20


@pytest.mark.parametrize("model", sorted(config_model_ids()))
def test_every_config_model_has_an_offline_price_and_kind(model):
    units = {
        "video_seconds_generated": 1,
        "prompt_tokens": 1000,
        "candidates_tokens": 1000,
        "sample_count": 1,
        "images_generated": 1,
        "characters_synthesized": 100,
        "audio_seconds": 1,
    }
    cost, details = pricing.estimate_details(model, units, fetch=False)
    assert cost is not None and cost > 0, (model, details)
    assert pricing.kind_of(model) == _expected_kind(model)


# Drift check -----------------------------------------------------------------


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


def test_catalog_load_flags_missing_skus_and_price_changes(monkeypatch):
    skus = {
        pricing.VERTEX_SERVICE: [
            _sku("Count of samples for Lyria2 music generation model", 0.06),  # same
            _sku("Lyria 3 Audio Ouptut - Predictions", 0.10),  # book 0.08
        ],
        pricing.TTS_SERVICE: [],
    }
    monkeypatch.setattr(
        pricing, "_fetch_catalog_skus", lambda service=None: skus.get(service, [])
    )
    pricing.clear_price_cache()
    pricing.estimate_details("lyria-002", {"sample_count": 1})  # loads Vertex
    drift = {d["sku"]: d for d in pricing.price_drift()}
    lyria3 = drift["Lyria 3 Audio Ouptut - Predictions"]
    assert lyria3["issue"] == "price" and lyria3["book"] == pytest.approx(0.08)
    assert lyria3["catalog"] == pytest.approx(0.10)
    assert "Count of samples for Lyria2 music generation model" not in drift
    assert drift["Veo 3 Video Generation"]["issue"] == "missing"


def test_no_drift_before_a_catalog_load():
    pricing.clear_price_cache()
    assert pricing.price_drift() == []


def test_usage_page_alerts_list_drift_and_unpriced_models(monkeypatch):
    from pages import usage as usage_page

    monkeypatch.setattr(
        pricing,
        "price_drift",
        lambda: [
            {"sku": "A", "issue": "missing", "book": 1.0, "catalog": None},
            {"sku": "B", "issue": "price", "book": 1.0, "catalog": 1.2},
        ],
    )
    summary = {
        "models": [
            {"model": "mystery-1", "unpriced": 2},
            {"model": "lyria-002", "unpriced": 0},
        ]
    }
    assert usage_page._alerts(summary) == {
        "missing": ["A"],
        "changed": [{"sku": "B", "book": 1.0, "catalog": 1.2}],
        "unpriced": ["mystery-1"],
    }
