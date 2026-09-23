"""Ingest NSFDC's officially published Channel Partner directories into the
`partners` table.

Sources (downloaded fresh from nsfdc.nic.in on each run — nothing here is
invented; every row traces back to one of these PDFs via `source_url`):

  http://nsfdc.nic.in/our-channel-partners

Two PDF table layouts are handled:
  - "wide":   one entry per row — [Sl.No, (State), Name+Address]
  - "paired": two entries side-by-side per row — [No, Name+Address, No, Name+Address]

The Small Finance Bank and Cooperative Society PDFs use a non-standard layout
that PyMuPDF's table detector cannot reliably parse; they are skipped with a
warning rather than risk inserting garbled data — add those partners via the
admin console instead until a dedicated parser is written for them.

Addresses are geocoded via OpenStreetMap Nominatim (free, rate-limited to
1 req/sec per its usage policy) to get lat/lon for the map. Partners with an
address that fails to geocode are still inserted (name/type/address are still
useful for the list view) but won't appear on the map or in distance-sorted
results until an admin adds coordinates.
"""

import re
import sys
import time
from pathlib import Path

import requests
import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import SessionLocal, init_db
from models import Partner

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HEADERS = {"User-Agent": "VittSetu-Hackathon-Prototype/1.0 (contact: project maintainer)"}
GEOCODE_DELAY_SECONDS = 1.1  # respect Nominatim's 1 req/sec usage policy

SOURCE_PAGE = "http://nsfdc.nic.in/our-channel-partners"
CAPTURED_DATE = "2026-09-18"

INDIAN_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat",
    "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh",
    "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab",
    "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh",
    "Uttarakhand", "West Bengal", "Delhi", "Jammu and Kashmir", "Ladakh", "Puducherry",
    "Chandigarh", "Andaman and Nicobar Islands", "Dadra and Nagar Haveli", "Daman and Diu",
    "Lakshadweep",
]

# (partner_type, source_url, layout, eligible_scheme_codes)
# eligible_scheme_codes only set where NSFDC's own scheme page (see
# scripts/seed_schemes.py) explicitly names this partner type as a channel
# for one of the 5 seeded schemes — left empty where no such link is verified,
# rather than guessed.
SOURCES = [
    ("SCA", "http://nsfdc.nic.in/storage/channel-partners/attachments/20260401_164458_Ip6UJm.pdf", "wide_state", ["MFS", "TERM_LOAN", "ELS"]),
    ("PSB", "http://nsfdc.nic.in/storage/channel-partners/attachments/20260408_100623_Bea3za.pdf", "paired", []),
    ("RRB", "http://nsfdc.nic.in/storage/channel-partners/attachments/20260401_163145_9tiTZM.pdf", "paired", []),
    ("NBFC-MFI", "http://nsfdc.nic.in/storage/channel-partners/attachments/20251223_101231_7smjJC.pdf", "paired", ["AMY"]),
    ("Cooperative Bank", "http://nsfdc.nic.in/storage/channel-partners/attachments/20251223_101341_Zcm8s6.pdf", "paired", ["UNY"]),
    ("Other/SIDBI", "http://nsfdc.nic.in/storage/channel-partners/attachments/20260408_101214_Yw5CGQ.pdf", "wide_state", []),
]

_CLEAN_RE = re.compile(r"[​﻿]")  # zero-width space / BOM noise seen in these PDFs


def clean(text: str | None) -> str:
    if not text:
        return ""
    text = _CLEAN_RE.sub("", text)
    text = text.replace("�", "-")  # PDF encoding artifact standing in for en/em dash
    return text.strip()


def split_name_address(block: str) -> tuple[str, str]:
    lines = [l.strip() for l in clean(block).split("\n") if l.strip()]
    if not lines:
        return "", ""
    name = lines[0].rstrip(",")
    address = ", ".join(lines[1:])
    return name, address


def guess_state(text: str) -> str | None:
    for state in INDIAN_STATES:
        if state.lower() in text.lower():
            return state
    return None


def download_pdf(url: str) -> pymupdf.Document:
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    resp.raise_for_status()
    return pymupdf.open(stream=resp.content, filetype="pdf")


def parse_wide_state(doc: pymupdf.Document) -> list[dict]:
    """[Sl.No, State, Name, Address] (separate cells) or [Sl.No, State, Name+Address] (combined) layout."""
    entries = []
    for page in doc:
        for table in page.find_tables().tables:
            for row in table.extract():
                cells = [clean(c) for c in row if c is not None]
                if not cells or not re.match(r"^\d+\.?$", cells[0]):
                    continue
                state = None
                rest = cells[1:]
                if rest and rest[0] in INDIAN_STATES:
                    state = rest[0]
                    rest = rest[1:]
                if not rest:
                    continue
                if len(rest) >= 2:
                    # Name and Address are already separate cells — a name can
                    # legitimately span multiple lines, so join them, don't truncate.
                    name = rest[0].replace("\n", " ").strip()
                    address = ", ".join(c.replace("\n", ", ") for c in rest[1:])
                else:
                    name, address = split_name_address(rest[0])
                if not state:
                    state = guess_state(f"{name} {address}")
                if name:
                    entries.append({"name": name, "address": address, "state": state})
    return entries


def parse_paired(doc: pymupdf.Document) -> list[dict]:
    """[No, Name+Address, No, Name+Address] two-entries-per-row layout."""
    entries = []
    for page in doc:
        for table in page.find_tables().tables:
            for row in table.extract():
                cells = row
                for i in (0, 2):
                    if i + 1 >= len(cells):
                        continue
                    no_cell, block = cells[i], cells[i + 1]
                    if not no_cell or not block or not re.match(r"^\d+\.?$", clean(no_cell)):
                        continue
                    name, address = split_name_address(block)
                    if name:
                        entries.append({"name": name, "address": address, "state": guess_state(block)})
    return entries


PARSERS = {"wide_state": parse_wide_state, "paired": parse_paired}


def geocode(query: str) -> tuple[float, float] | None:
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"q": f"{query}, India", "format": "json", "limit": 1},
            headers=NOMINATIM_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as e:
        print(f"    [geocode-fail] {query[:60]}: {e}")
    return None


def ingest():
    init_db()
    db = SessionLocal()
    total_inserted = 0
    total_skipped_dupe = 0

    try:
        for partner_type, url, layout, scheme_codes in SOURCES:
            print(f"\n=== {partner_type} ({url}) ===")
            try:
                doc = download_pdf(url)
            except Exception as e:
                print(f"  [error] could not download: {e}")
                continue

            entries = PARSERS[layout](doc)
            print(f"  parsed {len(entries)} entries")

            for entry in entries:
                existing = db.query(Partner).filter_by(name=entry["name"], partner_type=partner_type).first()
                if existing:
                    total_skipped_dupe += 1
                    continue

                coords = None
                if entry["address"]:
                    # Address-only geocodes far more reliably than "org name, address" —
                    # Nominatim matches physical locations, not organization names.
                    coords = geocode(entry["address"])
                    time.sleep(GEOCODE_DELAY_SECONDS)
                    if not coords and entry["state"]:
                        coords = geocode(f"{entry['address']}, {entry['state']}")
                        time.sleep(GEOCODE_DELAY_SECONDS)
                if not coords and entry["state"]:
                    coords = geocode(entry["state"])
                    time.sleep(GEOCODE_DELAY_SECONDS)

                partner = Partner(
                    name=entry["name"],
                    partner_type=partner_type,
                    state=entry["state"],
                    address=entry["address"] or None,
                    lat=coords[0] if coords else None,
                    lon=coords[1] if coords else None,
                    eligible_scheme_codes=scheme_codes,
                    capacity_status="available",
                    source_url=url,
                    source_captured_date=CAPTURED_DATE,
                )
                db.add(partner)
                total_inserted += 1
                geo_note = "geocoded" if coords else "no coordinates"
                print(f"  [add] {entry['name'][:60]} ({entry['state'] or '?'}) — {geo_note}")

            db.commit()

    finally:
        db.close()

    print(f"\nDone. Inserted {total_inserted} partners, skipped {total_skipped_dupe} already-present duplicates.")
    print("Small Finance Bank and Cooperative Society PDFs were not auto-parseable "
          "(non-standard layout) — add those via the admin console, or extend "
          "this script's parsers for them.")


if __name__ == "__main__":
    ingest()
