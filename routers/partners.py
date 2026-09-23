"""Channel Partner locator endpoint."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db import get_db
from schemas import PartnersNearbyRequest, PartnerOut
from partner_engine import find_nearby_partners

router = APIRouter(prefix="/api", tags=["partners"])


@router.post("/partners/nearby", response_model=list[PartnerOut])
def partners_nearby(req: PartnersNearbyRequest, db: Session = Depends(get_db)):
    results = find_nearby_partners(
        db, req.lat, req.lon, req.state, req.district, req.scheme_code, req.limit
    )
    out = []
    for partner, distance in results:
        item = PartnerOut.model_validate(partner)
        item.distance_km = round(distance, 1) if distance is not None else None
        out.append(item)
    return out
