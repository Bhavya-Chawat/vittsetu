"""EMI / amortization calculator, bounded by a scheme's own stored parameters.

Pure arithmetic, no LLM involvement. NSFDC schemes are officially repaid in
quarterly (occasionally half-yearly) instalments, not monthly — this module
computes the commonly-understood monthly-reducing-balance EMI figure the PS
asks for as an illustrative planning tool, and says so explicitly in `notes`,
rather than silently implying it matches the Channel Partner's exact billing
cycle.
"""

from models import Scheme
from schemas import CalculateResponse


def calculate_loan(scheme: Scheme, project_cost: float, tenure_months: int | None = None) -> CalculateResponse:
    if project_cost <= 0:
        raise ValueError("project_cost must be greater than zero")

    financing_pct = scheme.max_financing_pct
    loan_amount = min(project_cost * financing_pct / 100, scheme.max_loan_amount)
    applicant_contribution = project_cost - loan_amount
    interest_rate = scheme.interest_rate_to_beneficiary_pct

    tenure = tenure_months or scheme.repayment_tenure_max_months
    tenure = min(max(tenure, 1), scheme.repayment_tenure_max_months)

    moratorium = scheme.moratorium_min_months or 0
    repayment_months = max(tenure - moratorium, 1)

    monthly_rate = interest_rate / 100 / 12
    n = repayment_months
    if monthly_rate == 0:
        emi = loan_amount / n
    else:
        factor = (1 + monthly_rate) ** n
        emi = loan_amount * monthly_rate * factor / (factor - 1)

    total_payment = emi * n
    total_interest = total_payment - loan_amount

    notes = [
        f"Loan capped at {financing_pct:.0f}% of project cost or ₹{scheme.max_loan_amount:,.0f}, whichever is lower.",
        f"You contribute the remaining ₹{applicant_contribution:,.0f} ({100 - financing_pct:.0f}%) from your own resources.",
        f"EMI holiday (moratorium) of {moratorium} month(s) before instalments begin.",
        "NSFDC/Channel Partners actually collect repayments quarterly (see scheme details), not monthly — "
        "this monthly EMI figure is a standard reducing-balance planning estimate, not your exact billing schedule.",
    ]
    if scheme.moratorium_notes:
        notes.append(scheme.moratorium_notes)

    return CalculateResponse(
        scheme_code=scheme.code,
        project_cost=project_cost,
        financing_pct=financing_pct,
        loan_amount=round(loan_amount, 2),
        applicant_contribution=round(applicant_contribution, 2),
        interest_rate_pct=interest_rate,
        tenure_months=tenure,
        moratorium_months=moratorium,
        monthly_emi=round(emi, 2),
        total_interest=round(total_interest, 2),
        total_payment=round(total_payment, 2),
        notes=notes,
    )
