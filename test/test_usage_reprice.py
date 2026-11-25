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
"""scripts/usage_reprice.py recomputes costs from stored billing units."""

import importlib.util
import pathlib

import pytest

_PATH = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "usage_reprice.py"
_spec = importlib.util.spec_from_file_location("usage_reprice", _PATH)
reprice_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reprice_mod)


def test_reprice_recomputes_cost_and_keeps_the_old_value():
    doc = {
        "model": "lyria-002",
        "status": "failed_after_output",
        "billing_units": {"sample_count": 2},
        "cost": 0.0,
        "at": 1764000000,
    }
    old, new, update = reprice_mod.reprice(doc, "20261126", fetch=False)
    assert old == 0.0 and new == pytest.approx(0.12)
    assert update["cost"] == pytest.approx(0.12)
    assert update["cost_by_sku"]
    assert update["cost_before_reprice_20261126"] == 0.0


def test_rerun_on_the_same_day_keeps_the_first_old_value():
    doc = {
        "model": "lyria-002",
        "status": "success",
        "billing_units": {"sample_count": 1},
        "cost": 0.06,
        "cost_before_reprice_20261126": 0.05,
    }
    _, _, update = reprice_mod.reprice(doc, "20261126", fetch=False)
    assert "cost_before_reprice_20261126" not in update


def test_summary_per_model():
    rows = [("a", 1.0, 2.0), ("a", 1.0, 1.0), ("b", 0.5, 0.5)]
    assert reprice_mod.summarize(rows) == [("a", 2, 2.0, 3.0), ("b", 1, 0.5, 0.5)]
