"""Deterministic eligibility + scheme recommendation rules.

No LLM involvement anywhere in this module — every eligibility/matching
decision must be traceable to a scheme's stored, source-cited fields.
"""

import re

from sqlalchemy.orm import Session
from models import Scheme
from schemas import ApplicantProfile, BusinessRequirement, EducationRequirement

# NSFDC's general target-group ceiling, stated identically across its schemes
# (nsfdc.nic.in/scheme, accessed during planning). Scheme-specific sub-limits,
# if any exist in deeper guideline PDFs, are not yet cross-verified — see plan.
GENERAL_INCOME_LIMIT = 500_000


def check_eligibility(profile: ApplicantProfile) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    eligible = True

    if not profile.is_sc_category:
        eligible = False
        reasons.append(
            "NSFDC schemes are for persons belonging to the Scheduled Caste (SC) "
            "category. Your Channel Partner will verify your SC certificate at "
            "the application stage."
        )
    else:
        reasons.append("SC category self-declaration recorded.")

    if profile.annual_family_income > GENERAL_INCOME_LIMIT:
        eligible = False
        reasons.append(
            f"Annual family income of ₹{profile.annual_family_income:,.0f} exceeds "
            f"NSFDC's ₹{GENERAL_INCOME_LIMIT:,.0f} eligibility ceiling."
        )
    else:
        reasons.append(
            f"Annual family income of ₹{profile.annual_family_income:,.0f} is within "
            f"the ₹{GENERAL_INCOME_LIMIT:,.0f} ceiling."
        )

    return eligible, reasons


def _business_candidates(db: Session) -> list[Scheme]:
    return db.query(Scheme).filter(Scheme.scheme_type != "education_loan").all()


def _education_candidates(db: Session) -> list[Scheme]:
    return db.query(Scheme).filter(Scheme.scheme_type == "education_loan").all()


def recommend_business(
    db: Session, requirement: BusinessRequirement
) -> tuple[list[tuple[Scheme, list[str]]], list[tuple[Scheme, list[str]]]]:
    cost = requirement.estimated_cost
    matched: list[tuple[Scheme, list[str]]] = []
    rejected: list[tuple[Scheme, list[str]]] = []

    for scheme in _business_candidates(db):
        reasons: list[str] = []
        fits_min = scheme.min_project_cost is None or cost >= scheme.min_project_cost
        fits_max = cost <= scheme.max_project_cost

        if fits_min and fits_max:
            reasons.append(
                f"Project cost ₹{cost:,.0f} fits this scheme's band "
                f"(up to ₹{scheme.max_project_cost:,.0f})."
            )
            reasons.append(
                f"Financing up to {scheme.max_financing_pct:.0f}% "
                f"(max ₹{scheme.max_loan_amount:,.0f}) at "
                f"{scheme.interest_rate_to_beneficiary_pct}% p.a. via "
                f"{', '.join(scheme.eligible_partner_types)}."
            )
            matched.append((scheme, reasons))
        else:
            if not fits_min:
                reasons.append(
                    f"Project cost ₹{cost:,.0f} is below this scheme's minimum "
                    f"₹{scheme.min_project_cost:,.0f} threshold."
                )
            if not fits_max:
                reasons.append(
                    f"Project cost ₹{cost:,.0f} exceeds this scheme's maximum "
                    f"₹{scheme.max_project_cost:,.0f} limit."
                )
            rejected.append((scheme, reasons))

    matched.sort(key=lambda pair: pair[0].interest_rate_to_beneficiary_pct)
    return matched, rejected


def recommend_education(
    db: Session, requirement: EducationRequirement
) -> tuple[list[tuple[Scheme, list[str]]], list[tuple[Scheme, list[str]]]]:
    matched: list[tuple[Scheme, list[str]]] = []
    rejected: list[tuple[Scheme, list[str]]] = []

    for scheme in _education_candidates(db):
        reasons: list[str] = []
        implied_loan = min(requirement.course_fee * (scheme.max_financing_pct / 100), scheme.max_loan_amount)

        if implied_loan <= 0:
            rejected.append((scheme, ["Course fee must be greater than zero."]))
            continue

        reasons.append(
            f"Eligible for up to ₹{implied_loan:,.0f} "
            f"({scheme.max_financing_pct:.0f}% of course fee, capped at ₹{scheme.max_loan_amount:,.0f}) "
            f"at {scheme.interest_rate_to_beneficiary_pct}% p.a."
        )

        courses = (scheme.education_criteria or {}).get("courses", [])
        course_lower = requirement.course_name.lower()
        # Tokens of length >=3 avoid false matches from meaningless fragments
        # like the "b"/"m" left over from splitting "B.Tech"/"M.Arch" etc.
        course_tokens = {t for t in re.findall(r"[a-z]+", course_lower) if len(t) >= 3}
        known_match = any(
            c.lower() in course_lower
            or course_lower in c.lower()
            or course_tokens & {t for t in re.findall(r"[a-z]+", c.lower()) if len(t) >= 3}
            for c in courses
        )
        if known_match:
            reasons.append(f"'{requirement.course_name}' matches NSFDC's recognized course list.")
        else:
            reasons.append(
                f"Course name not automatically matched to NSFDC's recognized list — "
                "ask your Channel Partner to confirm it qualifies as a recognized "
                "professional/technical course before applying."
            )

        matched.append((scheme, reasons))

    return matched, rejected
