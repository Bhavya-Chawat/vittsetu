"""Financial calculator endpoint."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db import get_db
from models import Scheme
from schemas import CalculateRequest, CalculateResponse
from financial_engine import calculate_loan

router = APIRouter(prefix="/api", tags=["calculate"])


@router.post("/calculate", response_model=CalculateResponse)
def calculate(req: CalculateRequest, db: Session = Depends(get_db)):
    scheme = db.query(Scheme).filter_by(code=req.scheme_code.upper()).first()
    if not scheme:
        raise HTTPException(status_code=404, detail="Scheme not found")
    try:
        return calculate_loan(scheme, req.project_cost, req.tenure_months)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
