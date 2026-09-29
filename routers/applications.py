"""Application routing: send an applicant's request to a chosen Channel Partner,
then track it through the partner / PM-SURAJ lifecycle.

VittSetu doesn't sanction loans. The status here mirrors what happens
off-platform (with the partner and on the official PM-SURAJ portal) and is
advanced by an admin. The public lookup by reference number never exposes
applicant PII.

Lifecycle:
  routed → acknowledged_by_partner → handed_off_to_pmsuraj → sanctioned → disbursed
  (any non-final status) → rejected
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db import get_db
from financial_engine import max_eligible_loan
from models import Application, ApplicationEvent, Partner, Scheme
from partner_engine import EXCLUDED, RoutingPolicy, evaluate_routing
from routers.admin import require_admin
from schemas import (
    ApplicationAdmin, ApplicationAdminEventOut, ApplicationCreate, ApplicationEventOut,
    ApplicationPublic, ApplicationStatus, ApplicationStatusUpdate,
)

router = APIRouter(tags=["applications"])

NEXT_STATUS = {
    "routed": "acknowledged_by_partner",
    "acknowledged_by_partner": "handed_off_to_pmsuraj",
    "handed_off_to_pmsuraj": "sanctioned",
    "sanctioned": "disbursed",
}
FINAL_STATUSES = {"disbursed", "rejected"}


def allowed_next_statuses(current: str) -> list[str]:
    if current in FINAL_STATUSES:
        return []
    return [NEXT_STATUS[current], "rejected"]


def _reference(app: Application) -> str:
    return f"VS-{app.created_at.year}-{app.id:06d}"


def _public(app: Application) -> ApplicationPublic:
    return ApplicationPublic(
        reference=app.reference,
        status=app.status,
        scheme_code=app.scheme.code,
        scheme_name=app.scheme.name,
        partner_name=app.partner.name,
        partner_type=app.partner.partner_type,
        partner_phone=app.partner.phone,
        partner_address=app.partner.address,
        requested_loan_amount=app.requested_loan_amount,
        created_at=app.created_at,
        updated_at=app.updated_at,
        timeline=[ApplicationEventOut.model_validate(e) for e in app.events],
    )


def _admin(app: Application) -> ApplicationAdmin:
    return ApplicationAdmin(
        **_public(app).model_dump(exclude={"timeline"}),
        applicant_name=app.applicant_name,
        applicant_contact=app.applicant_contact,
        applicant_state=app.applicant_state,
        applicant_district=app.applicant_district,
        project_cost=app.project_cost,
        consent_given_at=app.consent_given_at,
        routing_status_at_submission=app.routing_status_at_submission,
        routing_reason_at_submission=app.routing_reason_at_submission,
        timeline=[ApplicationAdminEventOut.model_validate(e) for e in app.events],
    )


def _get_by_reference(db: Session, reference: str) -> Application:
    app = db.query(Application).filter_by(reference=reference.strip().upper()).first()
    if not app:
        raise HTTPException(status_code=404, detail="No application found with that reference number")
    return app


@router.post("/api/applications", response_model=ApplicationPublic, status_code=201)
def create_application(req: ApplicationCreate, db: Session = Depends(get_db)):
    if not req.consent:
        raise HTTPException(
            status_code=400,
            detail="Consent is required to share your application details with the chosen Channel Partner.",
        )

    scheme = db.query(Scheme).filter_by(code=req.scheme_code.upper()).first()
    if not scheme:
        raise HTTPException(status_code=404, detail="Scheme not found")
    partner = db.get(Partner, req.partner_id)
    if not partner:
        raise HTTPException(status_code=404, detail="Partner not found")

    if scheme.code not in (partner.eligible_scheme_codes or []):
        raise HTTPException(
            status_code=400,
            detail=f"{partner.name} does not channel the {scheme.name} — choose a partner listed for this scheme.",
        )
    routing = evaluate_routing(partner, RoutingPolicy.from_env())
    if routing.status == EXCLUDED:
        raise HTTPException(status_code=409, detail=f"{partner.name} cannot take applications right now. {routing.reason}")

    requested_loan = None
    if req.project_cost is not None:
        if scheme.scheme_type != "education_loan":
            too_small = scheme.min_project_cost is not None and req.project_cost < scheme.min_project_cost
            if too_small or req.project_cost > scheme.max_project_cost:
                raise HTTPException(status_code=400, detail=f"Project cost is outside the {scheme.name}'s eligible range.")
        requested_loan = max_eligible_loan(scheme, req.project_cost)
        if req.loan_amount is not None:
            if req.loan_amount > requested_loan:
                raise HTTPException(
                    status_code=400,
                    detail=f"Requested loan exceeds the scheme's maximum of ₹{requested_loan:,.0f} for this project cost.",
                )
            requested_loan = round(req.loan_amount, 2)
    elif req.loan_amount is not None:
        raise HTTPException(status_code=400, detail="project_cost is required when loan_amount is given.")

    now = datetime.now(timezone.utc)
    app = Application(
        applicant_name=req.applicant_name,
        applicant_contact=req.applicant_contact,
        applicant_state=req.state,
        applicant_district=req.district,
        consent_given_at=now,
        scheme_id=scheme.id,
        partner_id=partner.id,
        project_cost=req.project_cost,
        requested_loan_amount=requested_loan,
        routing_status_at_submission=routing.status,
        routing_reason_at_submission=routing.reason,
        status="routed",
        created_at=now,
    )
    db.add(app)
    db.flush()  # assigns app.id, which the reference number is built from
    app.reference = _reference(app)
    db.add(ApplicationEvent(
        application_id=app.id, event_type="created", to_status="routed", actor="applicant",
        note=f"Routed to {partner.name} ({partner.partner_type}). Routing: {routing.reason}",
    ))
    db.commit()
    db.refresh(app)
    return _public(app)


@router.get("/api/applications/{reference}", response_model=ApplicationPublic)
def get_application_status(reference: str, db: Session = Depends(get_db)):
    """Public status lookup — anyone holding the reference sees status only, no PII."""
    return _public(_get_by_reference(db, reference))


@router.get("/api/admin/applications", response_model=list[ApplicationAdmin], dependencies=[Depends(require_admin)])
def admin_list_applications(status: Optional[ApplicationStatus] = None, db: Session = Depends(get_db)):
    query = db.query(Application).filter(Application.reference.isnot(None))
    if status:
        query = query.filter(Application.status == status)
    return [_admin(a) for a in query.order_by(Application.id.desc())]


@router.patch(
    "/api/admin/applications/{reference}/status",
    response_model=ApplicationAdmin, dependencies=[Depends(require_admin)],
)
def admin_update_application_status(reference: str, req: ApplicationStatusUpdate, db: Session = Depends(get_db)):
    app = _get_by_reference(db, reference)
    allowed = allowed_next_statuses(app.status)
    if req.status not in allowed:
        detail = (f"Application is already {app.status} (final)." if not allowed
                  else f"Cannot move from {app.status} to {req.status}; allowed: {', '.join(allowed)}.")
        raise HTTPException(status_code=409, detail=detail)

    db.add(ApplicationEvent(
        application_id=app.id, event_type="status_changed", from_status=app.status, to_status=req.status,
        note=req.note, actor=f"admin:{req.updated_by.strip()}",
    ))
    app.status = req.status
    db.commit()
    db.refresh(app)
    return _admin(app)
