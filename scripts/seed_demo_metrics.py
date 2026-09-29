"""Fill partners with plausible, clearly-labelled DEMO portfolio metrics.

NSFDC does not publish per-partner NPA / overdue / fund-utilization figures,
so in real use they are entered by an admin (PATCH /api/admin/partners/{id}/metrics
or the CSV import). For a demo, this script fills in illustrative figures so
the routing policy has something to act on. Every row it writes carries
metrics_updated_by = "DEMO DATA", which the API and UI label as such
everywhere they are shown.

It never touches real (admin-entered) figures, and it leaves roughly one
partner in seven without figures so the "no data" path is visible too.
Figures are deterministic per partner id, so re-running gives the same demo.

Usage:
  python scripts/seed_demo_metrics.py           # fill partners that have no real figures
  python scripts/seed_demo_metrics.py --clear   # remove all demo figures again
"""

import argparse
import random
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import SessionLocal, init_db
from models import Partner
from partner_engine import DEMO_DATA_TAG

METRIC_FIELDS = ["fund_utilization_pct", "npa_pct", "overdue_pct", "allocated_funds_inr", "disbursed_funds_inr"]

# Profile weights. The figure ranges in _demo_figures are chosen against
# partner_engine.RoutingPolicy's defaults so the demo shows every routing outcome.
PROFILES = {
    "no_data": 0.15,
    "healthy": 0.50,
    "watch": 0.20,     # one metric in the "deprioritize" band
    "stressed": 0.15,  # one metric past an "exclude" limit
}


def _demo_figures(rng: random.Random) -> dict | None:
    profile = rng.choices(list(PROFILES), weights=list(PROFILES.values()))[0]
    if profile == "no_data":
        return None
    npa, overdue, util = rng.uniform(0.5, 4.5), rng.uniform(2, 9), rng.uniform(65, 95)
    if profile == "watch":
        which = rng.choice(["npa", "overdue", "util"])
        if which == "npa":
            npa = rng.uniform(5, 9.5)
        elif which == "overdue":
            overdue = rng.uniform(10, 24)
        else:
            util = rng.uniform(35, 59)
    elif profile == "stressed":
        which = rng.choice(["npa", "overdue", "util"])
        if which == "npa":
            npa = rng.uniform(10.5, 18)
        elif which == "overdue":
            overdue = rng.uniform(26, 40)
        else:
            util = rng.uniform(10, 29)
    allocated = round(rng.uniform(0.5, 25) * 1e7, -5)  # ₹50 lakh – ₹25 crore
    return {
        "npa_pct": round(npa, 1),
        "overdue_pct": round(overdue, 1),
        "fund_utilization_pct": round(util, 1),
        "allocated_funds_inr": allocated,
        "disbursed_funds_inr": round(allocated * util / 100, -3),
    }


def seed(today: date | None = None) -> dict:
    init_db()
    today = today or date.today()
    counts = {"filled": 0, "left_no_data": 0, "skipped_real": 0}
    db = SessionLocal()
    try:
        for partner in db.query(Partner).order_by(Partner.id):
            has_real = partner.metrics_updated_by not in (None, DEMO_DATA_TAG)
            if has_real:
                counts["skipped_real"] += 1
                continue
            figures = _demo_figures(random.Random(partner.id))
            if figures is None:
                _clear(partner)
                counts["left_no_data"] += 1
                continue
            for f, v in figures.items():
                setattr(partner, f, v)
            partner.metrics_as_of_date = today.isoformat()
            partner.metrics_updated_by = DEMO_DATA_TAG
            counts["filled"] += 1
        db.commit()
    finally:
        db.close()
    return counts


def _clear(partner: Partner) -> None:
    for f in METRIC_FIELDS:
        setattr(partner, f, None)
    partner.metrics_as_of_date = None
    partner.metrics_updated_by = None


def clear() -> int:
    init_db()
    db = SessionLocal()
    try:
        demo = db.query(Partner).filter(Partner.metrics_updated_by == DEMO_DATA_TAG).all()
        for partner in demo:
            _clear(partner)
        db.commit()
        return len(demo)
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed or clear DEMO partner portfolio metrics.")
    parser.add_argument("--clear", action="store_true", help="remove all demo figures (real figures are untouched)")
    args = parser.parse_args()
    if args.clear:
        print(f"Cleared demo figures from {clear()} partner(s).")
    else:
        c = seed()
        print(f"Demo figures written for {c['filled']} partner(s), tagged metrics_updated_by={DEMO_DATA_TAG!r}; "
              f"{c['left_no_data']} left with no data; {c['skipped_real']} with real admin figures untouched.")
