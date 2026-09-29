"""Re-apply SCHEME_CODES_BY_TYPE to partners already in vittsetu.db.

scripts/ingest_partners.py only sets eligible_scheme_codes when it inserts a
row, and skips rows it has already ingested — so after the scheme mapping
changes, existing partners keep their old codes. This updates them in place
without re-running the slow download + geocode.

Only rows that came from ingest (source_url is one of ingest's PDFs for that
partner type) are touched; partners added by hand through the admin console
keep whatever codes the admin set.

Usage:
  python scripts/backfill_partner_schemes.py            # apply
  python scripts/backfill_partner_schemes.py --dry-run  # just show what would change
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from db import SessionLocal, init_db
from models import Partner
from ingest_partners import SCHEME_CODES_BY_TYPE, SOURCES


def backfill(dry_run: bool = False) -> int:
    init_db()
    source_urls = {(partner_type, url) for partner_type, url, _ in SOURCES}
    db = SessionLocal()
    changed = 0
    try:
        for partner in db.query(Partner).order_by(Partner.id):
            if (partner.partner_type, partner.source_url) not in source_urls:
                continue
            wanted = SCHEME_CODES_BY_TYPE[partner.partner_type]
            current = partner.eligible_scheme_codes or []
            if sorted(current) == sorted(wanted):
                continue
            print(f"[{'would update' if dry_run else 'update'}] #{partner.id} {partner.name[:60]} "
                  f"({partner.partner_type}): {current} -> {wanted}")
            if not dry_run:
                # Assign a new list: in-place mutation of a JSON column isn't change-tracked.
                partner.eligible_scheme_codes = list(wanted)
            changed += 1
        if not dry_run:
            db.commit()
    finally:
        db.close()
    print(f"\n{'Would update' if dry_run else 'Updated'} {changed} partner(s).")
    return changed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="show changes without writing them")
    backfill(parser.parse_args().dry_run)
