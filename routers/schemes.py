"""Scheme browsing, eligibility check, recommendation and activity-taxonomy endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import activity_taxonomy
from db import get_db
from models import Scheme
from schemas import (
    ActivityCategoryOut, ActivityOut, ClassifyRequest, EligibilityRequest, EligibilityResponse,
    RecommendRequest, RecommendResponse, SchemeOut,
)
from scheme_engine import candidate_schemes, check_eligibility, recommend as run_recommend

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
def eligibility(req: EligibilityRequest, db: Session = Depends(get_db)):
    eligible, reasons = check_eligibility(req.profile, candidate_schemes(db, req.profile.purpose))
    return EligibilityResponse(eligible=eligible, reasons=reasons)


@router.post("/recommend", response_model=RecommendResponse)
def recommend(req: RecommendRequest, db: Session = Depends(get_db)):
    try:
        return run_recommend(db, req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/activities", response_model=list[ActivityCategoryOut])
def list_activities():
    return [
        ActivityCategoryOut(id=c.id, label=c.label, label_hi=c.label_hi)
        for c in activity_taxonomy.load_taxonomy()[0]
    ]


@router.post("/activities/classify", response_model=ActivityOut)
def classify_activity(req: ClassifyRequest):
    """Deterministic keyword classification of a business description."""
    result = activity_taxonomy.classify(req.text)
    if result.category is None:
        return ActivityOut(category=None, label=None, source="unclassified")
    return ActivityOut(
        category=result.category,
        label=activity_taxonomy.get_category(result.category).label,
        source="keyword_match",
        matched_keywords=list(result.matched_keywords),
    )
