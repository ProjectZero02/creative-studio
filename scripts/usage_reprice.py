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
"""Reprice stored usage events with the current pricing.

Recomputes each event's cost and cost_by_sku from its stored billing_units
(config/pricing.py, live Cloud Billing Catalog when readable). Dry run by
default: prints old and new totals per model and changes nothing.

    python scripts/usage_reprice.py                 # dry run, last 400 days
    python scripts/usage_reprice.py --days 30
    python scripts/usage_reprice.py --apply         # write the new costs

--apply writes the new cost and pricing fields and keeps the previous cost
in cost_before_reprice_<YYYYMMDD> (set once per day, so a rerun keeps the
first value). Needs Application Default Credentials with Firestore access.
"""

from __future__ import annotations

import argparse
import datetime
import pathlib
import sys
import time
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from config import pricing  # noqa: E402

COLLECTION = "usage_events"
PRICING_FIELDS = (
    "pricing_status",
    "pricing_source",
    "pricing_effective_time",
    "pricing_basis",
    "pricing_unit",
    "price_per_unit",
    "input_price_per_million",
    "output_price_per_million",
    "image_output_price_per_million",
    "video_output_price_per_million",
    "audio_output_price_per_million",
    "grounding_cost",
    "tokens_in",
    "tokens_out",
)


def reprice(doc: dict, today: str, fetch: bool = True) -> tuple[float, float, dict]:
    """(old cost, new cost, fields to write) for one stored event."""
    old = float(doc.get("cost") or 0)
    cost, details = pricing.estimate_details(
        doc.get("model") or "",
        doc.get("billing_units") or {},
        doc.get("status") or "success",
        fetch=fetch,
        at=float(doc.get("at") or time.time()),
        location=str(doc.get("location") or ""),
    )
    new = round(cost, 5) if cost is not None else None
    update = {
        "cost": new,
        "cost_by_sku": details.get("cost_by_sku", {}),
        "kind": pricing.kind_of(doc.get("model") or "", doc.get("billing_units")),
        "repriced_at": time.time(),
    }
    for name in PRICING_FIELDS:
        update[name] = details.get(name)  # None clears a stale field
    keep = f"cost_before_reprice_{today}"
    if keep not in doc:
        update[keep] = doc.get("cost")
    return old, float(new or 0), update


def summarize(rows: list[tuple[str, float, float]]) -> list[tuple[str, int, float, float]]:
    per_model: dict[str, list] = defaultdict(lambda: [0, 0.0, 0.0])
    for model, old, new in rows:
        m = per_model[model]
        m[0] += 1
        m[1] += old
        m[2] += new
    return sorted(
        ((k, v[0], v[1], v[2]) for k, v in per_model.items()), key=lambda r: -r[3]
    )


def _stream(db, since: float):
    base = db.collection(COLLECTION).where("at", ">=", since).order_by("at")
    last = None
    while True:
        query = base.start_after(last) if last is not None else base
        page = list(query.limit(1000).stream())
        yield from page
        if len(page) < 1000:
            return
        last = page[-1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--project", default="mikel-testing")
    parser.add_argument("--database", default="create-studio-asset-metadata")
    parser.add_argument("--days", type=int, default=400)
    parser.add_argument("--apply", action="store_true", help="write the new costs")
    parser.add_argument(
        "--offline", action="store_true", help="book prices only (no catalog)"
    )
    args = parser.parse_args(argv)

    from google.cloud import firestore  # pylint: disable=import-outside-toplevel

    db = firestore.Client(project=args.project, database=args.database)
    today = datetime.date.today().strftime("%Y%m%d")
    since = time.time() - args.days * 86400
    rows, updates = [], []
    for snap in _stream(db, since):
        doc = snap.to_dict()
        old, new, update = reprice(doc, today, fetch=not args.offline)
        rows.append((doc.get("model") or "unknown", old, new))
        updates.append((snap.reference, update))

    print(f"{'model':<40} {'events':>7} {'old $':>11} {'new $':>11} {'change':>8}")
    for model, count, old, new in summarize(rows):
        change = f"{(new - old) / old * 100:+.1f}%" if old else "new"
        print(f"{model:<40} {count:>7} {old:>11.4f} {new:>11.4f} {change:>8}")
    old_total = sum(r[1] for r in rows)
    new_total = sum(r[2] for r in rows)
    print(f"{'TOTAL':<40} {len(rows):>7} {old_total:>11.4f} {new_total:>11.4f}")
    drift = pricing.price_drift()
    if drift:
        print(f"\nPrice book vs catalog: {len(drift)} issue(s)")
        for d in drift:
            print(f"  {d['issue']:<8} {d['sku']}  book={d['book']} catalog={d['catalog']}")

    if not args.apply:
        print("\nDry run: nothing written. Add --apply to write.")
        return 0
    batch, pending = db.batch(), 0
    for ref, update in updates:
        batch.update(ref, update)
        pending += 1
        if pending == 400:
            batch.commit()
            batch, pending = db.batch(), 0
    if pending:
        batch.commit()
    print(f"\nWrote {len(updates)} event(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
