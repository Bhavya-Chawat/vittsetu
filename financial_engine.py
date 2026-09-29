"""Loan calculator, driven by each scheme's guideline rules stored as data.

Pure, deterministic arithmetic — no LLM. Money is computed in Decimal and
rounded half-up to the paisa, so the amortization schedule reconciles exactly
(instalments sum to principal + interest, closing balance is exactly 0).

Scheme rule formats (JSON columns on models.Scheme, values in
scripts/seed_schemes.py). Conditions in "if" test the LoanContext: a list
means "one of", a scalar means "equals". The first matching rule wins.

  moratorium_rules = {
      "default_months": 6, "default_basis": "...",
      "rules": [
          {"if": {"activity_category": ["plantation", "construction"]}, "months": 12, "basis": "..."},
          {"if": {"repayment_started": false}, "course_duration_plus_months": 12, "basis": "..."},
      ],
  }
  tenure_rules = {
      "includes_moratorium": true,  # guideline tenure counts from disbursement
      "default_months": 84, "default_basis": "...",
      "rules": [{"if": {"repayment_started": true}, "months": 120, "basis": "..."}],
  }
  rates_by_partner_type = {"Cooperative Bank": 13, "Small Finance Bank": 15}

Interest conventions (NSFDC doesn't publish these details, so they are
stated in every result's notes rather than hidden):
  - Interest accrues during the moratorium as simple interest on the amount
    disbursed. By default it is capitalized (added to the principal repaid
    afterwards); "serviced" means it is paid as it falls due instead.
  - Instalments are equal, on a reducing balance, at the scheme's annual rate
    divided by the number of instalments per year.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from models import Scheme
from schemas import CalculateResponse, ScheduleRow

FREQUENCY_MONTHS = {"monthly": 1, "quarterly": 3, "half_yearly": 6}
FREQUENCY_LABELS = {"monthly": "monthly", "quarterly": "quarterly", "half_yearly": "half-yearly"}
PAISA = Decimal("0.01")


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(PAISA, rounding=ROUND_HALF_UP)


def _inr(value) -> str:
    return f"₹{float(value):,.0f}"


def _pct(value: float) -> str:
    return f"{value:g}%"


@dataclass(frozen=True)
class LoanContext:
    """Applicant facts that guideline rules can depend on."""
    activity_category: str | None = None
    repayment_started: bool = False
    course_duration_months: int | None = None


# ── Rule resolution ──────────────────────────────────────────────────────────

def _applies(condition: dict, ctx: LoanContext) -> bool:
    for key, expected in condition.items():
        actual = getattr(ctx, key)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


def resolve_moratorium(scheme: Scheme, ctx: LoanContext) -> tuple[int | None, str]:
    """(months, basis). Months is None when the rule needs an input that's
    missing — e.g. ELS before repayment needs the course duration."""
    rules = scheme.moratorium_rules
    if not rules:
        months = scheme.moratorium_min_months or 0
        return months, f"{months}-month moratorium"
    for rule in rules.get("rules", []):
        if _applies(rule.get("if", {}), ctx):
            if "course_duration_plus_months" in rule:
                if ctx.course_duration_months is None:
                    return None, rule["basis"]
                return ctx.course_duration_months + rule["course_duration_plus_months"], rule["basis"]
            return rule["months"], rule["basis"]
    if "default_months" not in rules:
        raise ValueError(f"{scheme.code}: no moratorium rule matches {ctx}")
    return rules["default_months"], rules["default_basis"]


def resolve_tenure(scheme: Scheme, ctx: LoanContext) -> tuple[int, bool, str]:
    """(guideline months, whether they include the moratorium, basis)."""
    rules = scheme.tenure_rules
    if not rules:
        return scheme.repayment_tenure_max_months, True, (
            f"up to {scheme.repayment_tenure_max_months} months including moratorium"
        )
    includes = rules.get("includes_moratorium", True)
    for rule in rules.get("rules", []):
        if _applies(rule.get("if", {}), ctx):
            return rule["months"], includes, rule["basis"]
    if "default_months" not in rules:
        raise ValueError(f"{scheme.code}: no tenure rule matches {ctx}")
    return rules["default_months"], includes, rules["default_basis"]


def rate_options(scheme: Scheme) -> dict[str, float]:
    """Beneficiary interest rate for each partner type that channels the scheme."""
    by_type = scheme.rates_by_partner_type or {}
    return {pt: by_type.get(pt, scheme.interest_rate_to_beneficiary_pct) for pt in scheme.eligible_partner_types or []}


def resolve_rate(scheme: Scheme, partner_type: str | None) -> tuple[float, str | None, str]:
    """(annual rate %, partner type it applies to, basis)."""
    options = rate_options(scheme)
    distinct = sorted(set(options.values()))
    if partner_type:
        if options and partner_type not in options:
            raise ValueError(
                f"{scheme.name} is not channelled through {partner_type} partners "
                f"(channels: {', '.join(options)})."
            )
        rate = options.get(partner_type, scheme.interest_rate_to_beneficiary_pct)
        return rate, partner_type, f"{_pct(rate)} p.a. via {partner_type}"
    if len(distinct) > 1:
        per_rate = "; ".join(
            f"{_pct(r)} via {', '.join(pt for pt, v in options.items() if v == r)}" for r in distinct
        )
        base = scheme.interest_rate_to_beneficiary_pct
        return base, None, f"{_pct(base)} p.a. shown — the rate depends on your partner ({per_rate})."
    rate = distinct[0] if distinct else scheme.interest_rate_to_beneficiary_pct
    return rate, None, f"{_pct(rate)} p.a."


def max_eligible_loan(scheme: Scheme, project_cost: float) -> float:
    """The scheme's cap: its financing % of the cost, up to its maximum loan."""
    if project_cost <= 0:
        raise ValueError("project_cost must be greater than zero")
    return float(min(_money(project_cost * scheme.max_financing_pct / 100), _money(scheme.max_loan_amount)))


# ── Amortization ─────────────────────────────────────────────────────────────

def instalment_amount(principal: Decimal, annual_rate_pct: float, periods_per_year: int, n: int) -> Decimal:
    """Equal instalment on a reducing balance: P·i·(1+i)^n / ((1+i)^n − 1)."""
    i = Decimal(str(annual_rate_pct)) / 100 / periods_per_year
    if i == 0:
        return _money(principal / n)
    factor = (1 + i) ** n
    return _money(principal * i * factor / (factor - 1))


def amortize(
    principal: Decimal, annual_rate_pct: float, period_months: int, n: int, first_due_month: int,
) -> tuple[Decimal, list[ScheduleRow]]:
    """Schedule of n equal instalments; the last absorbs rounding so it closes at exactly 0."""
    periods_per_year = 12 // period_months
    i = Decimal(str(annual_rate_pct)) / 100 / periods_per_year
    emi = instalment_amount(principal, annual_rate_pct, periods_per_year, n)
    balance = principal
    rows = []
    for k in range(1, n + 1):
        interest = _money(balance * i)
        principal_part = balance if k == n else min(emi - interest, balance)
        payment = principal_part + interest
        rows.append(ScheduleRow(
            period=k,
            due_month=first_due_month + (k - 1) * period_months,
            opening_balance=float(balance),
            instalment=float(payment),
            interest=float(interest),
            principal=float(principal_part),
            closing_balance=float(balance - principal_part),
        ))
        balance -= principal_part
    return emi, rows


# ── Calculator ───────────────────────────────────────────────────────────────

def calculate_loan(
    scheme: Scheme,
    project_cost: float,
    tenure_months: int | None = None,
    *,
    loan_amount: float | None = None,
    repayment_frequency: str = "quarterly",
    partner_type: str | None = None,
    context: LoanContext = LoanContext(),
    moratorium_interest: str = "capitalized",
) -> CalculateResponse:
    """Full repayment picture for one scheme. tenure_months is the total period
    from disbursement (moratorium + repayment); omit it for the guideline maximum."""
    if repayment_frequency not in FREQUENCY_MONTHS:
        raise ValueError(f"repayment_frequency must be one of {', '.join(FREQUENCY_MONTHS)}")
    if moratorium_interest not in ("capitalized", "serviced"):
        raise ValueError("moratorium_interest must be 'capitalized' or 'serviced'")

    max_loan = max_eligible_loan(scheme, project_cost)
    loan = max_loan if loan_amount is None else float(_money(loan_amount))
    if loan <= 0:
        raise ValueError("loan_amount must be greater than zero")
    if loan > max_loan:
        raise ValueError(
            f"loan_amount {_inr(loan)} exceeds this scheme's maximum of {_inr(max_loan)} for a project of "
            f"{_inr(project_cost)} ({scheme.max_financing_pct:g}% of cost, capped at {_inr(scheme.max_loan_amount)})."
        )
    contribution = float(_money(project_cost) - _money(loan))

    rate, rate_partner_type, rate_basis = resolve_rate(scheme, partner_type)

    moratorium, moratorium_basis = resolve_moratorium(scheme, context)
    if moratorium is None:
        raise ValueError(
            "course_duration_months is required to work out the moratorium "
            f"({moratorium_basis})."
        )

    guideline_months, includes_moratorium, tenure_basis = resolve_tenure(scheme, context)
    period = FREQUENCY_MONTHS[repayment_frequency]
    max_total = guideline_months if includes_moratorium else moratorium + guideline_months
    min_total = moratorium + period
    if max_total < min_total:
        raise ValueError("The moratorium leaves no time for repayment within this scheme's tenure.")
    # Largest total that leaves a whole number of instalments.
    max_total = moratorium + (max_total - moratorium) // period * period

    notes: list[str] = []
    requested = max_total if tenure_months is None else tenure_months
    clamped = min(max(requested, min_total), max_total)
    total = moratorium + (clamped - moratorium) // period * period
    if tenure_months is not None and total != tenure_months:
        notes.append(
            f"Tenure adjusted from {tenure_months} to {total} months to fit the "
            f"{moratorium}-month moratorium and whole {FREQUENCY_LABELS[repayment_frequency]} instalments "
            f"(allowed: {min_total}–{max_total} months)."
        )
    repayment_months = total - moratorium
    n = repayment_months // period

    disbursed = _money(loan)
    accrued = _money(disbursed * Decimal(str(rate)) / 100 * moratorium / 12)
    principal = disbursed + accrued if moratorium_interest == "capitalized" else disbursed

    emi, schedule = amortize(principal, rate, period, n, first_due_month=moratorium + period)
    instalments_total = sum(Decimal(str(r.instalment)) for r in schedule)
    total_payment = instalments_total + (accrued if moratorium_interest == "serviced" else 0)
    total_interest = total_payment - disbursed

    notes += [
        f"Loan capped at {scheme.max_financing_pct:g}% of project cost or {_inr(scheme.max_loan_amount)}, "
        f"whichever is lower — up to {_inr(max_loan)} here.",
        f"You contribute the remaining {_inr(contribution)} from your own resources.",
        f"Moratorium: {moratorium} month(s) — {moratorium_basis}.",
        f"Interest during the moratorium ({_inr(accrued)}, simple interest at {_pct(rate)} p.a.) is "
        + ("added to the amount you repay (capitalized)." if moratorium_interest == "capitalized"
           else "paid as it falls due during the moratorium."),
        f"Repayment: {n} {FREQUENCY_LABELS[repayment_frequency]} instalments of {_inr(emi)} "
        f"(about {_inr(emi / period)} a month). NSFDC's Channel Partners usually collect quarterly — "
        "confirm the exact schedule with your partner.",
        f"Tenure: {tenure_basis}.",
    ]
    if not includes_moratorium:
        notes.append("For this scheme the repayment period is counted after the moratorium ends.")
    if rate_partner_type is None and len(set(rate_options(scheme).values())) > 1:
        notes.append(rate_basis)
    if scheme.moratorium_notes:
        notes.append(scheme.moratorium_notes)

    return CalculateResponse(
        scheme_code=scheme.code,
        project_cost=project_cost,
        financing_pct=scheme.max_financing_pct,
        max_loan_amount=max_loan,
        loan_amount=loan,
        applicant_contribution=contribution,
        interest_rate_pct=rate,
        rate_partner_type=rate_partner_type,
        rate_basis=rate_basis,
        rate_options=rate_options(scheme),
        repayment_frequency=repayment_frequency,
        period_months=period,
        number_of_instalments=n,
        moratorium_months=moratorium,
        moratorium_basis=moratorium_basis,
        moratorium_interest=float(accrued),
        moratorium_interest_treatment=moratorium_interest,
        principal_after_moratorium=float(principal),
        tenure_months=total,
        repayment_months=repayment_months,
        min_tenure_months=min_total,
        max_tenure_months=max_total,
        tenure_basis=tenure_basis,
        tenure_includes_moratorium=includes_moratorium,
        instalment_amount=float(emi),
        monthly_equivalent=float(_money(emi / period)),
        total_payment=float(total_payment),
        total_interest=float(total_interest),
        total_cost=float(total_payment + _money(contribution)),
        schedule=schedule,
        notes=notes,
    )
