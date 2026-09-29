"""Channel Partner locator: filtering, ranking, fallbacks, and the API wrapper."""

import pytest

from partner_engine import find_nearby_partners, haversine_km

BENGALURU = (12.9716, 77.5946)
HOSUR_TN = (12.7409, 77.8253)  # ~35 km from Bengaluru, across the Tamil Nadu border
MYSURU = (12.2958, 76.6394)  # ~125 km from Bengaluru, same state


def names(result):
    return [m.partner.name for m in result.partners]


def search(db, lat=None, lon=None, state=None, district=None, scheme_code=None, limit=10):
    return find_nearby_partners(db, lat, lon, state, district, scheme_code, limit)


def test_haversine_known_distance():
    assert haversine_km(*BENGALURU, *MYSURU) == pytest.approx(128, abs=5)


# ── District: preference, not filter ─────────────────────────────────────────

def test_district_does_not_hide_partners_without_district(db_session, make_partner):
    # Ingest never populates `district` — these must still be found.
    make_partner("Karnataka SC Dev Corp", state="Karnataka", address="Bengaluru 560001")
    make_partner("Another KA Partner", state="Karnataka", address="Hubli 580020")

    result = search(db_session, state="Karnataka", district="Mysuru", scheme_code="MFS")

    assert sorted(names(result)) == ["Another KA Partner", "Karnataka SC Dev Corp"]
    assert result.note is None


def test_district_match_ranks_first_by_address_or_field(db_session, make_partner):
    make_partner("A Elsewhere", state="Karnataka", address="Hubli 580020")
    make_partner("B Address Match", state="Karnataka", address="Sayyaji Rao Road, Mysuru - 570001")
    make_partner("C Field Match", state="Karnataka", district="mysuru", address="Somewhere")

    result = search(db_session, state="Karnataka", district="Mysuru")

    assert names(result)[:2] == ["B Address Match", "C Field Match"]
    assert names(result)[2] == "A Elsewhere"


def test_district_match_is_whole_word(db_session, make_partner):
    make_partner("A Plain", state="Karnataka", address="Hubli")
    make_partner("B Substring Only", state="Karnataka", address="Udupiville Road")

    # "Udupi" must not count as a match inside "Udupiville".
    assert names(search(db_session, state="Karnataka", district="Udupi")) == ["A Plain", "B Substring Only"]


# ── Scheme membership ────────────────────────────────────────────────────────

def test_scheme_filter_is_exact_membership_not_substring(db_session, make_partner):
    make_partner("Term Loan Partner", eligible_scheme_codes=["TERM_LOAN"])
    make_partner("MFS Partner", eligible_scheme_codes=["MFS", "ELS"])
    make_partner("No Schemes", eligible_scheme_codes=[])

    # A LIKE-based .contains() would match "TERM" inside "TERM_LOAN".
    assert names(search(db_session, scheme_code="TERM")) == []
    assert names(search(db_session, scheme_code="TERM_LOAN")) == ["Term Loan Partner"]
    assert names(search(db_session, scheme_code="ELS")) == ["MFS Partner"]


def test_no_scheme_code_returns_all_schemes(db_session, make_partner):
    make_partner("A", eligible_scheme_codes=["AMY"])
    make_partner("B", eligible_scheme_codes=[])
    assert names(search(db_session)) == ["A", "B"]


# ── Capacity ─────────────────────────────────────────────────────────────────

def test_not_accepting_is_excluded_and_limited_ranks_last(db_session, make_partner):
    make_partner("A Limited", capacity_status="limited")
    make_partner("B Available", capacity_status="available")
    make_partner("C Not Accepting", capacity_status="not_accepting")

    result = search(db_session)
    assert names(result) == ["B Available", "A Limited"]
    assert [m.partner.name for m in result.excluded] == ["C Not Accepting"]
    assert "not currently accepting" in result.excluded[0].routing.reason


# ── Location mode ────────────────────────────────────────────────────────────

def test_location_ranks_by_distance_ignoring_state(db_session, make_partner):
    make_partner("Mysuru SCA", state="Karnataka", lat=MYSURU[0], lon=MYSURU[1])
    make_partner("Hosur Bank", state="Tamil Nadu", lat=HOSUR_TN[0], lon=HOSUR_TN[1])
    make_partner("No Coords", state="Karnataka")

    result = search(db_session, lat=BENGALURU[0], lon=BENGALURU[1], state="Karnataka")

    # The nearest partner is across the state border and still comes first.
    assert names(result) == ["Hosur Bank", "Mysuru SCA", "No Coords"]
    distances = [m.distance_km for m in result.partners]
    assert distances[0] == pytest.approx(35, abs=5)
    assert distances[2] is None
    assert result.note is None


def test_location_mode_respects_scheme_and_capacity_filters(db_session, make_partner):
    make_partner("Near But Full", lat=HOSUR_TN[0], lon=HOSUR_TN[1], capacity_status="not_accepting")
    make_partner("Near Wrong Scheme", lat=HOSUR_TN[0], lon=HOSUR_TN[1], eligible_scheme_codes=["AMY"])
    make_partner("Far OK", lat=MYSURU[0], lon=MYSURU[1])

    assert names(search(db_session, lat=BENGALURU[0], lon=BENGALURU[1], scheme_code="MFS")) == ["Far OK"]


# ── State fallback ───────────────────────────────────────────────────────────

def test_state_with_no_partners_falls_back_to_national_with_note(db_session, make_partner):
    make_partner("Delhi Partner", state="Delhi")
    make_partner("Gujarat Partner", state="Gujarat")

    result = search(db_session, state="Goa", scheme_code="MFS")

    assert names(result) == ["Delhi Partner", "Gujarat Partner"]
    assert "Goa" in result.note


def test_state_filter_applies_when_state_has_partners(db_session, make_partner):
    make_partner("Delhi Partner", state="Delhi")
    make_partner("Gujarat Partner", state="Gujarat")

    result = search(db_session, state="Gujarat")

    assert names(result) == ["Gujarat Partner"]
    assert result.note is None


def test_state_fallback_only_counts_compatible_partners(db_session, make_partner):
    # Goa has a partner, but not for this scheme — so fall back.
    make_partner("Goa AMY-only", state="Goa", eligible_scheme_codes=["AMY"])
    make_partner("Delhi MFS", state="Delhi")

    result = search(db_session, state="Goa", scheme_code="MFS")

    assert names(result) == ["Delhi MFS"]
    assert result.note is not None


def test_no_partners_anywhere_gives_empty_result_without_note(db_session):
    result = search(db_session, state="Goa", scheme_code="MFS")
    assert result.partners == []
    assert result.note is None


def test_limit(db_session, make_partner):
    for i in range(5):
        make_partner(f"P{i}")
    assert len(search(db_session, limit=3).partners) == 3


# ── API ──────────────────────────────────────────────────────────────────────

def test_nearby_endpoint_shape_and_distance_rounding(client, make_partner):
    make_partner("Hosur Bank", state="Tamil Nadu", lat=HOSUR_TN[0], lon=HOSUR_TN[1])

    resp = client.post("/api/partners/nearby", json={
        "lat": BENGALURU[0], "lon": BENGALURU[1], "scheme_code": "MFS",
    })

    assert resp.status_code == 200
    body = resp.json()
    assert body["note"] is None
    [partner] = body["partners"]
    assert partner["name"] == "Hosur Bank"
    assert partner["distance_km"] == round(partner["distance_km"], 1)


def test_nearby_endpoint_returns_fallback_note(client, make_partner):
    make_partner("Delhi Partner", state="Delhi")

    body = client.post("/api/partners/nearby", json={"state": "Goa", "district": "Panaji"}).json()

    assert [p["name"] for p in body["partners"]] == ["Delhi Partner"]
    assert "Goa" in body["note"]


# ── Backfill script ──────────────────────────────────────────────────────────

def test_backfill_updates_ingested_rows_only(db_session, make_partner):
    from backfill_partner_schemes import backfill
    from ingest_partners import SOURCES

    psb_url = next(url for ptype, url, _ in SOURCES if ptype == "PSB")
    ingested = make_partner("Canara Bank", partner_type="PSB", source_url=psb_url, eligible_scheme_codes=[])
    manual = make_partner("Admin-added PSB", partner_type="PSB", source_url=None, eligible_scheme_codes=["ELS"])

    assert backfill(dry_run=True) == 1
    db_session.refresh(ingested)
    assert ingested.eligible_scheme_codes == []  # dry run wrote nothing

    assert backfill() == 1
    db_session.refresh(ingested)
    db_session.refresh(manual)
    assert ingested.eligible_scheme_codes == ["MFS", "TERM_LOAN", "ELS"]
    assert manual.eligible_scheme_codes == ["ELS"]
    assert backfill() == 0  # idempotent
