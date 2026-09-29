"""Channel Partner locator endpoint."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db import get_db
from schemas import PartnersNearbyRequest, PartnersNearbyResponse
from partner_engine import find_nearby_partners, partner_out

router = APIRouter(prefix="/api", tags=["partners"])


@router.post("/partners/nearby", response_model=PartnersNearbyResponse)
def partners_nearby(req: PartnersNearbyRequest, db: Session = Depends(get_db)):
    result = find_nearby_partners(
        db, req.lat, req.lon, req.state, req.district, req.scheme_code, req.limit
    )
    return PartnersNearbyResponse(
        partners=[partner_out(m.partner, m.routing, m.distance_km) for m in result.partners],
        excluded=[partner_out(m.partner, m.routing, m.distance_km) for m in result.excluded],
        note=result.note,
    )
