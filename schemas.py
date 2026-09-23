"""Pydantic request/response models for the scheme, calculator, and partner APIs."""

from typing import Optional, Literal
from pydantic import BaseModel, Field


# ── Eligibility & Recommendation ────────────────────────────────────────────

class ApplicantProfile(BaseModel):
    annual_family_income: float = Field(..., description="Annual family income in INR")
    is_sc_category: bool = Field(..., description="Self-declared SC category; verified by the Channel Partner at application stage")
    state: Optional[str] = None
    district: Optional[str] = None
    purpose: Literal["business", "education"] = "business"


class BusinessRequirement(BaseModel):
    project_type: str
    estimated_cost: float


class EducationRequirement(BaseModel):
    course_name: str
    course_fee: float
    repayment_started: bool = False


class EligibilityRequest(BaseModel):
    profile: ApplicantProfile


class EligibilityResponse(BaseModel):
    eligible: bool
    reasons: list[str]


class RecommendRequest(BaseModel):
    profile: ApplicantProfile
    business: Optional[BusinessRequirement] = None
    education: Optional[EducationRequirement] = None


class SchemeOut(BaseModel):
    code: str
    name: str
    scheme_type: str
    income_limit_annual: Optional[float]
    min_project_cost: Optional[float]
    max_project_cost: float
    max_financing_pct: float
    max_loan_amount: float
    interest_rate_to_beneficiary_pct: float
    moratorium_min_months: Optional[int]
    moratorium_max_months: Optional[int]
    moratorium_notes: Optional[str]
    repayment_tenure_max_months: int
    required_documents: list[str]
    eligible_partner_types: list[str]
    source_url: str
    last_verified_date: str

    class Config:
        from_attributes = True


class SchemeMatch(BaseModel):
    scheme: SchemeOut
    reasons: list[str]


class RecommendResponse(BaseModel):
    eligible: bool
    eligibility_reasons: list[str]
    matched: list[SchemeMatch]
    rejected: list[SchemeMatch]


# ── Financial Calculator ────────────────────────────────────────────────────

class CalculateRequest(BaseModel):
    scheme_code: str
    project_cost: float
    tenure_months: Optional[int] = None


class CalculateResponse(BaseModel):
    scheme_code: str
    project_cost: float
    financing_pct: float
    loan_amount: float
    applicant_contribution: float
    interest_rate_pct: float
    tenure_months: int
    moratorium_months: int
    monthly_emi: float
    total_interest: float
    total_payment: float
    notes: list[str]


# ── Partner Locator ──────────────────────────────────────────────────────────

class PartnersNearbyRequest(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None
    state: Optional[str] = None
    district: Optional[str] = None
    scheme_code: Optional[str] = None
    limit: int = 10


class PartnerOut(BaseModel):
    id: int
    name: str
    partner_type: str
    state: Optional[str]
    district: Optional[str]
    address: Optional[str]
    lat: Optional[float]
    lon: Optional[float]
    phone: Optional[str]
    email: Optional[str]
    capacity_status: str
    distance_km: Optional[float] = None
    eligible_scheme_codes: list[str]

    class Config:
        from_attributes = True


class CapacityUpdateRequest(BaseModel):
    capacity_status: Literal["available", "limited", "not_accepting"]
    updated_by: str = "admin"


# ── Free-text interpretation (AI-assisted) ──────────────────────────────────

class InterpretRequest(BaseModel):
    text: str
    language: str = "en"


class InterpretResponse(BaseModel):
    purpose: Optional[Literal["business", "education"]] = None
    project_type: Optional[str] = None
    estimated_cost: Optional[float] = None
    course_name: Optional[str] = None
    course_fee: Optional[float] = None
    confidence_note: str
