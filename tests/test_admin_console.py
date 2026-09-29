"""Admin console: auth hardening, CORS, partner CRUD + geocoding, scheme edits,
audit trail, operational metrics, and the public coverage stats."""

from datetime import timedelta

import pytest

import geocoding
from conftest import ADMIN_HEADERS
from models import AdminAuditLog, Application, ApplicationEvent, Partner, Scheme

AS_OPS = {**ADMIN_HEADERS, "X-Admin-User": "Priya (ops)"}


def audit_entries(db_session, **filters):
    db_session.expire_all()
    return db_session.query(AdminAuditLog).filter_by(**filters).order_by(AdminAuditLog.id).all()


# ── Auth hardening ───────────────────────────────────────────────────────────

def test_production_refuses_default_token(client, monkeypatch):
    monkeypatch.setenv("VITTSETU_ENV", "production")
    monkeypatch.setenv("ADMIN_TOKEN", "vittsetu-admin-dev")
    resp = client.get("/api/admin/schemes", headers={"X-Admin-Token": "vittsetu-admin-dev"})
    assert resp.status_code == 503 and "non-default ADMIN_TOKEN" in resp.json()["detail"]

    monkeypatch.delenv("ADMIN_TOKEN")  # unset falls back to the default → still refused
    assert client.get("/api/admin/schemes", headers={"X-Admin-Token": "vittsetu-admin-dev"}).status_code == 503

    monkeypatch.setenv("ADMIN_TOKEN", "s3cret-prod-token")
    assert client.get("/api/admin/schemes", headers={"X-Admin-Token": "s3cret-prod-token"}).status_code == 200
    assert client.get("/api/admin/schemes", headers={"X-Admin-Token": "s3cret-prod-tokeN"}).status_code == 401


def test_default_token_works_outside_production(client, monkeypatch):
    monkeypatch.delenv("VITTSETU_ENV", raising=False)
    monkeypatch.setenv("ADMIN_TOKEN", "")
    assert client.get("/api/admin/schemes", headers={"X-Admin-Token": "vittsetu-admin-dev"}).status_code == 200


def test_non_ascii_token_header_is_rejected_cleanly(client):
    # Raw non-ASCII bytes, as a browser can send; must be a clean 401, not a 500.
    assert client.get("/api/admin/schemes", headers={"X-Admin-Token": "tést".encode()}).status_code == 401


def test_admin_user_header_is_percent_decoded(client, db_session, make_partner):
    p = make_partner("P")
    client.patch(f"/api/admin/partners/{p.id}/capacity", json={"capacity_status": "limited"},
                 headers={**ADMIN_HEADERS, "X-Admin-User": "%E0%A4%AA%E0%A5%8D%E0%A4%B0%E0%A4%BF%E0%A4%AF%E0%A4%BE"})
    assert audit_entries(db_session, entity_type="partner")[0].actor == "प्रिया"


def test_cors_allows_only_configured_origins(client):
    ok = client.get("/api/schemes", headers={"Origin": "http://localhost:5173"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    evil = client.get("/api/schemes", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in evil.headers
    preflight = client.options("/api/admin/partners", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "GET",
    })
    assert preflight.status_code == 400


# ── Partners: create / edit ──────────────────────────────────────────────────

NEW_PARTNER = {
    "name": "Mysuru District SC Society", "partner_type": "Cooperative Society", "state": "Karnataka",
    "district": "Mysuru", "address": "Sayyaji Rao Road, Mysuru 570001", "lat": 12.30, "lon": 76.64,
    "phone": "0821-000000", "email": "office@example.org", "eligible_scheme_codes": ["UNY"],
    "source_url": "http://nsfdc.nic.in/our-channel-partners",
}


def test_create_partner_is_audited(client, db_session):
    resp = client.post("/api/admin/partners", headers=AS_OPS, json=NEW_PARTNER)
    assert resp.status_code == 201
    body = resp.json()
    assert body["capacity_status"] == "available" and body["routing_status"] == "no_data"

    [entry] = audit_entries(db_session, entity_type="partner", entity_id=str(body["id"]))
    assert (entry.action, entry.actor, entry.before) == ("created", "Priya (ops)", None)
    assert entry.after["name"] == NEW_PARTNER["name"]


@pytest.mark.parametrize("override, fragment", [
    ({"partner_type": "Moneylender"}, "partner_type"),
    ({"eligible_scheme_codes": ["UNY", "NOPE"]}, "Unknown scheme code(s): NOPE"),
    ({"lat": 12.3, "lon": None}, "both latitude and longitude"),
    ({"lat": 76.64, "lon": 12.30}, "lat"),  # swapped — outside India
    ({"email": "not-an-email"}, "email"),
    ({"source_url": "ftp://example.org"}, "http(s) URL"),
    ({"name": "   "}, "name"),
])
def test_create_partner_validation(client, override, fragment):
    resp = client.post("/api/admin/partners", headers=ADMIN_HEADERS, json={**NEW_PARTNER, **override})
    assert resp.status_code == 422
    assert fragment in str(resp.json()["detail"])


def test_patch_partner_updates_clears_and_audits(client, db_session, make_partner):
    p = make_partner("Old Name", state="Bihar", district="Patna", address="Patna 800001")

    resp = client.patch(f"/api/admin/partners/{p.id}", headers=AS_OPS,
                        json={"name": "New Name", "district": None, "lat": 25.6, "lon": 85.1})

    assert resp.status_code == 200
    body = resp.json()
    assert (body["name"], body["district"], body["lat"], body["state"]) == ("New Name", None, 25.6, "Bihar")
    [entry] = audit_entries(db_session, entity_type="partner", entity_id=str(p.id))
    assert entry.action == "updated" and entry.actor == "Priya (ops)"
    assert (entry.before["name"], entry.after["name"]) == ("Old Name", "New Name")
    assert (entry.before["district"], entry.after["district"]) == ("Patna", None)

    # A no-op edit writes no audit entry.
    client.patch(f"/api/admin/partners/{p.id}", headers=AS_OPS, json={"name": "New Name"})
    assert len(audit_entries(db_session, entity_type="partner", entity_id=str(p.id))) == 1


def test_patch_partner_guards(client, make_partner):
    p = make_partner("P")
    assert client.patch(f"/api/admin/partners/{p.id}", headers=ADMIN_HEADERS, json={"name": None}).status_code == 422
    assert client.patch(f"/api/admin/partners/{p.id}", headers=ADMIN_HEADERS, json={"lat": 20.0}).status_code == 422
    assert client.patch("/api/admin/partners/99999", headers=ADMIN_HEADERS, json={"name": "x"}).status_code == 404
    assert client.patch(f"/api/admin/partners/{p.id}", json={"name": "x"}).status_code == 401


def test_capacity_metrics_and_csv_changes_are_audited(client, db_session, make_partner):
    p = make_partner("P")
    client.patch(f"/api/admin/partners/{p.id}/capacity", headers=AS_OPS, json={"capacity_status": "limited"})
    client.patch(f"/api/admin/partners/{p.id}/metrics", headers=AS_OPS,
                 json={"npa_pct": 4, "metrics_as_of_date": "2026-09-01"})
    client.post("/api/admin/partners/metrics/import", headers=AS_OPS, files={
        "file": ("m.csv", f"partner_id,npa_pct,metrics_as_of_date\n{p.id},6,2026-09-15\n".encode(), "text/csv"),
    })

    entries = audit_entries(db_session, entity_type="partner", entity_id=str(p.id))
    assert [e.action for e in entries] == ["capacity_changed", "metrics_updated", "metrics_imported"]
    assert (entries[0].before["capacity_status"], entries[0].after["capacity_status"]) == ("available", "limited")
    assert (entries[2].before["npa_pct"], entries[2].after["npa_pct"]) == (4, 6)


# ── Partners: list / filters / pagination ────────────────────────────────────

def test_partner_list_search_filters_and_pagination(client, make_partner):
    for i in range(30):
        make_partner(f"Bank {i:02d}", partner_type="RRB", state="Bihar", district="Patna" if i % 2 else None,
                     lat=25.6 if i % 3 else None, lon=85.1 if i % 3 else None)
    make_partner("Goa SCA", state="Goa", address="Panaji", npa_pct=20, metrics_as_of_date="2026-09-01",
                 metrics_updated_by="ops")

    page1 = client.get("/api/admin/partners", headers=ADMIN_HEADERS, params={"page_size": 10}).json()
    assert (page1["total"], len(page1["items"]), page1["page"]) == (31, 10, 1)
    assert page1["missing_coordinates"] == 11 and page1["missing_district"] == 16
    page4 = client.get("/api/admin/partners", headers=ADMIN_HEADERS, params={"page_size": 10, "page": 4}).json()
    assert [p["name"] for p in page4["items"]] == ["Goa SCA"]

    def names(**params):
        return [p["name"] for p in client.get("/api/admin/partners", headers=ADMIN_HEADERS,
                                              params={"page_size": 200, **params}).json()["items"]]

    assert names(q="panaji") == ["Goa SCA"]
    assert names(q="bank 1") == [f"Bank {i}" for i in range(10, 20)]
    assert len(names(missing="coordinates")) == 11
    assert len(names(missing="district")) == 16
    assert names(routing_status="excluded") == ["Goa SCA"]
    assert names(state="Goa", partner_type="SCA") == ["Goa SCA"]
    assert client.get("/api/admin/partners", headers=ADMIN_HEADERS, params={"page_size": 500}).status_code == 422


# ── Geocoding ────────────────────────────────────────────────────────────────

def test_geocode_endpoint(client, monkeypatch):
    calls = []

    def fake(query):
        calls.append(query)
        return geocoding.GeocodeResult(25.61, 85.14, "Patna, Bihar, India")

    monkeypatch.setattr(geocoding, "geocode", fake)
    body = client.post("/api/admin/geocode", headers=ADMIN_HEADERS,
                       json={"address": "Bailey Road, Patna", "state": "Bihar"}).json()
    assert body == {"lat": 25.61, "lon": 85.14, "display_name": "Patna, Bihar, India",
                    "query": "Bailey Road, Patna, Bihar"}
    client.post("/api/admin/geocode", headers=ADMIN_HEADERS, json={"address": "Patna, Bihar", "state": "Bihar"})
    assert calls[-1] == "Patna, Bihar"  # state not repeated

    monkeypatch.setattr(geocoding, "geocode", lambda q: None)
    assert client.post("/api/admin/geocode", headers=ADMIN_HEADERS, json={"address": "nowhere"}).status_code == 404

    def boom(q):
        raise geocoding.GeocodingError("timeout")
    monkeypatch.setattr(geocoding, "geocode", boom)
    assert client.post("/api/admin/geocode", headers=ADMIN_HEADERS, json={"address": "Patna"}).status_code == 502
    assert client.post("/api/admin/geocode", json={"address": "Patna"}).status_code == 401


def test_geocoder_rate_limits_and_identifies_itself(monkeypatch):
    clock = {"now": 1000.0}
    sleeps, requests_made = [], []

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"lat": "25.6", "lon": "85.1", "display_name": "Patna"}]

    def fake_get(url, params, headers, timeout):
        requests_made.append((clock["now"], params["q"], headers["User-Agent"]))
        return FakeResp()

    def fake_sleep(seconds):
        sleeps.append(seconds)
        clock["now"] += seconds

    monkeypatch.setattr(geocoding.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(geocoding.time, "sleep", fake_sleep)
    monkeypatch.setattr(geocoding.requests, "get", fake_get)
    monkeypatch.setattr(geocoding, "_last_request_at", 0.0)

    geocoding.geocode("Patna")
    clock["now"] += 0.3
    result = geocoding.geocode("Gaya")

    assert result == geocoding.GeocodeResult(25.6, 85.1, "Patna")
    assert sleeps == [pytest.approx(0.8)]  # waited out the rest of the 1.1 s window
    assert requests_made[1][0] - requests_made[0][0] == pytest.approx(1.1)
    assert all(ua == geocoding.NOMINATIM_HEADERS["User-Agent"] for _, _, ua in requests_made)
    assert requests_made[0][1] == "Patna, India"


# ── Schemes ──────────────────────────────────────────────────────────────────

SOURCE = "https://nsfdc.nic.in/scheme"


def test_scheme_edit_requires_valid_source_url(client):
    assert client.put("/api/admin/schemes/MFS", headers=ADMIN_HEADERS, json={"max_loan_amount": 130000}).status_code == 422
    assert client.put("/api/admin/schemes/MFS", headers=ADMIN_HEADERS,
                      json={"source_url": "see circular", "max_loan_amount": 130000}).status_code == 422


def test_scheme_edit_dry_run_then_apply(client, db_session):
    payload = {"source_url": SOURCE, "max_loan_amount": 130000, "interest_rate_to_beneficiary_pct": 6.0}

    dry = client.put("/api/admin/schemes/mfs", headers=AS_OPS, params={"dry_run": "true"}, json=payload).json()
    assert dry["applied"] is False
    assert {c["field"]: (c["before"], c["after"]) for c in dry["changes"]} == {
        "interest_rate_to_beneficiary_pct": (6.5, 6.0),
        "max_loan_amount": (125000, 130000),
        "source_url": ("http://nsfdc.nic.in/scheme", SOURCE),
    }
    db_session.expire_all()
    assert db_session.query(Scheme).filter_by(code="MFS").one().max_loan_amount == 125000
    assert audit_entries(db_session, entity_type="scheme") == []

    applied = client.put("/api/admin/schemes/MFS", headers=AS_OPS, json=payload).json()
    assert applied["applied"] is True and applied["scheme"]["max_loan_amount"] == 130000
    assert applied["scheme"]["last_verified_date"] != "2026-09-18"
    [entry] = audit_entries(db_session, entity_type="scheme", entity_id="MFS")
    assert entry.actor == "Priya (ops)"
    assert (entry.before["max_loan_amount"], entry.after["max_loan_amount"]) == (125000, 130000)

    again = client.put("/api/admin/schemes/MFS", headers=AS_OPS, json=payload).json()
    assert again["applied"] is False and again["changes"] == []


@pytest.mark.parametrize("payload, fragment", [
    ({"max_loan_amount": 200000}, "cannot exceed max_project_cost"),
    ({"min_project_cost": 200000}, "must be below max_project_cost"),
    ({"max_financing_pct": 120}, "max_financing_pct"),
    ({"rates_by_partner_type": {"NBFC-MFI": 12}}, "Not a partner type for this scheme"),
    ({"moratorium_min_months": 12}, "cannot exceed moratorium_max_months"),
    ({"max_loan_amount": None}, "Cannot clear required field(s): max_loan_amount"),
    ({"max_project_cost": None, "interest_rate_to_beneficiary_pct": None},
     "Cannot clear required field(s): interest_rate_to_beneficiary_pct, max_project_cost"),
])
def test_scheme_edit_validation(client, payload, fragment):
    resp = client.put("/api/admin/schemes/MFS", headers=ADMIN_HEADERS, json={"source_url": SOURCE, **payload})
    assert resp.status_code == 422
    assert fragment in str(resp.json()["detail"])


def test_scheme_rates_edit_changes_calculator(client):
    client.put("/api/admin/schemes/UNY", headers=ADMIN_HEADERS, json={
        "source_url": SOURCE,
        "rates_by_partner_type": {"Cooperative Bank": 12, "Cooperative Society": 12, "Small Finance Bank": 14},
    })
    calc = client.post("/api/calculate", json={"scheme_code": "UNY", "project_cost": 300000,
                                               "partner_type": "Small Finance Bank"}).json()
    assert calc["interest_rate_pct"] == 14


# ── Applications + audit log + metrics ───────────────────────────────────────

def route(client, partner):
    return client.post("/api/applications", json={"scheme_code": "MFS", "partner_id": partner.id,
                                                  "consent": True}).json()["reference"]


def advance(client, ref, *statuses, headers=AS_OPS):
    for s in statuses:
        assert client.patch(f"/api/admin/applications/{ref}/status", headers=headers,
                            json={"status": s}).status_code == 200


def test_application_status_changes_are_audited(client, db_session, make_partner):
    ref = route(client, make_partner("SCA"))
    advance(client, ref, "acknowledged_by_partner")
    [entry] = audit_entries(db_session, entity_type="application", entity_id=ref)
    assert (entry.action, entry.actor) == ("status_changed", "Priya (ops)")
    assert (entry.before["status"], entry.after["status"]) == ("routed", "acknowledged_by_partner")
    event = db_session.query(ApplicationEvent).filter_by(to_status="acknowledged_by_partner").one()
    assert event.actor == "admin:Priya (ops)"


def test_audit_endpoint_filters_and_pages(client, make_partner):
    p = make_partner("P")
    for status in ("limited", "available", "limited"):
        client.patch(f"/api/admin/partners/{p.id}/capacity", headers=AS_OPS, json={"capacity_status": status})
    client.put("/api/admin/schemes/MFS", headers=AS_OPS, json={"source_url": SOURCE, "max_loan_amount": 120000})

    body = client.get("/api/admin/audit", headers=ADMIN_HEADERS, params={"page_size": 2}).json()
    assert body["total"] == 4 and len(body["items"]) == 2
    assert body["items"][0]["entity_type"] == "scheme"  # newest first
    assert body["items"][0]["changed_fields"] == ["last_verified_date", "max_loan_amount", "source_url"]

    partner_only = client.get("/api/admin/audit", headers=ADMIN_HEADERS,
                              params={"entity_type": "partner", "entity_id": str(p.id)}).json()
    assert [i["after"]["capacity_status"] for i in partner_only["items"]] == ["limited", "available", "limited"]
    assert all(i["changed_fields"] == ["capacity_status"] for i in partner_only["items"])
    assert client.get("/api/admin/audit").status_code == 401


def test_admin_metrics(client, db_session, make_partner):
    sca = make_partner("SCA", lat=25.6, lon=85.1, district="Patna")
    make_partner("Stressed", npa_pct=20, metrics_as_of_date="2026-09-01", metrics_updated_by="ops")
    make_partner("Demo", npa_pct=6, metrics_as_of_date="2026-09-01", metrics_updated_by="DEMO DATA")

    refs = [route(client, sca) for _ in range(5)]
    full = ("acknowledged_by_partner", "handed_off_to_pmsuraj", "sanctioned", "disbursed")
    for ref in refs[:3]:
        advance(client, ref, *full)
    advance(client, refs[3], "rejected")

    # Pin known durations: disbursed 10, 20 and 45 days after routing → median 20.
    for ref, days in zip(refs[:3], (10, 20, 45)):
        app = db_session.query(Application).filter_by(reference=ref).one()
        event = db_session.query(ApplicationEvent).filter_by(application_id=app.id, to_status="disbursed").one()
        event.created_at = app.created_at + timedelta(days=days)
    db_session.commit()

    m = client.get("/api/admin/metrics", headers=ADMIN_HEADERS).json()
    assert m["applications_total"] == 5
    assert m["applications_by_status"] == {"routed": 1, "acknowledged_by_partner": 0, "handed_off_to_pmsuraj": 0,
                                           "sanctioned": 0, "disbursed": 3, "rejected": 1}
    assert (m["disbursed_count"], m["median_days_routed_to_disbursed"]) == (3, 20.0)
    assert m["partners_by_routing_status"] == {"eligible": 0, "no_data": 1, "deprioritized": 1, "excluded": 1}
    assert (m["partners_with_real_metrics"], m["partners_with_demo_metrics"]) == (1, 1)
    assert (m["partners_missing_coordinates"], m["partners_missing_district"]) == (2, 2)


def test_admin_metrics_empty(client):
    m = client.get("/api/admin/metrics", headers=ADMIN_HEADERS).json()
    assert m["applications_total"] == 0 and m["median_days_routed_to_disbursed"] is None


# ── Public stats ─────────────────────────────────────────────────────────────

def test_stats_coverage(client, make_partner):
    make_partner("Bihar SCA", state="Bihar", lat=25.6, lon=85.1)
    make_partner("Goa SCA", state="Goa")
    make_partner("Closed", state="Goa", capacity_status="not_accepting")
    make_partner("MFI", state="Assam", partner_type="NBFC-MFI", eligible_scheme_codes=["AMY"],
                 npa_pct=3, metrics_as_of_date="2026-09-01", metrics_updated_by="DEMO DATA")

    s = client.get("/api/stats").json()

    assert (s["schemes"], s["partners"], s["partners_mapped"], s["states_covered"]) == (5, 4, 1, 3)
    assert s["partners_by_type"] == {"NBFC-MFI": 1, "SCA": 3}
    per = {row["code"]: row for row in s["per_scheme"]}
    assert (per["MFS"]["partners"], per["MFS"]["routable_partners"], per["MFS"]["states_with_routable_partner"]) == (3, 2, 2)
    assert per["UNY"]["partners"] == 0
    assert s["metrics_coverage"] == {"real": 0, "demo": 1, "none": 3}
    assert "npa_pct" not in str(s)  # counts only — no partner figures on the public endpoint
