"""Ingest NSFDC's officially published Channel Partner directories into the
`partners` table.

Sources (downloaded fresh from nsfdc.nic.in on each run — nothing here is
invented; every row traces back to one of these PDFs via `source_url`):

  http://nsfdc.nic.in/our-channel-partners

PDF table layouts handled:
  - "wide_state":   one entry per row — [Sl.No, (State), Name+Address]
  - "paired":       two entries side-by-side per row — [No, Name+Address, No, Name+Address]
  - "sfb_names":    Small Finance Bank list — a sparse table of serial number
                    + bank name only (no addresses are published)
  - "coop_society": paired layout, but each block runs name and address
                    together on one comma-separated line

Rows from the two dedicated parsers are validated and skipped (with a
warning) rather than inserted if they don't look like a real entry.

Usage:
  python scripts/ingest_partners.py                          # every partner type
  python scripts/ingest_partners.py --only "Small Finance Bank"

Addresses are geocoded via OpenStreetMap Nominatim (free, rate-limited to
1 req/sec per its usage policy) to get lat/lon for the map. Partners with an
address that fails to geocode are still inserted (name/type/address are still
useful for the list view) but won't appear on the map or in distance-sorted
results until an admin adds coordinates.
"""

import argparse
import re
import sys
from datetime import date
from pathlib import Path

import requests
import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import geocoding
from db import SessionLocal, init_db
from models import Partner


SOURCE_PAGE = "http://nsfdc.nic.in/our-channel-partners"

INDIAN_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat",
    "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh",
    "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab",
    "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh",
    "Uttarakhand", "West Bengal", "Delhi", "Jammu and Kashmir", "Ladakh", "Puducherry",
    "Chandigarh", "Andaman and Nicobar Islands", "Dadra and Nagar Haveli", "Daman and Diu",
    "Lakshadweep",
]

# Which of the 5 seeded schemes each partner type channels. Only set where
# NSFDC's own pages say so — left empty where no link is verified, rather
# than guessed. Checked 2026-09-29 against:
#   [S] http://nsfdc.nic.in/scheme
#   [H] http://nsfdc.nic.in/how-to-apply-2
#
#   MFS, Term Loan: "NSFDC charges ... from the SCAs/CAs"                [S]
#   ELS:            interest-rate column headed "CAs"                    [S]
#   AMY:            "through selected NBFC-MFIs"                         [S]
#   UNY:            "through Cooperative Societies, Cooperative Banks,
#                    and Small Finance Banks (SFBs)"                     [S]
#   Banks are CAs:  "Channel Partners, including State Channelizing
#                    Agencies (SCAs), Banks, and other Channelizing
#                    Agencies (CAs)"                                     [H]
#
# PSB and RRB therefore get the SCA/CA schemes. Other/SIDBI (NEDFi,
# JHARCRAFT, SIDBI) stays empty: neither page names these agencies or says
# which schemes they channel. Also used by scripts/backfill_partner_schemes.py.
SCHEME_CODES_BY_TYPE = {
    "SCA": ["MFS", "TERM_LOAN", "ELS"],
    "PSB": ["MFS", "TERM_LOAN", "ELS"],
    "RRB": ["MFS", "TERM_LOAN", "ELS"],
    "NBFC-MFI": ["AMY"],
    "Cooperative Bank": ["UNY"],
    "Cooperative Society": ["UNY"],
    "Small Finance Bank": ["UNY"],
    "Other/SIDBI": [],
}

# (partner_type, source_url, layout) — PDFs linked from SOURCE_PAGE.
SOURCES = [
    ("SCA", "http://nsfdc.nic.in/storage/channel-partners/attachments/20260401_164458_Ip6UJm.pdf", "wide_state"),
    ("PSB", "http://nsfdc.nic.in/storage/channel-partners/attachments/20260408_100623_Bea3za.pdf", "paired"),
    ("RRB", "http://nsfdc.nic.in/storage/channel-partners/attachments/20260401_163145_9tiTZM.pdf", "paired"),
    ("NBFC-MFI", "http://nsfdc.nic.in/storage/channel-partners/attachments/20251223_101231_7smjJC.pdf", "paired"),
    ("Cooperative Bank", "http://nsfdc.nic.in/storage/channel-partners/attachments/20251223_101341_Zcm8s6.pdf", "paired"),
    ("Other/SIDBI", "http://nsfdc.nic.in/storage/channel-partners/attachments/20260408_101214_Yw5CGQ.pdf", "wide_state"),
    ("Small Finance Bank", "http://nsfdc.nic.in/storage/uploads/images/banners/20260408_100851_UrGTfH.pdf", "sfb_names"),
    ("Cooperative Society", "http://nsfdc.nic.in/storage/uploads/images/banners/20260408_101711_6Iyved.pdf", "coop_society"),
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


_SERIAL_RE = re.compile(r"^\d+\.?$")
_PIN_RE = re.compile(r"\b\d{3}\s?\d{3}\b")


def _flatten(text: str | None) -> str:
    """clean(), then join lines, normalize NBSPs/whitespace and tidy " ," spacing."""
    text = clean(text).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"\s+,", ",", text).strip(" ,")


def parse_sfb_names(doc: pymupdf.Document) -> list[dict]:
    """Small Finance Bank PDF: a sparse table whose rows hold only a serial
    number and a bank name scattered across mostly-empty cells, e.g.
    ['', '1', '', '', 'AU small finance bank', '', None]. No addresses are
    published, so entries get no state or coordinates (names are never geocoded).
    """
    entries = []
    for page in doc:
        for table in page.find_tables().tables:
            for row in table.extract():
                cells = [c for c in (_flatten(c) for c in row) if c]
                if len(cells) < 2 or not _SERIAL_RE.match(cells[0]):
                    continue
                name = cells[1]
                if len(cells) > 2 or len(name) > 120 or not re.search(r"small finance bank", name, re.IGNORECASE):
                    print(f"  [skip-invalid] unexpected Small Finance Bank row: {cells!r}")
                    continue
                entries.append({"name": name, "address": "", "state": None})
    return entries


def parse_coop_society(doc: pymupdf.Document) -> list[dict]:
    """Cooperative Society PDF: paired [No, Block, No, Block] rows where each
    block runs name and address together, comma-separated, e.g.
    "Streenidhi, Telangana, 401 & 402, 4th Floor ..., Hyderabad, Telangana 500004".
    The name is the text before the first comma; the rest is the address.
    """
    entries = []
    for page in doc:
        for table in page.find_tables().tables:
            for row in table.extract():
                for i in range(0, len(row) - 1, 2):
                    no_cell, block = _flatten(row[i]), _flatten(row[i + 1])
                    if not _SERIAL_RE.match(no_cell) or not block:
                        continue
                    name, _, address = block.partition(",")
                    name, address = name.strip(), address.strip(" ,")
                    state = guess_state(address)
                    problems = []
                    if not name or len(name) > 100 or name[0].isdigit():
                        problems.append("implausible name")
                    if not (_PIN_RE.search(address) or state):
                        problems.append("address has no PIN code or state")
                    if problems:
                        print(f"  [skip-invalid] {', '.join(problems)}: {block[:80]!r}")
                        continue
                    entries.append({"name": name, "address": address, "state": state})
    return entries


PARSERS = {
    "wide_state": parse_wide_state,
    "paired": parse_paired,
    "sfb_names": parse_sfb_names,
    "coop_society": parse_coop_society,
}


def geocode(query: str) -> tuple[float, float] | None:
    """Shared Nominatim client (geocoding.py) — it enforces the 1 req/sec limit."""
    try:
        result = geocoding.geocode(query)
    except geocoding.GeocodingError as e:
        print(f"    [geocode-fail] {query[:60]}: {e}")
        return None
    return (result.lat, result.lon) if result else None


def ingest(only: str | None = None):
    init_db()
    db = SessionLocal()
    total_inserted = 0
    total_skipped_dupe = 0

    try:
        for partner_type, url, layout in SOURCES:
            if only and partner_type != only:
                continue
            scheme_codes = SCHEME_CODES_BY_TYPE[partner_type]
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
                    if not coords and entry["state"]:
                        coords = geocode(f"{entry['address']}, {entry['state']}")
                if not coords and entry["state"]:
                    coords = geocode(entry["state"])

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
                    # PDFs are downloaded fresh on every run, so today is the capture date.
                    source_captured_date=date.today().isoformat(),
                )
                db.add(partner)
                total_inserted += 1
                geo_note = "geocoded" if coords else "no coordinates"
                print(f"  [add] {entry['name'][:60]} ({entry['state'] or '?'}) — {geo_note}")

            db.commit()

    finally:
        db.close()

    print(f"\nDone. Inserted {total_inserted} partners, skipped {total_skipped_dupe} already-present duplicates.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest NSFDC's official Channel Partner directories.")
    parser.add_argument(
        "--only",
        metavar="PARTNER_TYPE",
        choices=[partner_type for partner_type, _, _ in SOURCES],
        help='ingest just this partner type (quote names with spaces), e.g. "Small Finance Bank"',
    )
    ingest(parser.parse_args().only)
