"""Scheme browsing, eligibility check, and recommendation endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db import get_db
from models import Scheme
from schemas import (
    EligibilityRequest, EligibilityResponse,
    RecommendRequest, RecommendResponse, SchemeMatch, SchemeOut,
)
from scheme_engine import check_eligibility, recommend_business, recommend_education

router = APIRouter(prefix="/api", tags=["schemes"])


@router.get("/schemes", response_model=list[SchemeOut])
def list_schemes(db: Session = Depends(get_db)):
    return db.query(Scheme).all()


@router.get("/schemes/{code}", response_model=SchemeOut)
def get_scheme(code: str, db: Session = Depends(get_db)):
    scheme = db.query(Scheme).filter_by(code=code.upper()).first()
    if not scheme:
        raise HTTPException(status_code=404, detail="Scheme not found")
    return scheme


@router.post("/eligibility", response_model=EligibilityResponse)
def eligibility(req: EligibilityRequest):
    eligible, reasons = check_eligibility(req.profile)
    return EligibilityResponse(eligible=eligible, reasons=reasons)


@router.post("/recommend", response_model=RecommendResponse)
def recommend(req: RecommendRequest, db: Session = Depends(get_db)):
    eligible, elig_reasons = check_eligibility(req.profile)
    if not eligible:
        return RecommendResponse(
            eligible=False, eligibility_reasons=elig_reasons, matched=[], rejected=[]
        )

    if req.profile.purpose == "education":
        if not req.education:
            raise HTTPException(status_code=400, detail="education requirement is required for purpose=education")
        matched, rejected = recommend_education(db, req.education)
    else:
        if not req.business:
            raise HTTPException(status_code=400, detail="business requirement is required for purpose=business")
        matched, rejected = recommend_business(db, req.business)

    return RecommendResponse(
        eligible=True,
        eligibility_reasons=elig_reasons,
        matched=[SchemeMatch(scheme=s, reasons=r) for s, r in matched],
        rejected=[SchemeMatch(scheme=s, reasons=r) for s, r in rejected],
    )
