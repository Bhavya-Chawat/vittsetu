"""Application routing: creation + validation, public status lookup, admin lifecycle."""

import re

import pytest

from conftest import ADMIN_HEADERS
from models import Application, ApplicationEvent


def submit(client, partner, **overrides):
    payload = {"scheme_code": "MFS", "partner_id": partner.id, "consent": True, **overrides}
    return client.post("/api/applications", json=payload)


@pytest.fixture
def partner(make_partner):
    return make_partner("Karnataka SCA", phone="080-1234", address="Bengaluru 560001", state="Karnataka")


# ── Create ───────────────────────────────────────────────────────────────────

def test_create_routes_application_and_records_event(client, partner, db_session):
    resp = submit(client, partner, applicant_name="Asha", applicant_contact="98450 00000",
                  state="Karnataka", district="Mysuru", project_cost=100000)

    assert resp.status_code == 201
    body = resp.json()
    assert re.fullmatch(r"VS-\d{4}-\d{6}", body["reference"])
    assert body["status"] == "routed"
    assert body["partner_name"] == "Karnataka SCA"
    assert body["requested_loan_amount"] == 90000  # 90% of cost, via the calculator
    assert [e["to_status"] for e in body["timeline"]] == ["routed"]
    assert "Asha" not in resp.text and "98450" not in resp.text  # no PII echoed back

    app = db_session.query(Application).filter_by(reference=body["reference"]).one()
    assert app.applicant_name == "Asha"
    assert app.consent_given_at is not None
    assert app.routing_status_at_submission == "no_data"
    [event] = db_session.query(ApplicationEvent).filter_by(application_id=app.id).all()
    assert (event.event_type, event.actor) == ("created", "applicant")


def test_references_are_sequential_and_unique(client, partner):
    first = submit(client, partner).json()["reference"]
    second = submit(client, partner).json()["reference"]
    assert first != second
    assert int(second[-6:]) == int(first[-6:]) + 1


def test_contact_is_optional_and_blank_strings_are_dropped(client, partner, db_session):
    body = submit(client, partner, applicant_name="  ", applicant_contact="").json()
    app = db_session.query(Application).filter_by(reference=body["reference"]).one()
    assert app.applicant_name is None and app.applicant_contact is None


def test_consent_is_required(client, partner):
    resp = submit(client, partner, consent=False)
    assert resp.status_code == 400
    assert "Consent" in resp.json()["detail"]
    assert client.post("/api/applications", json={"scheme_code": "MFS", "partner_id": partner.id}).status_code == 422


def test_partner_must_channel_the_scheme(client, make_partner):
    nbfc = make_partner("MFI", partner_type="NBFC-MFI", eligible_scheme_codes=["AMY"])
    resp = submit(client, nbfc, scheme_code="MFS")
    assert resp.status_code == 400
    assert "does not channel" in resp.json()["detail"]
    assert submit(client, nbfc, scheme_code="AMY").status_code == 201


def test_excluded_partner_cannot_receive_applications(client, make_partner):
    stressed = make_partner("Stressed", npa_pct=15, metrics_as_of_date="2026-09-01", metrics_updated_by="ops")
    closed = make_partner("Closed", capacity_status="not_accepting")

    resp = submit(client, stressed)
    assert resp.status_code == 409
    assert "NPA 15%" in resp.json()["detail"]
    assert submit(client, closed).status_code == 409


def test_deprioritized_and_no_data_partners_are_still_routable(client, make_partner):
    watch = make_partner("Watch", npa_pct=7, metrics_as_of_date="2026-09-01", metrics_updated_by="ops")
    assert submit(client, watch).json()["status"] == "routed"


def test_unknown_scheme_or_partner(client, partner):
    assert submit(client, partner, scheme_code="NOPE").status_code == 404
    assert client.post("/api/applications", json={"scheme_code": "MFS", "partner_id": 99999, "consent": True}).status_code == 404


def test_project_cost_must_fit_scheme_band(client, partner):
    assert submit(client, partner, project_cost=500000).status_code == 400  # MFS max is 1.4 lakh
    assert submit(client, partner, project_cost=0).status_code == 422
    # Education loans have no upper project-cost band — the loan is capped instead.
    assert submit(client, partner, scheme_code="ELS", project_cost=6_000_000).json()["requested_loan_amount"] == 4_000_000


# ── Public status lookup ─────────────────────────────────────────────────────

def test_public_lookup_has_no_pii(client, partner):
    ref = submit(client, partner, applicant_name="Asha Devi", applicant_contact="asha@example.com",
                 district="Mysuru", project_cost=100000).json()["reference"]

    resp = client.get(f"/api/applications/{ref.lower()}")  # case-insensitive

    assert resp.status_code == 200
    body = resp.json()
    assert body["reference"] == ref and body["status"] == "routed"
    assert body["partner_phone"] == "080-1234"  # partner contact is public directory data
    for secret in ("Asha", "asha@example.com", "Mysuru", "applicant", "note", "actor", "project_cost"):
        assert secret not in resp.text


def test_public_lookup_unknown_reference(client):
    assert client.get("/api/applications/VS-2026-999999").status_code == 404


# ── Admin lifecycle ──────────────────────────────────────────────────────────

def patch_status(client, ref, status, **extra):
    return client.patch(f"/api/admin/applications/{ref}/status", headers=ADMIN_HEADERS,
                        json={"status": status, **extra})


def test_admin_endpoints_require_token(client, partner):
    ref = submit(client, partner).json()["reference"]
    assert client.get("/api/admin/applications").status_code == 401
    assert client.patch(f"/api/admin/applications/{ref}/status", json={"status": "rejected"}).status_code == 401


def test_admin_list_includes_pii_and_filters_by_status(client, partner):
    ref1 = submit(client, partner, applicant_name="Asha").json()["reference"]
    ref2 = submit(client, partner).json()["reference"]
    patch_status(client, ref2, "rejected")

    rows = client.get("/api/admin/applications", headers=ADMIN_HEADERS).json()
    assert [r["reference"] for r in rows] == [ref2, ref1]  # newest first
    assert rows[1]["applicant_name"] == "Asha"
    assert rows[1]["routing_status_at_submission"] == "no_data"

    routed = client.get("/api/admin/applications", headers=ADMIN_HEADERS, params={"status": "routed"}).json()
    assert [r["reference"] for r in routed] == [ref1]


def test_full_happy_path_lifecycle(client, partner):
    ref = submit(client, partner).json()["reference"]
    for status in ("acknowledged_by_partner", "handed_off_to_pmsuraj", "sanctioned", "disbursed"):
        resp = patch_status(client, ref, status, note=f"moved to {status}", updated_by="ops")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == status

    admin_view = resp.json()
    assert admin_view["timeline"][-1]["actor"] == "admin:ops"
    assert admin_view["timeline"][-1]["note"] == "moved to disbursed"

    public = client.get(f"/api/applications/{ref}").json()
    assert [e["to_status"] for e in public["timeline"]] == [
        "routed", "acknowledged_by_partner", "handed_off_to_pmsuraj", "sanctioned", "disbursed",
    ]
    assert "moved to" not in str(public)  # admin notes stay private


@pytest.mark.parametrize("path, target", [
    ([], "sanctioned"),  # can't skip ahead
    ([], "routed"),  # already there
    (["acknowledged_by_partner", "handed_off_to_pmsuraj"], "acknowledged_by_partner"),  # no going back
    (["rejected"], "acknowledged_by_partner"),  # rejected is final
    (["acknowledged_by_partner", "handed_off_to_pmsuraj", "sanctioned", "disbursed"], "rejected"),  # disbursed is final
])
def test_invalid_transitions_are_refused(client, partner, path, target):
    ref = submit(client, partner).json()["reference"]
    for status in path:
        assert patch_status(client, ref, status).status_code == 200
    resp = patch_status(client, ref, target)
    assert resp.status_code == 409


@pytest.mark.parametrize("path", [[], ["acknowledged_by_partner"], ["acknowledged_by_partner", "handed_off_to_pmsuraj", "sanctioned"]])
def test_reject_is_allowed_from_any_open_status(client, partner, path):
    ref = submit(client, partner).json()["reference"]
    for status in path:
        patch_status(client, ref, status)
    assert patch_status(client, ref, "rejected").json()["status"] == "rejected"


def test_unknown_status_value_is_rejected(client, partner):
    ref = submit(client, partner).json()["reference"]
    assert patch_status(client, ref, "approved").status_code == 422
