"""Calculator: hand-verified instalments per scheme, guideline rules, frequencies, schedule integrity.

Expected instalments were computed independently of financial_engine — exact
rational arithmetic, bisecting for the payment that brings the balance to
zero — then rounded to the paisa. Principal after moratorium is worked by hand
in each case's comment (simple interest on the amount disbursed, capitalized).
"""

from decimal import Decimal

import pytest

from financial_engine import LoanContext, calculate_loan, instalment_amount
from models import Scheme


@pytest.fixture
def scheme(db_session):
    return lambda code: db_session.query(Scheme).filter_by(code=code).one()


def test_textbook_instalment():
    # ₹1,00,000 at 12% p.a., 12 monthly instalments — the standard worked example.
    assert instalment_amount(Decimal(100000), 12, 12, 12) == Decimal("8884.88")


# ── Hand-verified per scheme (quarterly, maximum loan and tenure) ────────────

@pytest.mark.parametrize("code, cost, kwargs, principal, n, instalment", [
    # MFS: loan 90,000 (90%); 90,000 × 6.5% × 3/12 = 1,462.50 → 91,462.50; (36 − 3)/3 = 11 quarters
    ("MFS", 100_000, {}, 91_462.50, 11, 9_147.23),
    # AMY: 90,000 × 15% × 3/12 = 3,375 → 93,375; 11 quarters
    ("AMY", 100_000, {}, 93_375.00, 11, 10_515.45),
    # UNY via Cooperative Bank at 13%: 270,000 × 13% × 3/12 = 8,775 → 278,775; (60 − 3)/3 = 19 quarters
    ("UNY", 300_000, {"partner_type": "Cooperative Bank"}, 278_775.00, 19, 19_895.62),
    # UNY via Small Finance Bank at 15%: 270,000 × 15% × 3/12 = 10,125 → 280,125
    ("UNY", 300_000, {"partner_type": "Small Finance Bank"}, 280_125.00, 19, 20_877.88),
    # Term Loan, general activity: 900,000 × 8% × 6/12 = 36,000 → 936,000; (84 − 6)/3 = 26 quarters
    ("TERM_LOAN", 1_000_000, {"context": LoanContext(activity_category="trade_retail")}, 936_000.00, 26, 46_518.48),
    # Term Loan, plantation: 12-month moratorium → 900,000 × 8% = 72,000 → 972,000; (84 − 12)/3 = 24 quarters
    ("TERM_LOAN", 1_000_000, {"context": LoanContext(activity_category="plantation")}, 972_000.00, 24, 51_390.71),
    # Term Loan at the ₹50L ceiling: loan 45L; 4,500,000 × 8% × 6/12 = 180,000 → 4,680,000
    ("TERM_LOAN", 5_000_000, {}, 4_680_000.00, 26, 232_592.40),
    # ELS, 4-year course, repayment not started: moratorium 48 + 12 = 60 months;
    # 900,000 × 6.5% × 60/12 = 292,500 → 1,192,500; 12 years = 48 quarters after the moratorium
    ("ELS", 1_000_000, {"context": LoanContext(course_duration_months=48)}, 1_192_500.00, 48, 35_971.29),
    # ELS, repayment started: 6-month moratorium → 900,000 × 6.5% × 6/12 = 29,250 → 929,250; 10 years = 40 quarters
    ("ELS", 1_000_000, {"context": LoanContext(repayment_started=True)}, 929_250.00, 40, 31_775.45),
])
def test_hand_verified_instalments(scheme, code, cost, kwargs, principal, n, instalment):
    r = calculate_loan(scheme(code), cost, **kwargs)
    assert r.principal_after_moratorium == principal
    assert r.number_of_instalments == n
    assert r.instalment_amount == instalment
    assert r.repayment_frequency == "quarterly"
    assert r.monthly_equivalent == round(instalment / 3, 2)


@pytest.mark.parametrize("frequency, n, instalment, max_tenure", [
    ("monthly", 33, 3_034.16, 36),
    ("quarterly", 11, 9_147.23, 36),
    # 33 months after the moratorium hold 5 whole half-years (30 months) → max tenure 3 + 30 = 33
    ("half_yearly", 5, 20_114.03, 33),
])
def test_repayment_frequencies(scheme, frequency, n, instalment, max_tenure):
    r = calculate_loan(scheme("MFS"), 100_000, repayment_frequency=frequency)
    assert (r.number_of_instalments, r.instalment_amount, r.max_tenure_months) == (n, instalment, max_tenure)
    assert r.period_months == {"monthly": 1, "quarterly": 3, "half_yearly": 6}[frequency]


# ── Schedule integrity ───────────────────────────────────────────────────────

@pytest.mark.parametrize("code, kwargs", [
    ("MFS", {}), ("TERM_LOAN", {"repayment_frequency": "monthly"}),
    ("ELS", {"context": LoanContext(course_duration_months=36)}), ("UNY", {"repayment_frequency": "half_yearly"}),
])
def test_schedule_reconciles_exactly(scheme, code, kwargs):
    r = calculate_loan(scheme(code), 120_000, **kwargs)
    rows = r.schedule
    cents = lambda xs: sum(round(x * 100) for x in xs)  # compare in paise to avoid float drift

    assert len(rows) == r.number_of_instalments
    assert rows[0].opening_balance == r.principal_after_moratorium
    assert rows[-1].closing_balance == 0
    assert cents(row.principal for row in rows) == round(r.principal_after_moratorium * 100)
    assert cents(row.instalment for row in rows) == round(r.total_payment * 100)  # capitalized: no separate interest
    for row in rows:
        assert round(row.instalment * 100) == round(row.principal * 100) + round(row.interest * 100)
    for prev, row in zip(rows, rows[1:]):
        assert row.opening_balance == prev.closing_balance
        assert row.due_month - prev.due_month == r.period_months
    assert rows[0].due_month == r.moratorium_months + r.period_months
    assert rows[-1].due_month == r.tenure_months
    # All but the final (rounding-absorbing) instalment are equal.
    assert {row.instalment for row in rows[:-1]} == {r.instalment_amount}
    assert abs(rows[-1].instalment - r.instalment_amount) < 1


def test_totals(scheme):
    r = calculate_loan(scheme("MFS"), 100_000)
    assert r.loan_amount == 90_000 and r.applicant_contribution == 10_000
    assert r.total_interest == pytest.approx(r.total_payment - 90_000, abs=0.005)
    assert r.total_cost == pytest.approx(r.total_payment + 10_000, abs=0.005)
    assert r.moratorium_interest == 1_462.50


def test_serviced_moratorium_interest(scheme):
    capitalized = calculate_loan(scheme("MFS"), 100_000)
    serviced = calculate_loan(scheme("MFS"), 100_000, moratorium_interest="serviced")
    assert serviced.principal_after_moratorium == 90_000
    assert serviced.moratorium_interest == 1_462.50
    instalments = sum(row.instalment for row in serviced.schedule)
    assert serviced.total_payment == pytest.approx(instalments + 1_462.50, abs=0.005)
    assert serviced.instalment_amount < capitalized.instalment_amount
    assert serviced.total_interest < capitalized.total_interest  # no interest charged on interest


# ── Guideline rules ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("activity, months", [
    ("plantation", 12), ("construction", 12), ("manufacturing", 6), ("transport", 6), (None, 6),
])
def test_term_loan_moratorium_by_activity(scheme, activity, months):
    r = calculate_loan(scheme("TERM_LOAN"), 1_000_000, context=LoanContext(activity_category=activity))
    assert r.moratorium_months == months
    assert r.tenure_months == 84  # the 7 years include the moratorium


def test_els_moratorium_and_tenure_depend_on_repayment_status(scheme):
    not_started = calculate_loan(scheme("ELS"), 500_000, context=LoanContext(course_duration_months=36))
    assert not_started.moratorium_months == 48  # course 36 + 12
    assert not_started.max_tenure_months == 48 + 144  # 12 years after the moratorium
    assert "course period plus 1 year" in not_started.moratorium_basis

    started = calculate_loan(scheme("ELS"), 500_000, context=LoanContext(repayment_started=True))
    assert started.moratorium_months == 6
    assert started.max_tenure_months == 6 + 120  # 10 years
    assert not started.tenure_includes_moratorium

    with pytest.raises(ValueError, match="course_duration_months is required"):
        calculate_loan(scheme("ELS"), 500_000)  # not started, duration unknown


@pytest.mark.parametrize("partner_type, rate", [
    ("Cooperative Bank", 13), ("Cooperative Society", 13), ("Small Finance Bank", 15),
])
def test_uny_rate_by_partner_type(scheme, partner_type, rate):
    r = calculate_loan(scheme("UNY"), 300_000, partner_type=partner_type)
    assert (r.interest_rate_pct, r.rate_partner_type) == (rate, partner_type)


def test_uny_without_partner_shows_base_rate_and_explains(scheme):
    r = calculate_loan(scheme("UNY"), 300_000)
    assert r.interest_rate_pct == 13 and r.rate_partner_type is None
    assert "15% via Small Finance Bank" in r.rate_basis
    assert r.rate_options == {"Cooperative Bank": 13, "Cooperative Society": 13, "Small Finance Bank": 15}
    with pytest.raises(ValueError, match="not channelled through NBFC-MFI"):
        calculate_loan(scheme("UNY"), 300_000, partner_type="NBFC-MFI")


def test_single_rate_schemes_ignore_partner_type(scheme):
    assert calculate_loan(scheme("MFS"), 100_000, partner_type="RRB").interest_rate_pct == 6.5


def test_legacy_scheme_without_rules_uses_flat_fields(scheme, db_session):
    tl = scheme("TERM_LOAN")
    tl.moratorium_rules = tl.tenure_rules = None
    r = calculate_loan(tl, 1_000_000, context=LoanContext(activity_category="plantation"))
    assert r.moratorium_months == 6  # moratorium_min_months
    assert r.max_tenure_months == 84


# ── Tenure bounds, loan amount ───────────────────────────────────────────────

@pytest.mark.parametrize("requested, total, adjusted", [
    (None, 36, False),
    (1, 6, True),  # minimum is moratorium + one quarter
    (6, 6, False),
    (20, 18, True),  # 17 repayment months → 5 whole quarters
    (100, 36, True),  # capped at the guideline
])
def test_tenure_is_bounded_and_whole_periods(scheme, requested, total, adjusted):
    r = calculate_loan(scheme("MFS"), 100_000, requested)
    assert r.tenure_months == total
    assert (r.min_tenure_months, r.max_tenure_months) == (6, 36)
    assert r.number_of_instalments == (total - 3) // 3
    assert any("Tenure adjusted" in n for n in r.notes) == adjusted


def test_loan_amount_is_editable_up_to_the_maximum(scheme):
    r = calculate_loan(scheme("MFS"), 100_000, loan_amount=50_000)
    assert (r.loan_amount, r.max_loan_amount, r.applicant_contribution) == (50_000, 90_000, 50_000)
    assert calculate_loan(scheme("MFS"), 100_000, loan_amount=90_000).loan_amount == 90_000
    with pytest.raises(ValueError, match="exceeds this scheme's maximum"):
        calculate_loan(scheme("MFS"), 100_000, loan_amount=90_000.01)


@pytest.mark.parametrize("code, cost, max_loan", [
    ("MFS", 140_000, 125_000),  # 90% = 1,26,000, capped at the ₹1.25L maximum
    ("UNY", 140_001, 126_000.90),  # 90% of ₹1,40,001
    ("TERM_LOAN", 140_001, 126_000.90),
    ("TERM_LOAN", 5_000_000, 4_500_000),  # 90% of ₹50L = the ₹45L maximum
])
def test_boundary_costs_max_loan(scheme, code, cost, max_loan):
    assert calculate_loan(scheme(code), cost).max_loan_amount == max_loan


# ── API ──────────────────────────────────────────────────────────────────────

def test_calculate_api_uses_selected_partner_rate(client, make_partner):
    sfb = make_partner("AU SFB", partner_type="Small Finance Bank", eligible_scheme_codes=["UNY"])
    coop = make_partner("Coop", partner_type="Cooperative Bank", eligible_scheme_codes=["UNY"])
    sca = make_partner("SCA")  # MFS/TERM_LOAN/ELS only

    body = {"scheme_code": "UNY", "project_cost": 300_000}
    assert client.post("/api/calculate", json={**body, "partner_id": sfb.id}).json()["interest_rate_pct"] == 15
    assert client.post("/api/calculate", json={**body, "partner_id": coop.id}).json()["interest_rate_pct"] == 13
    assert client.post("/api/calculate", json={**body, "partner_id": sca.id}).status_code == 400
    assert client.post("/api/calculate", json={**body, "partner_id": 99999}).status_code == 404


def test_calculate_api_validation(client):
    ok = client.post("/api/calculate", json={
        "scheme_code": "ELS", "project_cost": 800_000, "course_duration_months": 24,
        "repayment_frequency": "monthly", "loan_amount": 500_000,
    })
    assert ok.status_code == 200
    assert (ok.json()["moratorium_months"], ok.json()["loan_amount"]) == (36, 500_000)

    assert client.post("/api/calculate", json={"scheme_code": "ELS", "project_cost": 800_000}).status_code == 400
    assert client.post("/api/calculate", json={"scheme_code": "MFS", "project_cost": 100_000,
                                               "repayment_frequency": "weekly"}).status_code == 422
    assert client.post("/api/calculate", json={"scheme_code": "MFS", "project_cost": 100_000,
                                               "loan_amount": 95_000}).status_code == 400
