"""Recommender: activity taxonomy, cost boundaries, per-scheme income limits,
availability-aware best fit with trade-offs, and education matching."""

import json
import typing

import pytest

import activity_taxonomy
from models import Scheme
from schemas import ActivityCategoryId
from schemas import SchemeComparison
from scheme_engine import _rate_sentence_end, match_course

BIHAR_PROFILE = {"annual_family_income": 200_000, "is_sc_category": True, "state": "Bihar", "purpose": "business"}


def recommend(client, cost, profile=None, **business):
    return client.post("/api/recommend", json={
        "profile": profile or BIHAR_PROFILE,
        "business": {"project_type": business.pop("project_type", "Tailoring"), "estimated_cost": cost, **business},
    }).json()


def codes(items):
    return [m["scheme"]["code"] if "scheme" in m else m["code"] for m in items]


# ── Activity taxonomy ────────────────────────────────────────────────────────

def test_taxonomy_ids_match_api_schema():
    assert set(activity_taxonomy.category_ids()) == set(typing.get_args(ActivityCategoryId))


@pytest.mark.parametrize("text, category", [
    ("Tailoring shop", "services"),  # tie with trade's "shop" → services is listed first in tie_break_order
    ("tea stall near bus stand", "trade_retail"),  # "tea stall" (2 words) outweighs "bus" (1)
    ("Tea plantation in Assam", "plantation"),
    ("Dairy farm with 5 cows", "agriculture_allied"),
    ("house construction contractor", "construction"),
    ("Buying two E-Rickshaws", "transport"),  # hyphen variant + plural
    ("atta chakki / flour mill", "manufacturing"),
    ("किराना दुकान", "trade_retail"),
    ("सिलाई केंद्र", "services"),
    ("Kirana STORE", "trade_retail"),  # case-insensitive
])
def test_classification(text, category):
    assert activity_taxonomy.classify(text).category == category


def test_classification_is_word_bounded_and_can_be_empty():
    assert activity_taxonomy.classify("carpet").category is None  # no "car"/"pet" style substring hits
    assert activity_taxonomy.classify("").category is None
    assert activity_taxonomy.classify("something else entirely").matched_keywords == ()


def test_taxonomy_is_data(tmp_path, monkeypatch):
    data = json.loads(activity_taxonomy.TAXONOMY_PATH.read_text(encoding="utf-8"))
    for cat in data["categories"]:
        if cat["id"] == "transport":
            cat["keywords"].append("bullock cart")
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(activity_taxonomy, "TAXONOMY_PATH", path)
    activity_taxonomy.load_taxonomy.cache_clear()
    try:
        assert activity_taxonomy.classify("bullock cart hire").category == "transport"
    finally:
        activity_taxonomy.load_taxonomy.cache_clear()


def test_activity_endpoints(client):
    cats = client.get("/api/activities").json()
    assert [c["id"] for c in cats][:2] == ["agriculture_allied", "plantation"]
    assert all(c["label_hi"] for c in cats)
    body = client.post("/api/activities/classify", json={"text": "coffee plantation"}).json()
    assert body == {"category": "plantation", "label": "Plantation", "source": "keyword_match",
                    "matched_keywords": ["plantation", "coffee", "coffee plantation"]}


def test_interpret_returns_deterministic_activity(client, fake_llm):
    fake_llm.reply = lambda prompt: json.dumps(
        {"purpose": "business", "project_type": "Tea stall", "estimated_cost": 50000}
    )
    body = client.post("/api/interpret", json={"text": "I want to open a small stall selling tea"}).json()
    assert body["activity_category"] == "trade_retail"

    fake_llm.reply = lambda prompt: json.dumps({"purpose": "education", "course_name": "B.Tech", "course_fee": 400000})
    assert client.post("/api/interpret", json={"text": "btech fees"}).json()["activity_category"] is None


def test_recommend_reports_activity_source(client):
    guessed = recommend(client, 1_000_000, project_type="Rubber plantation")
    assert guessed["activity"]["category"] == "plantation" and guessed["activity"]["source"] == "keyword_match"
    confirmed = recommend(client, 1_000_000, project_type="Rubber plantation", activity_category="manufacturing")
    assert confirmed["activity"] == {"category": "manufacturing", "label": "Manufacturing & processing",
                                     "source": "user_confirmed", "matched_keywords": []}


def test_term_loan_moratorium_follows_activity(client):
    body = recommend(client, 1_000_000, project_type="Tea plantation")
    [row] = [r for r in body["comparison"] if r["code"] == "TERM_LOAN"]
    assert row["moratorium_months"] == 12
    assert any("12-month moratorium for plantation" in r for m in body["matched"] for r in m["reasons"])
    assert [r for r in recommend(client, 1_000_000, project_type="Kirana store")["comparison"]
            if r["code"] == "TERM_LOAN"][0]["moratorium_months"] == 6


# ── Cost boundaries ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("cost, matched, rejected_reason", [
    (140_000, {"MFS", "AMY", "UNY"}, {"TERM_LOAN": "below this scheme's minimum"}),
    (140_001, {"TERM_LOAN", "UNY"}, {"MFS": "exceeds this scheme's maximum", "AMY": "exceeds"}),
    (500_000, {"TERM_LOAN", "UNY"}, {}),
    (500_001, {"TERM_LOAN"}, {"UNY": "exceeds this scheme's maximum ₹500,000"}),
    (5_000_000, {"TERM_LOAN"}, {}),
    (5_000_001, set(), {"TERM_LOAN": "exceeds this scheme's maximum ₹5,000,000"}),
])
def test_cost_boundaries(client, cost, matched, rejected_reason):
    body = recommend(client, cost)
    assert set(codes(body["matched"])) == matched
    rejected = {m["scheme"]["code"]: " ".join(m["reasons"]) for m in body["rejected"]}
    assert set(rejected) == {"MFS", "TERM_LOAN", "AMY", "UNY"} - matched
    for code, fragment in rejected_reason.items():
        assert fragment in rejected[code]
    assert (body["best_fit"] is None) == (not matched)


# ── Income limits ────────────────────────────────────────────────────────────

def test_per_scheme_income_limit(client, db_session):
    db_session.query(Scheme).filter_by(code="AMY").one().income_limit_annual = 300_000
    db_session.commit()
    profile = {**BIHAR_PROFILE, "annual_family_income": 400_000}

    body = recommend(client, 100_000, profile=profile)

    assert set(codes(body["matched"])) == {"MFS", "UNY"}
    [amy] = [m for m in body["rejected"] if m["scheme"]["code"] == "AMY"]
    assert amy["reasons"] == ["Annual family income of ₹400,000 exceeds this scheme's ₹300,000 ceiling."]
    assert any("some schemes have lower ceilings" in r for r in body["eligibility_reasons"])


def test_eligibility_uses_highest_ceiling_for_purpose(client, db_session):
    db_session.query(Scheme).filter_by(code="ELS").one().income_limit_annual = 800_000
    db_session.commit()
    edu = {**BIHAR_PROFILE, "annual_family_income": 700_000, "purpose": "education"}
    biz = {**BIHAR_PROFILE, "annual_family_income": 700_000}
    assert client.post("/api/eligibility", json={"profile": edu}).json()["eligible"] is True
    assert client.post("/api/eligibility", json={"profile": biz}).json()["eligible"] is False


# ── Best fit ─────────────────────────────────────────────────────────────────

def test_best_fit_is_cheapest_reachable_scheme(client, make_partner):
    make_partner("Bihar SCA", state="Bihar")  # channels MFS
    make_partner("Bihar MFI", state="Bihar", partner_type="NBFC-MFI", eligible_scheme_codes=["AMY"])

    body = recommend(client, 100_000)
    best = body["best_fit"]

    assert best["scheme_code"] == "MFS"
    # MFS charges 6.5% through every partner type, so no partner type is singled out.
    assert best["effective_rate_pct"] == 6.5 and best["effective_rate_partner_type"] is None
    assert best["reasons"][0] == "Lowest effective interest among the 3 matching schemes: 6.5% p.a."
    assert "1 routable partner in Bihar." in best["reasons"]
    assert codes(body["comparison"]) == ["MFS", "AMY", "UNY"]  # UNY: no partner at all → last
    assert [r["is_best_fit"] for r in body["comparison"]] == [True, False, False]
    assert codes(body["matched"]) == ["MFS", "AMY", "UNY"]

    amy = best["alternatives"]["AMY"]
    assert amy[0] == "Higher interest: 15% vs 6.5% p.a."
    assert any(t.endswith("more interest over the full tenure (at the maximum loan and tenure).") for t in amy)


def test_reachability_beats_rate(client, make_partner):
    # Only an NBFC-MFI (AMY, 15%) operates in Bihar; the SCA (MFS, 6.5%) is elsewhere.
    make_partner("Goa SCA", state="Goa")
    make_partner("Bihar MFI", state="Bihar", partner_type="NBFC-MFI", eligible_scheme_codes=["AMY"])

    best = recommend(client, 100_000)["best_fit"]

    assert best["scheme_code"] == "AMY"
    assert best["reasons"][0] == ("Micro Finance Scheme (MFS) is cheaper (6.5%) but has no routable partner "
                                  "near you, so Aajeevika Micro-Finance Yojana (AMY) (15%) is "
                                  "the best option you can reach.")
    assert best["alternatives"]["MFS"][0].startswith("Lower interest (6.5% vs 15% p.a.)")


def test_excluded_partners_do_not_count_as_reachable(client, make_partner):
    make_partner("Bihar SCA (stressed)", state="Bihar", npa_pct=20, metrics_as_of_date="2026-09-01",
                 metrics_updated_by="ops")
    make_partner("Bihar MFI", state="Bihar", partner_type="NBFC-MFI", eligible_scheme_codes=["AMY"])
    assert recommend(client, 100_000)["best_fit"]["scheme_code"] == "AMY"


def test_uny_effective_rate_follows_reachable_partner_types(client, make_partner):
    make_partner("Bihar SFB", state="Bihar", partner_type="Small Finance Bank", eligible_scheme_codes=["UNY"])
    [uny] = [r for r in recommend(client, 300_000)["comparison"] if r["code"] == "UNY"]
    assert (uny["effective_rate_pct"], uny["effective_rate_partner_type"], uny["rate_display"]) == (
        15, "Small Finance Bank", "13–15%")

    make_partner("Bihar Coop", state="Bihar", partner_type="Cooperative Bank", eligible_scheme_codes=["UNY"])
    [uny] = [r for r in recommend(client, 300_000)["comparison"] if r["code"] == "UNY"]
    assert (uny["effective_rate_pct"], uny["effective_rate_partner_type"]) == (13, "Cooperative Bank")


def test_trade_offs_explain_longer_tenure(client, make_partner):
    make_partner("Bihar SCA", state="Bihar")
    uny = recommend(client, 100_000)["best_fit"]["alternatives"]["UNY"]
    assert any(t.startswith("Longer repayment (60 vs 36 months), so a smaller quarterly instalment") for t in uny)
    assert "Rate depends on the partner: 13–15% by partner type." in uny
    assert uny[-1].startswith("Channelled via Cooperative Bank, Cooperative Society, Small Finance Bank.")


def test_location_availability(client, make_partner):
    make_partner("Patna SCA", state="Bihar", lat=25.61, lon=85.14)
    near = client.post("/api/recommend", json={
        "profile": {**BIHAR_PROFILE, "state": None}, "business": {"project_type": "shop", "estimated_cost": 100_000},
        "lat": 25.59, "lon": 85.13,
    }).json()
    [mfs] = [r for r in near["comparison"] if r["code"] == "MFS"]
    assert mfs["availability"]["level"] == "local"
    assert mfs["availability"]["nearest_partner_name"] == "Patna SCA"

    far = client.post("/api/recommend", json={
        "profile": {**BIHAR_PROFILE, "state": None}, "business": {"project_type": "shop", "estimated_cost": 100_000},
        "lat": 12.97, "lon": 77.59,  # Bengaluru
    }).json()
    assert [r for r in far["comparison"] if r["code"] == "MFS"][0]["availability"]["level"] == "elsewhere"


def test_no_state_no_location_is_unspecified(client, make_partner):
    make_partner("Some SCA", state="Goa")
    body = recommend(client, 100_000, profile={**BIHAR_PROFILE, "state": None})
    [mfs] = [r for r in body["comparison"] if r["code"] == "MFS"]
    assert mfs["availability"]["level"] == "unspecified"
    assert "add your state" in mfs["availability"]["summary"]


# ── Education ────────────────────────────────────────────────────────────────


@pytest.fixture
def courses(db_session):
    return db_session.query(Scheme).filter_by(code="ELS").one().education_criteria["courses"]


@pytest.mark.parametrize("name, expected", [
    ("B.Sc Nursing", "Nursing (B.Sc / M.Sc)"),  # "nursing" is rarer than "bsc" → Nursing beats Physiotherapy
    ("B.Tech Computer Science", "Engineering (Diploma / B.Tech / B.E / M.Tech / M.E)"),
    ("Diploma in Pharmacy", "Pharmacy (B.Pharma / M.Pharma)"),  # "diploma" is generic, not Engineering
    ("MBBS", "Medical (MBBS / MD / MS)"),
    ("MBA", "Management (BBA / MBA)"),
    ("PhD in Chemistry", "Doctoral Studies (M.Phil / PhD)"),
    ("CA", "Chartered Accountancy (CA)"),
    ("Fashion designing", None),
])
def test_course_matching(courses, name, expected):
    assert match_course(name, courses) == expected


def edu(client, **education):
    return client.post("/api/recommend", json={
        "profile": {**BIHAR_PROFILE, "purpose": "education"},
        "education": {"course_name": "B.Sc Nursing", "course_fee": 600_000, **education},
    }).json()


def test_education_returns_matched_course_and_moratorium(client):
    body = edu(client, course_duration_months=48)
    [match] = body["matched"]
    assert match["matched_course"] == "Nursing (B.Sc / M.Sc)"
    assert "Moratorium: 60 months — course period plus 1 year, where repayment has not started." in match["reasons"]
    assert body["best_fit"]["scheme_code"] == "ELS"
    assert "Recognized course: Nursing (B.Sc / M.Sc)." in body["best_fit"]["reasons"]
    [row] = body["comparison"]
    assert (row["moratorium_months"], row["tenure_max_months"]) == (60, 60 + 144)
    assert row["quarterly_instalment"] is not None


def test_education_without_duration_or_after_repayment_started(client):
    [row] = edu(client)["comparison"]
    assert row["moratorium_months"] is None and row["quarterly_instalment"] is None
    assert "add your course duration" in " ".join(edu(client)["matched"][0]["reasons"])

    [row] = edu(client, repayment_started=True)["comparison"]
    assert (row["moratorium_months"], row["tenure_max_months"]) == (6, 6 + 120)


def test_unrecognized_course_still_matches_with_warning(client):
    [match] = edu(client, course_name="Fashion designing", course_duration_months=24)["matched"]
    assert match["matched_course"] is None
    assert any("not automatically matched" in r for r in match["reasons"])


def test_reason_sentences_end_with_one_period(client, make_partner):
    only = recommend(client, 600_000)["best_fit"]["reasons"][0]
    assert only == "The only scheme that matches: 8% p.a."

    make_partner("Bihar SFB", state="Bihar", partner_type="Small Finance Bank", eligible_scheme_codes=["UNY"])
    make_partner("Bihar Coop", state="Bihar", partner_type="Cooperative Bank", eligible_scheme_codes=["UNY"])
    make_partner("Bihar SCA", state="Bihar")
    body = recommend(client, 300_000)
    assert body["best_fit"]["reasons"][0] == "Lowest effective interest among the 2 matching schemes: 8% p.a."

    # With a partner-dependent rate the partner type is named, still with a single closing period.
    [uny] = [SchemeComparison(**r) for r in body["comparison"] if r["code"] == "UNY"]
    assert _rate_sentence_end(uny) == "13% p.a. via Cooperative Bank."


def test_moratorium_reason_is_not_repetitive(client, make_partner):
    make_partner("Bihar SCA", state="Bihar")
    assert ("3-month moratorium, within the 3-year repayment period; repay within 36 months of disbursement."
            in recommend(client, 100_000)["best_fit"]["reasons"])
    assert ("60-month moratorium (course period plus 1 year, where repayment has not started); "
            "repay within 204 months of disbursement." in edu(client, course_duration_months=48)["best_fit"]["reasons"])
