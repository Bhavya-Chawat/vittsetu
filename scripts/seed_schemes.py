"""Seed the schemes table with NSFDC's officially published loan schemes.

Every figure below was read directly off NSFDC's live official site during
the transformation-planning session on 2026-09-18 and transcribed verbatim —
none of it is invented or estimated. Sources:

  - Scheme terms:        http://nsfdc.nic.in/scheme
  - Document checklist:  http://nsfdc.nic.in/how-to-apply-2
  - Channel partners:    http://nsfdc.nic.in/our-channel-partners

If NSFDC revises rates/limits, update SOURCE_CAPTURED_DATE and the affected
fields here (or via the admin console once built) — never edit silently.

Guideline rules (moratorium, tenure, per-partner-type rates) are stored as
data in moratorium_rules / tenure_rules / rates_by_partner_type and
evaluated by financial_engine.py — see its docstring for the format.

Usage:
  python scripts/seed_schemes.py            # add missing schemes; fill empty fields on existing ones
  python scripts/seed_schemes.py --refresh  # also overwrite the guideline-rule fields below from this file
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import SessionLocal, init_db
from models import Scheme

SOURCE_URL = "http://nsfdc.nic.in/scheme"
DOC_SOURCE_URL = "http://nsfdc.nic.in/how-to-apply-2"
CAPTURED_DATE = "2026-09-18"

# Verified verbatim from http://nsfdc.nic.in/how-to-apply-2 — the official
# page explicitly defers the FULL checklist to each Channel Partner, so we
# only list what NSFDC itself states, not an assumed complete list.
COMMON_REQUIRED_DOCUMENTS = [
    "Caste Certificate (Scheduled Caste)",
    "Income Certificate / proof of annual family income",
    "KYC documents (Aadhaar, address proof, photograph)",
    "Any additional documents required by your Channel Partner (SCA/CA) — confirm exact checklist with them or on the PM-SURAJ portal",
]

ELS_COURSES = [
    "Engineering (Diploma / B.Tech / B.E / M.Tech / M.E)",
    "Architecture (B.Arch / M.Arch)",
    "Medical (MBBS / MD / MS)",
    "Biotechnology / Microbiology / Clinical Technology",
    "Pharmacy (B.Pharma / M.Pharma)",
    "Dental (BDS / MDS)",
    "Physiotherapy (B.Sc / M.Sc)",
    "Pathology (B.Sc / M.Sc)",
    "Nursing (B.Sc / M.Sc)",
    "Information Technology (BCA / MCA)",
    "Management (BBA / MBA)",
    "Hotel Management & Catering Technology",
    "Law (LLB / LLM)",
    "Education (CT / NTT / B.Ed / M.Ed)",
    "Physical Education (C.PEd / B.PEd / M.PEd)",
    "Journalism & Mass Communication",
    "Geriatric Care",
    "Midwifery",
    "Laboratory Technician",
    "Chartered Accountancy (CA)",
    "Cost Accountancy (ICWA)",
    "Company Secretaryship (CS)",
    "Actuarial Sciences",
    "AMIE / Institute of Electronics & Telecommunication",
    "Doctoral Studies (M.Phil / PhD)",
]

SCHEMES = [
    dict(
        code="MFS",
        name="Micro Finance Scheme (MFS)",
        scheme_type="micro_finance",
        income_limit_annual=500_000,
        min_project_cost=None,
        max_project_cost=140_000,
        max_financing_pct=90,
        max_loan_amount=125_000,
        interest_rate_to_partner_pct=2.5,
        interest_rate_to_beneficiary_pct=6.5,
        moratorium_min_months=3,
        moratorium_max_months=3,
        moratorium_notes=None,
        repayment_tenure_max_months=36,
        moratorium_rules={
            "default_months": 3,
            "default_basis": "3-month moratorium, within the 3-year repayment period",
        },
        tenure_rules={
            "includes_moratorium": True,
            "default_months": 36,
            "default_basis": "repaid in quarterly instalments within 3 years of disbursement, including the moratorium",
        },
        eligible_activities=["Small/micro business activities"],
        education_criteria=None,
        # "SCAs/CAs" per the scheme page; Banks are CAs per how-to-apply-2 (see ingest_partners.py).
        eligible_partner_types=["SCA", "PSB", "RRB"],
    ),
    dict(
        code="TERM_LOAN",
        name="Term Loan",
        scheme_type="term_loan",
        income_limit_annual=500_000,
        min_project_cost=140_000.01,
        max_project_cost=5_000_000,
        max_financing_pct=90,
        max_loan_amount=4_500_000,
        interest_rate_to_partner_pct=4,
        interest_rate_to_beneficiary_pct=8,
        moratorium_min_months=6,
        moratorium_max_months=12,
        moratorium_notes="6-month moratorium in general; 12 months for plantation and construction activities.",
        repayment_tenure_max_months=84,
        moratorium_rules={
            "default_months": 6,
            "default_basis": "6-month moratorium in general",
            "rules": [{
                "if": {"activity_category": ["plantation", "construction"]},
                "months": 12,
                "basis": "12-month moratorium for plantation and construction activities",
            }],
        },
        tenure_rules={
            "includes_moratorium": True,
            "default_months": 84,
            "default_basis": "repaid in quarterly instalments within 7 years, including the moratorium",
        },
        eligible_activities=["Larger business/project activities", "Plantation", "Construction"],
        education_criteria=None,
        eligible_partner_types=["SCA", "PSB", "RRB"],
    ),
    dict(
        code="AMY",
        name="Aajeevika Micro-Finance Yojana (AMY)",
        scheme_type="nbfc_micro_finance",
        income_limit_annual=500_000,
        min_project_cost=None,
        max_project_cost=140_000,
        max_financing_pct=90,
        max_loan_amount=125_000,
        interest_rate_to_partner_pct=5,
        interest_rate_to_beneficiary_pct=15,
        moratorium_min_months=3,
        moratorium_max_months=3,
        moratorium_notes=None,
        repayment_tenure_max_months=36,
        moratorium_rules={
            "default_months": 3,
            "default_basis": "3-month moratorium, within the 3-year repayment period",
        },
        tenure_rules={
            "includes_moratorium": True,
            "default_months": 36,
            "default_basis": "repaid in quarterly instalments within 3 years of each disbursement, including the moratorium",
        },
        eligible_activities=["Small/micro business activities via NBFC-MFIs"],
        education_criteria=None,
        eligible_partner_types=["NBFC-MFI"],
    ),
    dict(
        code="UNY",
        name="Udyam Nidhi Yojana (UNY)",
        scheme_type="udyam_nidhi",
        income_limit_annual=500_000,
        min_project_cost=None,
        max_project_cost=500_000,
        max_financing_pct=90,
        max_loan_amount=450_000,
        interest_rate_to_partner_pct=5,
        interest_rate_to_beneficiary_pct=13,  # via Cooperative Banks/Societies; 15% via Small Finance Banks (see notes)
        moratorium_min_months=3,
        moratorium_max_months=3,
        moratorium_notes="13% p.a. via Cooperative Banks/Societies; 15% p.a. via Small Finance Banks — actual rate depends on which partner processes your loan.",
        repayment_tenure_max_months=60,
        moratorium_rules={
            "default_months": 3,
            "default_basis": "3-month moratorium, within the 5-year repayment period",
        },
        tenure_rules={
            "includes_moratorium": True,
            "default_months": 60,
            "default_basis": "repaid in quarterly or half-yearly instalments within 5 years, including the moratorium",
        },
        rates_by_partner_type={"Cooperative Bank": 13, "Cooperative Society": 13, "Small Finance Bank": 15},
        eligible_activities=["Small/micro business activities via Cooperative Banks/Societies or Small Finance Banks"],
        education_criteria=None,
        eligible_partner_types=["Cooperative Bank", "Cooperative Society", "Small Finance Bank"],
    ),
    dict(
        code="ELS",
        name="Educational Loan Scheme (ELS)",
        scheme_type="education_loan",
        income_limit_annual=500_000,
        min_project_cost=None,
        max_project_cost=4_000_000,
        max_financing_pct=90,
        max_loan_amount=4_000_000,
        interest_rate_to_partner_pct=2.5,
        interest_rate_to_beneficiary_pct=6.5,
        moratorium_min_months=6,
        moratorium_max_months=None,
        moratorium_notes=(
            "Course period + 1 year if repayment has not started; "
            "up to 6 months if loan disbursed and repayment already started."
        ),
        repayment_tenure_max_months=144,  # 12 years (not started) — widest case; 10 years if repayment started
        moratorium_rules={
            "rules": [
                {
                    "if": {"repayment_started": True},
                    "months": 6,  # "up to 6 months" — the maximum is used
                    "basis": "up to 6 months, where the loan is disbursed and repayment has started",
                },
                {
                    "if": {"repayment_started": False},
                    "course_duration_plus_months": 12,
                    "basis": "course period plus 1 year, where repayment has not started",
                },
            ],
        },
        tenure_rules={
            # The scheme page lists the repayment period and the moratorium as
            # separate columns and (unlike the other schemes) doesn't say
            # "including the moratorium", so it's read as the period after it.
            "includes_moratorium": False,
            "rules": [
                {"if": {"repayment_started": True}, "months": 120,
                 "basis": "up to 10 years, where the loan is disbursed and repayment has started"},
                {"if": {"repayment_started": False}, "months": 144,
                 "basis": "up to 12 years, where repayment has not started"},
            ],
        },
        eligible_activities=[],
        education_criteria={"courses": ELS_COURSES},
        eligible_partner_types=["SCA", "PSB", "RRB"],
    ),
]


# Fields --refresh overwrites on existing rows. Deliberately excludes the
# figures admins can edit through the console (limits, rates, tenure caps).
RULE_FIELDS = [
    "moratorium_rules", "tenure_rules", "rates_by_partner_type",
    "eligible_partner_types", "education_criteria", "moratorium_notes",
]


def seed(refresh: bool = False):
    init_db()
    db = SessionLocal()
    try:
        for data in SCHEMES:
            existing = db.query(Scheme).filter_by(code=data["code"]).first()
            if existing:
                changed = []
                for field, value in data.items():
                    current = getattr(existing, field)
                    if (current is None and value is not None) or (refresh and field in RULE_FIELDS and current != value):
                        setattr(existing, field, value)
                        changed.append(field)
                print(f"[update] {data['code']}: {', '.join(changed)}" if changed else f"[skip] {data['code']} up to date")
                continue
            scheme = Scheme(
                required_documents=COMMON_REQUIRED_DOCUMENTS,
                source_url=SOURCE_URL,
                source_captured_date=CAPTURED_DATE,
                last_verified_date=CAPTURED_DATE,
                **data,
            )
            db.add(scheme)
            print(f"[add] {data['code']} — {data['name']}")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed NSFDC schemes into vittsetu.db.")
    parser.add_argument("--refresh", action="store_true",
                        help=f"overwrite these fields on existing schemes from this file: {', '.join(RULE_FIELDS)}")
    seed(parser.parse_args().refresh)
