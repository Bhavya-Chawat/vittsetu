"""SQLAlchemy models for schemes, channel partners, and applications.

Field names mirror the verified NSFDC data captured in the transformation
plan (see plans/ in the repo root, or the project README) — every Scheme
row must carry source_url + source_captured_date so figures stay traceable
to an official document, never invented.
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Float, Text, JSON, DateTime, ForeignKey,
)
from sqlalchemy.orm import relationship
from db import Base


def _utcnow():
    return datetime.now(timezone.utc)


class Scheme(Base):
    __tablename__ = "schemes"

    id = Column(Integer, primary_key=True)
    code = Column(String(32), unique=True, nullable=False)  # MFS, TERM_LOAN, AMY, UNY, ELS
    name = Column(String(200), nullable=False)
    scheme_type = Column(String(50), nullable=False)  # micro_finance | term_loan | education_loan | ...
    administering_agency = Column(String(100), default="NSFDC")
    applicant_category = Column(String(50), default="SC")

    income_limit_annual = Column(Float, nullable=True)  # INR

    min_project_cost = Column(Float, nullable=True)
    max_project_cost = Column(Float, nullable=False)
    max_financing_pct = Column(Float, nullable=False)
    max_loan_amount = Column(Float, nullable=False)

    interest_rate_to_partner_pct = Column(Float, nullable=False)
    interest_rate_to_beneficiary_pct = Column(Float, nullable=False)

    moratorium_min_months = Column(Integer, nullable=True)
    moratorium_max_months = Column(Integer, nullable=True)
    moratorium_notes = Column(Text, nullable=True)

    repayment_tenure_max_months = Column(Integer, nullable=False)

    eligible_activities = Column(JSON, default=list)
    education_criteria = Column(JSON, nullable=True)
    required_documents = Column(JSON, default=list)
    eligible_partner_types = Column(JSON, default=list)

    source_url = Column(String(500), nullable=False)
    source_captured_date = Column(String(20), nullable=False)  # ISO date string
    last_verified_date = Column(String(20), nullable=False)

    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class Partner(Base):
    __tablename__ = "partners"

    id = Column(Integer, primary_key=True)
    name = Column(String(300), nullable=False)
    partner_type = Column(String(50), nullable=False)  # SCA | PSB | RRB | NBFC-MFI | ...

    state = Column(String(100), nullable=True)
    district = Column(String(100), nullable=True)
    address = Column(Text, nullable=True)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    phone = Column(String(100), nullable=True)
    email = Column(String(200), nullable=True)

    eligible_scheme_codes = Column(JSON, default=list)

    capacity_status = Column(String(20), default="available")  # available | limited | not_accepting
    capacity_status_updated_by = Column(String(100), nullable=True)
    capacity_status_updated_at = Column(DateTime, nullable=True)

    source_url = Column(String(500), nullable=True)
    source_captured_date = Column(String(20), nullable=True)

    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class Application(Base):
    """Lightweight MVP tracking stub — not a real application-processing workflow.

    Real submission happens on the official PM-SURAJ portal; this table only
    records that a beneficiary was matched and routed, for demo/tracking purposes.
    """
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True)
    applicant_name = Column(String(200), nullable=True)
    applicant_contact = Column(String(100), nullable=True)

    scheme_id = Column(Integer, ForeignKey("schemes.id"), nullable=True)
    partner_id = Column(Integer, ForeignKey("partners.id"), nullable=True)

    project_cost = Column(Float, nullable=True)
    requested_loan_amount = Column(Float, nullable=True)

    status = Column(String(30), default="draft")  # draft | matched | routed | handed_off_to_pmsuraj

    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    scheme = relationship("Scheme")
    partner = relationship("Partner")
