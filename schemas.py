"""Pydantic request/response models for the scheme, calculator, and partner APIs."""

from datetime import date, datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field, field_validator


# ── Eligibility & Recommendation ────────────────────────────────────────────

class ApplicantProfile(BaseModel):
    annual_family_income: float = Field(..., description="Annual family income in INR")
    is_sc_category: bool = Field(..., description="Self-declared SC category; verified by the Channel Partner at application stage")
    state: Optional[str] = None
    district: Optional[str] = None
    purpose: Literal["business", "education"] = "business"


ActivityCategoryId = Literal[
    "agriculture_allied", "plantation", "construction", "manufacturing", "trade_retail", "services", "transport",
]  # must match reference_data/activity_taxonomy.json (checked by a test)

RepaymentFrequency = Literal["monthly", "quarterly", "half_yearly"]


class BusinessRequirement(BaseModel):
    project_type: str
    estimated_cost: float
    # Confirmed by the user in the UI; if omitted it is classified from project_type.
    activity_category: Optional[ActivityCategoryId] = None


class EducationRequirement(BaseModel):
    course_name: str
    course_fee: float
    repayment_started: bool = False
    course_duration_months: Optional[int] = Field(default=None, ge=1, le=120)


class EligibilityRequest(BaseModel):
    profile: ApplicantProfile


class EligibilityResponse(BaseModel):
    eligible: bool
    reasons: list[str]


class RecommendRequest(BaseModel):
    profile: ApplicantProfile
    business: Optional[BusinessRequirement] = None
    education: Optional[EducationRequirement] = None
    # Optional device location, used only to judge partner availability for the best fit.
    lat: Optional[float] = None
    lon: Optional[float] = None


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
    rates_by_partner_type: Optional[dict[str, float]] = None
    source_url: str
    last_verified_date: str

    class Config:
        from_attributes = True


class SchemeMatch(BaseModel):
    scheme: SchemeOut
    reasons: list[str]
    matched_course: Optional[str] = None  # education: the recognized NSFDC course it matched


class ActivityOut(BaseModel):
    category: Optional[ActivityCategoryId]
    label: Optional[str]
    source: Literal["user_confirmed", "keyword_match", "unclassified"]
    matched_keywords: list[str] = []


class ActivityCategoryOut(BaseModel):
    id: ActivityCategoryId
    label: str
    label_hi: str


class ClassifyRequest(BaseModel):
    text: str = Field(..., max_length=500)


class PartnerAvailability(BaseModel):
    level: Literal["local", "unspecified", "elsewhere", "none"]
    routable_partner_count: int
    nearest_partner_name: Optional[str] = None
    nearest_distance_km: Optional[float] = None
    summary: str


class SchemeComparison(BaseModel):
    """One row of the side-by-side comparison, evaluated for this applicant."""
    code: str
    name: str
    is_best_fit: bool
    rate_display: str  # e.g. "6.5%" or "13–15%"
    effective_rate_pct: float  # the rate this applicant would most likely get (see best_fit)
    effective_rate_partner_type: Optional[str]
    loan_for_this_cost: float
    max_loan_amount: float
    moratorium_months: Optional[int]  # None if it depends on an input not given (e.g. course duration)
    moratorium_basis: str
    tenure_max_months: int
    tenure_basis: str
    partner_types: list[str]
    availability: PartnerAvailability
    # Illustration at the guideline defaults (max loan, max tenure, quarterly); None if not computable.
    quarterly_instalment: Optional[float] = None
    total_interest: Optional[float] = None


class BestFit(BaseModel):
    scheme_code: str
    scheme_name: str
    effective_rate_pct: float
    effective_rate_partner_type: Optional[str]
    reasons: list[str]
    alternatives: dict[str, list[str]]  # scheme code → trade-offs versus the best fit


class RecommendResponse(BaseModel):
    eligible: bool
    eligibility_reasons: list[str]
    matched: list[SchemeMatch]
    rejected: list[SchemeMatch]
    activity: Optional[ActivityOut] = None
    best_fit: Optional[BestFit] = None
    comparison: list[SchemeComparison] = []


# ── Financial Calculator ────────────────────────────────────────────────────

class CalculateRequest(BaseModel):
    scheme_code: str
    project_cost: float = Field(..., gt=0)
    loan_amount: Optional[float] = Field(default=None, gt=0, description="Defaults to the maximum eligible loan")
    tenure_months: Optional[int] = Field(default=None, ge=1, description="Total months from disbursement; defaults to the maximum")
    repayment_frequency: RepaymentFrequency = "quarterly"
    partner_id: Optional[int] = Field(default=None, description="Selected partner — sets the rate for partner-dependent schemes")
    partner_type: Optional[str] = None
    activity_category: Optional[ActivityCategoryId] = None
    repayment_started: bool = False
    course_duration_months: Optional[int] = Field(default=None, ge=1, le=120)
    moratorium_interest: Literal["capitalized", "serviced"] = "capitalized"


class ScheduleRow(BaseModel):
    period: int
    due_month: int  # months after disbursement
    opening_balance: float
    instalment: float
    interest: float
    principal: float
    closing_balance: float


class CalculateResponse(BaseModel):
    scheme_code: str
    project_cost: float
    financing_pct: float
    max_loan_amount: float  # the most this scheme lends for this cost
    loan_amount: float
    applicant_contribution: float
    interest_rate_pct: float
    rate_partner_type: Optional[str]
    rate_basis: str
    rate_options: dict[str, float]  # partner type → rate
    repayment_frequency: RepaymentFrequency
    period_months: int
    number_of_instalments: int
    moratorium_months: int
    moratorium_basis: str
    moratorium_interest: float
    moratorium_interest_treatment: Literal["capitalized", "serviced"]
    principal_after_moratorium: float
    tenure_months: int  # total, from disbursement
    repayment_months: int
    min_tenure_months: int
    max_tenure_months: int
    tenure_basis: str
    tenure_includes_moratorium: bool
    instalment_amount: float
    monthly_equivalent: float
    total_payment: float  # everything paid to the lender
    total_interest: float
    total_cost: float  # total_payment + your own contribution
    schedule: list[ScheduleRow]
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

    # Admin-entered portfolio metrics — None means "no data", never a guess.
    fund_utilization_pct: Optional[float] = None
    npa_pct: Optional[float] = None
    overdue_pct: Optional[float] = None
    allocated_funds_inr: Optional[float] = None
    disbursed_funds_inr: Optional[float] = None
    metrics_as_of_date: Optional[str] = None
    metrics_updated_by: Optional[str] = None
    metrics_is_demo: bool = False  # True for scripts/seed_demo_metrics.py figures

    # Computed by partner_engine's routing policy.
    routing_status: Optional[Literal["eligible", "deprioritized", "excluded", "no_data"]] = None
    routing_reason: Optional[str] = None

    class Config:
        from_attributes = True


class PartnersNearbyResponse(BaseModel):
    partners: list[PartnerOut]  # routable, best first
    excluded: list[PartnerOut] = []  # routed away (high NPA/overdues, poor utilization, not accepting)
    note: Optional[str] = None  # e.g. "no partners in your state — showing national results"


class PartnerMetricsUpdate(BaseModel):
    """Admin-entered portfolio figures. Omitted fields are left unchanged;
    an explicit null clears a figure back to "no data"."""
    fund_utilization_pct: Optional[float] = Field(default=None, ge=0, le=100)
    npa_pct: Optional[float] = Field(default=None, ge=0, le=100)
    overdue_pct: Optional[float] = Field(default=None, ge=0, le=100)
    allocated_funds_inr: Optional[float] = Field(default=None, ge=0)
    disbursed_funds_inr: Optional[float] = Field(default=None, ge=0)
    metrics_as_of_date: date = Field(..., description="Date the figures describe — required so every figure is dated")
    updated_by: str = Field(default="admin", min_length=1, max_length=100)

    @field_validator("metrics_as_of_date")
    @classmethod
    def not_in_future(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("metrics_as_of_date cannot be in the future")
        return v


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
    # Deterministic keyword classification (activity_taxonomy), not the LLM's guess.
    activity_category: Optional[ActivityCategoryId] = None
    estimated_cost: Optional[float] = None
    course_name: Optional[str] = None
    course_fee: Optional[float] = None
    confidence_note: str


# ── Applications ────────────────────────────────────────────────────────────

ApplicationStatus = Literal[
    "routed", "acknowledged_by_partner", "handed_off_to_pmsuraj", "sanctioned", "disbursed", "rejected",
]


class ApplicationCreate(BaseModel):
    scheme_code: str
    partner_id: int
    consent: bool = Field(..., description="Applicant agrees to share these details with the chosen partner")
    applicant_name: Optional[str] = Field(default=None, max_length=200)
    applicant_contact: Optional[str] = Field(default=None, max_length=100)
    state: Optional[str] = Field(default=None, max_length=100)
    district: Optional[str] = Field(default=None, max_length=100)
    project_cost: Optional[float] = Field(default=None, gt=0)
    loan_amount: Optional[float] = Field(default=None, gt=0, description="Defaults to the maximum eligible loan")

    @field_validator("applicant_name", "applicant_contact", "state", "district")
    @classmethod
    def blank_to_none(cls, v: Optional[str]) -> Optional[str]:
        v = v.strip() if v else v
        return v or None


class ApplicationEventOut(BaseModel):
    event_type: str
    from_status: Optional[str]
    to_status: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class ApplicationPublic(BaseModel):
    """Public status view — deliberately carries no applicant PII."""
    reference: str
    status: ApplicationStatus
    scheme_code: str
    scheme_name: str
    partner_name: str
    partner_type: str
    partner_phone: Optional[str]
    partner_address: Optional[str]
    requested_loan_amount: Optional[float]
    created_at: datetime
    updated_at: datetime
    timeline: list[ApplicationEventOut]


class ApplicationAdminEventOut(ApplicationEventOut):
    note: Optional[str]
    actor: Optional[str]


class ApplicationAdmin(ApplicationPublic):
    applicant_name: Optional[str]
    applicant_contact: Optional[str]
    applicant_state: Optional[str]
    applicant_district: Optional[str]
    project_cost: Optional[float]
    consent_given_at: Optional[datetime]
    routing_status_at_submission: Optional[str]
    routing_reason_at_submission: Optional[str]
    timeline: list[ApplicationAdminEventOut]


class ApplicationStatusUpdate(BaseModel):
    status: ApplicationStatus
    note: Optional[str] = Field(default=None, max_length=1000)
    updated_by: str = Field(default="admin", min_length=1, max_length=100)
