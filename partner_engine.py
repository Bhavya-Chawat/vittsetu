"""Channel Partner compatibility filtering + geospatial ranking.

capacity_status is a live, admin-operated field (see models.Partner) — not a
statistic sourced from anywhere, since NSFDC does not publish per-partner
fund-utilization/NPA data publicly. Every partner defaults to "available"
until an admin changes it; this module simply filters/ranks on whatever the
field currently holds.
"""

import math
from sqlalchemy.orm import Session
from models import Partner

_CAPACITY_RANK = {"available": 0, "limited": 1, "not_accepting": 2}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def find_nearby_partners(
    db: Session,
    lat: float | None,
    lon: float | None,
    state: str | None,
    district: str | None,
    scheme_code: str | None,
    limit: int = 10,
) -> list[tuple[Partner, float | None]]:
    query = db.query(Partner).filter(Partner.capacity_status != "not_accepting")

    if scheme_code:
        query = query.filter(Partner.eligible_scheme_codes.contains(scheme_code))

    if district:
        query = query.filter(Partner.district == district)
    elif state:
        query = query.filter(Partner.state == state)

    partners = query.all()

    results: list[tuple[Partner, float | None]] = []
    for p in partners:
        distance = None
        if lat is not None and lon is not None and p.lat is not None and p.lon is not None:
            distance = haversine_km(lat, lon, p.lat, p.lon)
        results.append((p, distance))

    def sort_key(pair: tuple[Partner, float | None]):
        partner, distance = pair
        capacity_rank = _CAPACITY_RANK.get(partner.capacity_status, 1)
        distance_rank = distance if distance is not None else float("inf")
        return (capacity_rank, distance_rank)

    results.sort(key=sort_key)
    return results[:limit]
