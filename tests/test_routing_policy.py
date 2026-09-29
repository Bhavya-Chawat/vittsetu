"""Routing policy thresholds, status/reason text, ranking, and the admin metrics endpoints."""

from datetime import date

import pytest

from conftest import ADMIN_HEADERS
from models import Partner
from partner_engine import (
    DEPRIORITIZED, ELIGIBLE, EXCLUDED, NO_DATA, RoutingPolicy, evaluate_routing, find_nearby_partners,
)

TODAY = date(2026, 9, 29)
POLICY = RoutingPolicy()  # defaults: NPA 5/10, overdue 10/25, utilization <60/<30, 365 days


def partner(**metrics) -> Partner:
    """Unsaved Partner — evaluate_routing only reads attributes."""
    metrics.setdefault("capacity_status", "available")
    metrics.setdefault("metrics_as_of_date", "2026-09-01")
    return Partner(name="P", partner_type="SCA", **metrics)


def status(**metrics) -> str:
    return evaluate_routing(partner(**metrics), POLICY, TODAY).status


# ── Thresholds ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("npa, expected", [
    (0.0, ELIGIBLE), (4.99, ELIGIBLE),
    (5.0, DEPRIORITIZED), (9.99, DEPRIORITIZED),  # deprioritize threshold is inclusive
    (10.0, EXCLUDED), (40.0, EXCLUDED),  # exclude threshold is inclusive
])
def test_npa_thresholds(npa, expected):
    assert status(npa_pct=npa) == expected


@pytest.mark.parametrize("overdue, expected", [
    (9.99, ELIGIBLE), (10.0, DEPRIORITIZED), (24.99, DEPRIORITIZED), (25.0, EXCLUDED),
])
def test_overdue_thresholds(overdue, expected):
    assert status(overdue_pct=overdue) == expected


@pytest.mark.parametrize("util, expected", [
    (100.0, ELIGIBLE), (60.0, ELIGIBLE),  # "below" thresholds are strict
    (59.99, DEPRIORITIZED), (30.0, DEPRIORITIZED),
    (29.99, EXCLUDED), (0.0, EXCLUDED),
])
def test_utilization_thresholds(util, expected):
    assert status(fund_utilization_pct=util) == expected


def test_worst_metric_wins():
    assert status(npa_pct=1, overdue_pct=30, fund_utilization_pct=90) == EXCLUDED
    assert status(npa_pct=6, overdue_pct=2, fund_utilization_pct=90) == DEPRIORITIZED


def test_utilization_is_computed_from_funds_when_not_entered():
    assert status(allocated_funds_inr=1_000_000, disbursed_funds_inr=200_000) == EXCLUDED  # 20%
    assert status(allocated_funds_inr=1_000_000, disbursed_funds_inr=500_000) == DEPRIORITIZED  # 50%
    assert status(allocated_funds_inr=1_000_000, disbursed_funds_inr=900_000) == ELIGIBLE  # 90%
    # An entered % takes precedence over the computed one.
    assert status(fund_utilization_pct=95, allocated_funds_inr=1_000_000, disbursed_funds_inr=100_000) == ELIGIBLE
    # Allocation of zero can't produce a ratio.
    assert status(allocated_funds_inr=0, disbursed_funds_inr=0) == NO_DATA


def test_custom_policy_thresholds():
    strict = RoutingPolicy(npa_deprioritize_pct=2, npa_exclude_pct=4)
    assert evaluate_routing(partner(npa_pct=3), strict, TODAY).status == DEPRIORITIZED
    assert evaluate_routing(partner(npa_pct=4), strict, TODAY).status == EXCLUDED
    assert evaluate_routing(partner(npa_pct=3), POLICY, TODAY).status == ELIGIBLE


def test_policy_rejects_inverted_thresholds():
    with pytest.raises(ValueError):
        RoutingPolicy(npa_deprioritize_pct=12, npa_exclude_pct=10)
    with pytest.raises(ValueError):
        RoutingPolicy(utilization_exclude_below_pct=70, utilization_deprioritize_below_pct=60)


def test_policy_from_env():
    policy = RoutingPolicy.from_env({
        "VITTSETU_ROUTING_NPA_EXCLUDE_PCT": "15",
        "VITTSETU_ROUTING_MAX_METRICS_AGE_DAYS": "none",
        "VITTSETU_ROUTING_OVERDUE_EXCLUDE_PCT": "",  # blank = keep default
    })
    assert policy.npa_exclude_pct == 15
    assert policy.max_metrics_age_days is None
    assert policy.overdue_exclude_pct == 25
    assert RoutingPolicy.from_env({}) == RoutingPolicy()


# ── No data / stale / capacity ───────────────────────────────────────────────

def test_no_metrics_is_no_data_not_a_guess():
    decision = evaluate_routing(partner(metrics_as_of_date=None), POLICY, TODAY)
    assert decision.status == NO_DATA
    assert "No NPA, overdue or fund-utilization figures" in decision.reason


def test_partial_metrics_are_evaluated_and_gaps_named():
    decision = evaluate_routing(partner(npa_pct=2.0), POLICY, TODAY)
    assert decision.status == ELIGIBLE
    assert "NPA 2%" in decision.reason
    assert "No overdue/utilization data on record" in decision.reason


def test_stale_metrics_become_no_data():
    old = partner(npa_pct=15, metrics_as_of_date="2025-09-28")  # 366 days before TODAY
    assert evaluate_routing(old, POLICY, TODAY).status == NO_DATA
    assert "older than 365 days" in evaluate_routing(old, POLICY, TODAY).reason
    assert evaluate_routing(partner(npa_pct=15, metrics_as_of_date="2025-09-29"), POLICY, TODAY).status == EXCLUDED
    assert evaluate_routing(old, RoutingPolicy(max_metrics_age_days=None), TODAY).status == EXCLUDED


def test_not_accepting_always_excludes_even_with_healthy_metrics():
    decision = evaluate_routing(partner(capacity_status="not_accepting", npa_pct=1), POLICY, TODAY)
    assert decision.status == EXCLUDED
    assert "not currently accepting" in decision.reason


def test_reasons_are_human_readable_and_demo_is_flagged():
    real = evaluate_routing(partner(npa_pct=12.5, overdue_pct=30), POLICY, TODAY)
    assert real.reason == (
        "Routed away: NPA 12.5% is at or above the 10% limit; overdues 30% are at or above the 25% limit "
        "(figures as of 2026-09-01)."
    )
    assert "DEMO" not in real.reason

    demo = evaluate_routing(partner(npa_pct=6, metrics_updated_by="DEMO DATA"), POLICY, TODAY)
    assert demo.status == DEPRIORITIZED
    assert "DEMO DATA" in demo.reason


# ── Ranking ──────────────────────────────────────────────────────────────────

def test_ranking_routing_status_then_capacity_then_distance(db_session, make_partner):
    near, far = (12.97, 77.59), (13.5, 78.5)
    make_partner("Deprioritized Near", lat=near[0], lon=near[1], npa_pct=7, metrics_as_of_date="2026-09-01")
    make_partner("NoData Near", lat=near[0], lon=near[1])
    make_partner("Eligible Far", lat=far[0], lon=far[1], npa_pct=1, metrics_as_of_date="2026-09-01")
    make_partner("Eligible Near Limited", lat=near[0], lon=near[1], npa_pct=1,
                 metrics_as_of_date="2026-09-01", capacity_status="limited")
    make_partner("Eligible Near", lat=near[0] + 0.01, lon=near[1], npa_pct=1, metrics_as_of_date="2026-09-01")
    make_partner("Excluded Near", lat=near[0], lon=near[1], npa_pct=20, metrics_as_of_date="2026-09-01")

    result = find_nearby_partners(db_session, 12.97, 77.59, None, None, "MFS", policy=POLICY, today=TODAY)

    assert [m.partner.name for m in result.partners] == [
        "Eligible Near", "Eligible Far",  # eligible + available, by distance
        "Eligible Near Limited",  # eligible but limited capacity
        "NoData Near",
        "Deprioritized Near",
    ]
    assert [(m.partner.name, m.routing.status) for m in result.excluded] == [("Excluded Near", EXCLUDED)]


def test_state_with_only_excluded_partners_falls_back_with_explanation(db_session, make_partner):
    make_partner("Goa Stressed", state="Goa", npa_pct=20, metrics_as_of_date="2026-09-01")
    make_partner("Delhi OK", state="Delhi")

    result = find_nearby_partners(db_session, None, None, "Goa", None, "MFS", policy=POLICY, today=TODAY)

    assert [m.partner.name for m in result.partners] == ["Delhi OK"]
    assert [m.partner.name for m in result.excluded] == ["Goa Stressed"]
    assert "currently routed away" in result.note


def test_nearby_api_exposes_routing_and_metrics(client, make_partner):
    make_partner("Demo Partner", npa_pct=6, overdue_pct=3, fund_utilization_pct=80,
                 metrics_as_of_date=date.today().isoformat(), metrics_updated_by="DEMO DATA")
    make_partner("Blank Partner")

    body = client.post("/api/partners/nearby", json={"scheme_code": "MFS"}).json()

    by_name = {p["name"]: p for p in body["partners"]}
    demo, blank = by_name["Demo Partner"], by_name["Blank Partner"]
    assert demo["routing_status"] == "deprioritized"
    assert demo["metrics_is_demo"] is True
    assert "DEMO DATA" in demo["routing_reason"]
    assert demo["npa_pct"] == 6
    assert blank["routing_status"] == "no_data"
    assert blank["metrics_is_demo"] is False
    assert blank["npa_pct"] is None


# ── Admin: metrics PATCH ─────────────────────────────────────────────────────

def test_patch_metrics_sets_figures_and_reroutes(client, make_partner):
    p = make_partner("Partner")
    url = f"/api/admin/partners/{p.id}/metrics"

    assert client.patch(url, json={"npa_pct": 12, "metrics_as_of_date": "2026-09-01"}).status_code == 401

    resp = client.patch(url, headers=ADMIN_HEADERS, json={
        "npa_pct": 12, "overdue_pct": 4, "metrics_as_of_date": date.today().isoformat(), "updated_by": "ops-desk",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["routing_status"] == "excluded"
    assert body["metrics_updated_by"] == "ops-desk"

    # Omitted fields are kept; explicit null clears one.
    body = client.patch(url, headers=ADMIN_HEADERS, json={
        "npa_pct": None, "metrics_as_of_date": date.today().isoformat(),
    }).json()
    assert body["npa_pct"] is None
    assert body["overdue_pct"] == 4
    assert body["routing_status"] == "eligible"


@pytest.mark.parametrize("payload", [
    {"npa_pct": 101, "metrics_as_of_date": "2026-09-01"},
    {"npa_pct": -1, "metrics_as_of_date": "2026-09-01"},
    {"npa_pct": 5},  # undated figures are refused
    {"npa_pct": 5, "metrics_as_of_date": "2999-01-01"},
    {"allocated_funds_inr": 100, "disbursed_funds_inr": 200, "metrics_as_of_date": "2026-09-01"},
    {"npa_pct": 5, "metrics_as_of_date": "2026-09-01", "updated_by": "DEMO DATA"},
])
def test_patch_metrics_validation(client, make_partner, payload):
    p = make_partner("Partner")
    assert client.patch(f"/api/admin/partners/{p.id}/metrics", headers=ADMIN_HEADERS, json=payload).status_code == 422


def test_real_figures_replace_demo_figures_entirely(client, make_partner):
    p = make_partner("Partner", npa_pct=3, overdue_pct=30, metrics_as_of_date="2026-09-01",
                     metrics_updated_by="DEMO DATA")

    body = client.patch(f"/api/admin/partners/{p.id}/metrics", headers=ADMIN_HEADERS,
                        json={"npa_pct": 2, "metrics_as_of_date": "2026-09-15"}).json()

    assert body["npa_pct"] == 2
    assert body["overdue_pct"] is None  # demo overdue figure not carried over as "real"
    assert body["metrics_is_demo"] is False


# ── Admin: CSV template + import ─────────────────────────────────────────────

def _upload(client, csv_text, **params):
    return client.post("/api/admin/partners/metrics/import", headers=ADMIN_HEADERS, params=params,
                       files={"file": ("metrics.csv", csv_text.encode("utf-8-sig"), "text/csv")})


def test_csv_template_lists_partners_and_hides_demo_values(client, make_partner):
    make_partner("Real", npa_pct=3.5, metrics_as_of_date="2026-09-01", metrics_updated_by="ops")
    make_partner("Demo", npa_pct=9.0, metrics_as_of_date="2026-09-01", metrics_updated_by="DEMO DATA")

    resp = client.get("/api/admin/partners/metrics/template.csv", headers=ADMIN_HEADERS)

    assert resp.status_code == 200
    lines = resp.text.strip().splitlines()
    assert lines[0].startswith("partner_id,name,partner_type,state,fund_utilization_pct,npa_pct")
    assert "3.5" in lines[1] and "2026-09-01" in lines[1]
    assert "9.0" not in lines[2] and "2026-09-01" not in lines[2]


def test_csv_import_applies_rows(client, make_partner, db_session):
    a, b, c = make_partner("A"), make_partner("B"), make_partner("C")
    csv_text = (
        "partner_id,name,npa_pct,overdue_pct,fund_utilization_pct,metrics_as_of_date\n"
        f"{a.id},A,12.5%,3,\"80\",2026-09-01\n"  # spreadsheet-style "%" and quoting
        f"{b.id},B,1.5,,,2026-09-01\n"  # empty cells = no data
        f"{c.id},C,,,,\n"  # untouched template row
    )

    body = _upload(client, csv_text, updated_by="bulk-upload").json()

    assert body == {"dry_run": False, "updated": 2, "unchanged": 0, "skipped_blank": 1, "partner_ids": [a.id, b.id]}
    db_session.expire_all()
    assert (a.npa_pct, a.overdue_pct, a.fund_utilization_pct, a.metrics_updated_by) == (12.5, 3, 80, "bulk-upload")
    assert b.npa_pct == 1.5 and b.overdue_pct is None
    assert c.npa_pct is None

    # Re-importing the same figures changes nothing.
    assert _upload(client, csv_text, updated_by="bulk-upload").json()["unchanged"] == 2


def test_csv_import_is_all_or_nothing(client, make_partner, db_session):
    a = make_partner("A")
    csv_text = (
        "partner_id,npa_pct,metrics_as_of_date\n"
        f"{a.id},4,2026-09-01\n"
        "999999,4,2026-09-01\n"
        f"{a.id},4,2026-09-01\n"
        "x,4,2026-09-01\n"
        f"{a.id},abc,2026-09-01\n"
    )

    resp = _upload(client, csv_text)

    assert resp.status_code == 422
    lines = [e["line"] for e in resp.json()["detail"]["errors"]]
    assert lines == [3, 4, 5, 6]
    db_session.expire_all()
    assert a.npa_pct is None  # valid first row was not applied either


def test_csv_import_dry_run_and_missing_columns(client, make_partner, db_session):
    a = make_partner("A")
    body = _upload(client, f"partner_id,npa_pct,metrics_as_of_date\n{a.id},4,2026-09-01\n", dry_run="true").json()
    assert body["dry_run"] is True and body["updated"] == 1
    db_session.expire_all()
    assert a.npa_pct is None

    assert _upload(client, "partner_id,npa_pct\n1,4\n").status_code == 400


# ── Demo seeder ──────────────────────────────────────────────────────────────

def test_seed_demo_metrics_labels_everything_and_never_overwrites_real(db_session, make_partner):
    import seed_demo_metrics

    real = make_partner("Real", npa_pct=2, metrics_as_of_date="2026-09-01", metrics_updated_by="ops")
    for i in range(30):
        make_partner(f"P{i}")

    counts = seed_demo_metrics.seed(today=TODAY)

    assert counts["skipped_real"] == 1
    assert counts["filled"] + counts["left_no_data"] == 30
    assert counts["filled"] > 0 and counts["left_no_data"] > 0
    db_session.expire_all()
    assert (real.npa_pct, real.metrics_updated_by) == (2, "ops")
    others = db_session.query(Partner).filter(Partner.id != real.id).all()
    for p in others:
        if p.npa_pct is not None:
            assert p.metrics_updated_by == "DEMO DATA" and p.metrics_as_of_date == TODAY.isoformat()
    statuses = {evaluate_routing(p, POLICY, TODAY).status for p in others}
    assert statuses == {ELIGIBLE, DEPRIORITIZED, EXCLUDED, NO_DATA}  # demo exercises every path

    assert seed_demo_metrics.clear() == counts["filled"]
    db_session.expire_all()
    assert real.npa_pct == 2
    assert all(p.npa_pct is None for p in others)
