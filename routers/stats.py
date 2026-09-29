"""Public coverage statistics for the home page — counts only, no partner metrics."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db import get_db
from models import Partner, Scheme
from partner_engine import DEMO_DATA_TAG, EXCLUDED, RoutingPolicy, evaluate_routing
from schemas import SchemeCoverage, StatsResponse

router = APIRouter(prefix="/api", tags=["stats"])


@router.get("/stats", response_model=StatsResponse)
def stats(db: Session = Depends(get_db)):
    policy = RoutingPolicy.from_env()
    partners = db.query(Partner).all()
    routable = {p.id for p in partners if evaluate_routing(p, policy).status != EXCLUDED}

    by_type: dict[str, int] = {}
    for p in partners:
        by_type[p.partner_type] = by_type.get(p.partner_type, 0) + 1

    per_scheme = []
    for s in db.query(Scheme).order_by(Scheme.id):
        listed = [p for p in partners if s.code in (p.eligible_scheme_codes or [])]
        live = [p for p in listed if p.id in routable]
        per_scheme.append(SchemeCoverage(
            code=s.code, name=s.name, partners=len(listed), routable_partners=len(live),
            states_with_routable_partner=len({p.state for p in live if p.state}),
        ))

    demo = sum(1 for p in partners if p.metrics_updated_by == DEMO_DATA_TAG)
    real = sum(1 for p in partners if p.metrics_updated_by not in (None, DEMO_DATA_TAG))
    return StatsResponse(
        schemes=len(per_scheme),
        partners=len(partners),
        partners_mapped=sum(1 for p in partners if p.lat is not None and p.lon is not None),
        states_covered=len({p.state for p in partners if p.state}),
        partners_by_type=dict(sorted(by_type.items())),
        per_scheme=per_scheme,
        metrics_coverage={"real": real, "demo": demo, "none": len(partners) - real - demo},
    )
