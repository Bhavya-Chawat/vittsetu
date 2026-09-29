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

    # Guideline rules as data, evaluated by financial_engine (format documented
    # there; values transcribed in scripts/seed_schemes.py). NULL falls back to
    # the flat fields above: moratorium_min_months, repayment_tenure_max_months,
    # interest_rate_to_beneficiary_pct.
    moratorium_rules = Column(JSON, nullable=True)
    tenure_rules = Column(JSON, nullable=True)
    rates_by_partner_type = Column(JSON, nullable=True)  # {"Small Finance Bank": 15, ...}

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

    # Portfolio-health metrics used by the routing policy (partner_engine.py).
    # NSFDC does not publish these per partner, so they are ONLY ever
    # admin-entered (or explicitly-labelled demo data from
    # scripts/seed_demo_metrics.py, metrics_updated_by == "DEMO DATA").
    # NULL means "no data" — never fill in a guess.
    fund_utilization_pct = Column(Float, nullable=True)
    npa_pct = Column(Float, nullable=True)
    overdue_pct = Column(Float, nullable=True)
    allocated_funds_inr = Column(Float, nullable=True)
    disbursed_funds_inr = Column(Float, nullable=True)
    metrics_as_of_date = Column(String(20), nullable=True)  # ISO date the figures describe
    metrics_updated_by = Column(String(100), nullable=True)

    source_url = Column(String(500), nullable=True)
    source_captured_date = Column(String(20), nullable=True)

    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class Application(Base):
    """An applicant's request routed to a chosen Channel Partner.

    VittSetu doesn't process loans: the formal application is still made on
    the official PM-SURAJ portal / with the partner. This records the routing
    and lets the applicant track it by reference (see routers/applications.py
    for the status lifecycle).
    """
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True)
    reference = Column(String(20), unique=True, index=True, nullable=True)  # VS-2026-000123

    # Optional PII — never returned by the public status endpoint.
    applicant_name = Column(String(200), nullable=True)
    applicant_contact = Column(String(100), nullable=True)
    applicant_state = Column(String(100), nullable=True)
    applicant_district = Column(String(100), nullable=True)
    consent_given_at = Column(DateTime, nullable=True)

    scheme_id = Column(Integer, ForeignKey("schemes.id"), nullable=True)
    partner_id = Column(Integer, ForeignKey("partners.id"), nullable=True)

    project_cost = Column(Float, nullable=True)
    requested_loan_amount = Column(Float, nullable=True)

    # Routing decision at submission time, kept for audit even if the
    # partner's metrics change later.
    routing_status_at_submission = Column(String(20), nullable=True)
    routing_reason_at_submission = Column(Text, nullable=True)

    # routed | acknowledged_by_partner | handed_off_to_pmsuraj | sanctioned | disbursed | rejected
    status = Column(String(30), default="routed")

    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    scheme = relationship("Scheme")
    partner = relationship("Partner")
    events = relationship("ApplicationEvent", back_populates="application", order_by="ApplicationEvent.id")


class ApplicationEvent(Base):
    """Append-only audit trail of an application's lifecycle."""
    __tablename__ = "application_events"

    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False, index=True)
    event_type = Column(String(30), nullable=False)  # created | status_changed
    from_status = Column(String(30), nullable=True)
    to_status = Column(String(30), nullable=True)
    note = Column(Text, nullable=True)  # admin-only; may contain operational detail
    actor = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    application = relationship("Application", back_populates="events")


class AdminAuditLog(Base):
    """Append-only record of every admin change, with before/after snapshots (see audit.py)."""
    __tablename__ = "admin_audit_log"

    id = Column(Integer, primary_key=True)
    entity_type = Column(String(30), nullable=False, index=True)  # partner | scheme | application
    entity_id = Column(String(40), nullable=False, index=True)  # partner id, scheme code, application reference
    action = Column(String(40), nullable=False)  # created | updated | capacity_changed | metrics_updated | ...
    actor = Column(String(100), nullable=False)
    before = Column(JSON, nullable=True)  # None for creations
    after = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=_utcnow, index=True)
