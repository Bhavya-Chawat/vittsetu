"""Financial calculator endpoint."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db import get_db
from models import Partner, Scheme
from schemas import CalculateRequest, CalculateResponse
from financial_engine import LoanContext, calculate_loan

router = APIRouter(prefix="/api", tags=["calculate"])


@router.post("/calculate", response_model=CalculateResponse)
def calculate(req: CalculateRequest, db: Session = Depends(get_db)):
    scheme = db.query(Scheme).filter_by(code=req.scheme_code.upper()).first()
    if not scheme:
        raise HTTPException(status_code=404, detail="Scheme not found")

    # A selected partner decides the rate for schemes priced per partner type (e.g. UNY).
    partner_type = req.partner_type
    if req.partner_id is not None:
        partner = db.get(Partner, req.partner_id)
        if not partner:
            raise HTTPException(status_code=404, detail="Partner not found")
        if scheme.code not in (partner.eligible_scheme_codes or []):
            raise HTTPException(status_code=400, detail=f"{partner.name} does not channel the {scheme.name}.")
        partner_type = partner.partner_type

    try:
        return calculate_loan(
            scheme,
            req.project_cost,
            req.tenure_months,
            loan_amount=req.loan_amount,
            repayment_frequency=req.repayment_frequency,
            partner_type=partner_type,
            context=LoanContext(
                activity_category=req.activity_category,
                repayment_started=req.repayment_started,
                course_duration_months=req.course_duration_months,
            ),
            moratorium_interest=req.moratorium_interest,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
