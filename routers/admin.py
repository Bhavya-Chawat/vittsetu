"""Token-protected admin endpoints: partner capacity control + scheme/partner CRUD.

MVP auth: a single shared token via the ADMIN_TOKEN env var, not a full user
table — documented as an upgrade path in the transformation plan, appropriate
for a hackathon MVP where the only "admin" role is the team operating a demo
or an NSFDC ops user manually keeping partner capacity current.
"""

import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_db
from models import Scheme, Partner
from schemas import CapacityUpdateRequest, PartnerOut, SchemeOut

router = APIRouter(prefix="/api/admin", tags=["admin"])

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "vittsetu-admin-dev")


def require_admin(x_admin_token: Optional[str] = Header(default=None)):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing admin token")


class PartnerCreate(BaseModel):
    name: str
    partner_type: str
    state: Optional[str] = None
    district: Optional[str] = None
    address: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    eligible_scheme_codes: list[str] = []
    source_url: Optional[str] = None


class SchemeUpdate(BaseModel):
    """All fields optional — admin sends only what changed."""
    max_project_cost: Optional[float] = None
    max_financing_pct: Optional[float] = None
    max_loan_amount: Optional[float] = None
    interest_rate_to_beneficiary_pct: Optional[float] = None
    moratorium_min_months: Optional[int] = None
    moratorium_max_months: Optional[int] = None
    repayment_tenure_max_months: Optional[int] = None
    source_url: Optional[str] = None


@router.get("/partners", response_model=list[PartnerOut], dependencies=[Depends(require_admin)])
def admin_list_partners(db: Session = Depends(get_db)):
    return db.query(Partner).all()


@router.post("/partners", response_model=PartnerOut, dependencies=[Depends(require_admin)])
def admin_create_partner(payload: PartnerCreate, db: Session = Depends(get_db)):
    partner = Partner(**payload.model_dump())
    db.add(partner)
    db.commit()
    db.refresh(partner)
    return partner


@router.patch("/partners/{partner_id}/capacity", response_model=PartnerOut, dependencies=[Depends(require_admin)])
def admin_update_capacity(partner_id: int, payload: CapacityUpdateRequest, db: Session = Depends(get_db)):
    partner = db.query(Partner).get(partner_id)
    if not partner:
        raise HTTPException(status_code=404, detail="Partner not found")
    partner.capacity_status = payload.capacity_status
    partner.capacity_status_updated_by = payload.updated_by
    partner.capacity_status_updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(partner)
    return partner


@router.get("/schemes", response_model=list[SchemeOut], dependencies=[Depends(require_admin)])
def admin_list_schemes(db: Session = Depends(get_db)):
    return db.query(Scheme).all()


@router.put("/schemes/{code}", response_model=SchemeOut, dependencies=[Depends(require_admin)])
def admin_update_scheme(code: str, payload: SchemeUpdate, db: Session = Depends(get_db)):
    scheme = db.query(Scheme).filter_by(code=code.upper()).first()
    if not scheme:
        raise HTTPException(status_code=404, detail="Scheme not found")
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(scheme, field, value)
    if updates:
        scheme.last_verified_date = datetime.now(timezone.utc).date().isoformat()
    db.commit()
    db.refresh(scheme)
    return scheme
