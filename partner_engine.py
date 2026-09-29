"""Channel Partner routing policy, compatibility filtering + geospatial ranking.

Two independent, admin-operated signals decide where applications go:

  - capacity_status (available / limited / not_accepting): a manual switch.
    not_accepting always excludes the partner.
  - Portfolio-health metrics (NPA %, overdue %, fund utilization %): figures
    NSFDC tracks internally but does not publish per partner, so they only
    ever come from an admin (or from explicitly-labelled demo data). A
    partner with none on record is "no_data" — it stays routable, ranked
    after partners with healthy figures, and is never assigned guessed values.

RoutingPolicy turns those into a routing_status + human-readable reason:
  eligible       metrics on record and within all thresholds
  no_data        no (current) metrics on record
  deprioritized  a metric crosses a "deprioritize" threshold — still routable, ranked last
  excluded       a metric crosses an "exclude" threshold, or capacity is not_accepting

Search modes:
  - Location given (lat/lon): compatible partners nationwide, no state filter
    (the nearest partner may be across a state border).
  - No location: the applicant's state if given, falling back to national
    results (with a note) if that state has no routable partner.

Routable partners are ranked by routing status, then capacity, then locality
(distance with a location; otherwise a district match against the address —
district is a preference, never a filter, since NSFDC's directories give
free-text addresses and most partners have district=NULL). Excluded partners
are returned separately so the UI can show why they were routed away.
"""

import math
import os
import re
from dataclasses import dataclass, field, fields
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from models import Partner
from schemas import PartnerOut

ELIGIBLE, NO_DATA, DEPRIORITIZED, EXCLUDED = "eligible", "no_data", "deprioritized", "excluded"
DEMO_DATA_TAG = "DEMO DATA"  # metrics_updated_by value written by scripts/seed_demo_metrics.py

_ROUTING_RANK = {ELIGIBLE: 0, NO_DATA: 1, DEPRIORITIZED: 2}
_CAPACITY_RANK = {"available": 0, "limited": 1, "not_accepting": 2}


# ── Routing policy ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RoutingPolicy:
    """Thresholds for routing on portfolio health. All values are percentages.

    NPA/overdue: a value >= the threshold triggers it. Utilization: a value
    strictly below the threshold triggers it. Defaults are illustrative
    starting points for NSFDC operations to tune — override any of them with
    VITTSETU_ROUTING_<FIELD_NAME_UPPERCASE> env vars (see from_env).
    """
    npa_deprioritize_pct: float = 5.0
    npa_exclude_pct: float = 10.0
    overdue_deprioritize_pct: float = 10.0
    overdue_exclude_pct: float = 25.0
    utilization_deprioritize_below_pct: float = 60.0
    utilization_exclude_below_pct: float = 30.0
    # Figures older than this are treated as no_data. None disables the check.
    max_metrics_age_days: int | None = 365

    def __post_init__(self):
        if self.npa_deprioritize_pct > self.npa_exclude_pct:
            raise ValueError("npa_deprioritize_pct must be <= npa_exclude_pct")
        if self.overdue_deprioritize_pct > self.overdue_exclude_pct:
            raise ValueError("overdue_deprioritize_pct must be <= overdue_exclude_pct")
        if self.utilization_exclude_below_pct > self.utilization_deprioritize_below_pct:
            raise ValueError("utilization_exclude_below_pct must be <= utilization_deprioritize_below_pct")

    @classmethod
    def from_env(cls, environ=None) -> "RoutingPolicy":
        environ = os.environ if environ is None else environ
        overrides = {}
        for f in fields(cls):
            raw = environ.get(f"VITTSETU_ROUTING_{f.name.upper()}")
            if raw is None or raw.strip() == "":
                continue
            if f.name == "max_metrics_age_days":
                overrides[f.name] = None if raw.strip().lower() in ("none", "off") else int(raw)
            else:
                overrides[f.name] = float(raw)
        return cls(**overrides)


@dataclass(frozen=True)
class RoutingDecision:
    status: str
    reason: str


def has_demo_metrics(partner: Partner) -> bool:
    return partner.metrics_updated_by == DEMO_DATA_TAG


def effective_utilization_pct(partner: Partner) -> float | None:
    """Stored utilization %, else disbursed / allocated when both are on record."""
    if partner.fund_utilization_pct is not None:
        return partner.fund_utilization_pct
    if partner.allocated_funds_inr and partner.disbursed_funds_inr is not None:
        return partner.disbursed_funds_inr / partner.allocated_funds_inr * 100
    return None


def _pct(value: float) -> str:
    return f"{value:.1f}%".replace(".0%", "%")


def evaluate_routing(partner: Partner, policy: RoutingPolicy | None = None, today: date | None = None) -> RoutingDecision:
    policy = policy or RoutingPolicy()
    today = today or date.today()

    def decision(status: str, reason: str) -> RoutingDecision:
        """A decision based on the metrics — flagged in the reason text if they're demo figures."""
        if has_demo_metrics(partner):
            reason += " [DEMO DATA — illustrative figures, not real NSFDC data]"
        return RoutingDecision(status, reason)

    if partner.capacity_status == "not_accepting":
        return RoutingDecision(EXCLUDED, "This partner has marked itself as not currently accepting applications.")

    npa, overdue, util = partner.npa_pct, partner.overdue_pct, effective_utilization_pct(partner)
    if npa is None and overdue is None and util is None:
        return RoutingDecision(
            NO_DATA,
            "No NPA, overdue or fund-utilization figures on record for this partner — "
            "ranked after partners with healthy figures.",
        )

    as_of = partner.metrics_as_of_date
    if as_of and policy.max_metrics_age_days is not None:
        try:
            age_days = (today - date.fromisoformat(as_of)).days
        except ValueError:
            age_days = None
        if age_days is not None and age_days > policy.max_metrics_age_days:
            return RoutingDecision(
                NO_DATA,
                f"Portfolio figures are from {as_of}, older than {policy.max_metrics_age_days} days — "
                "treated as no data until refreshed.",
            )

    excluded, deprioritized = [], []
    if npa is not None:
        if npa >= policy.npa_exclude_pct:
            excluded.append(f"NPA {_pct(npa)} is at or above the {_pct(policy.npa_exclude_pct)} limit")
        elif npa >= policy.npa_deprioritize_pct:
            deprioritized.append(f"NPA {_pct(npa)} is at or above {_pct(policy.npa_deprioritize_pct)}")
    if overdue is not None:
        if overdue >= policy.overdue_exclude_pct:
            excluded.append(f"overdues {_pct(overdue)} are at or above the {_pct(policy.overdue_exclude_pct)} limit")
        elif overdue >= policy.overdue_deprioritize_pct:
            deprioritized.append(f"overdues {_pct(overdue)} are at or above {_pct(policy.overdue_deprioritize_pct)}")
    if util is not None:
        if util < policy.utilization_exclude_below_pct:
            excluded.append(f"fund utilization {_pct(util)} is below the {_pct(policy.utilization_exclude_below_pct)} minimum")
        elif util < policy.utilization_deprioritize_below_pct:
            deprioritized.append(f"fund utilization {_pct(util)} is below {_pct(policy.utilization_deprioritize_below_pct)}")

    dated = f" (figures as of {as_of})" if as_of else ""
    if excluded:
        return decision(EXCLUDED, "Routed away: " + "; ".join(excluded) + dated + ".")
    if deprioritized:
        return decision(DEPRIORITIZED, "Ranked lower: " + "; ".join(deprioritized) + dated + ".")

    known = []
    if npa is not None:
        known.append(f"NPA {_pct(npa)}")
    if overdue is not None:
        known.append(f"overdues {_pct(overdue)}")
    if util is not None:
        known.append(f"fund utilization {_pct(util)}")
    missing = [name for name, v in (("NPA", npa), ("overdue", overdue), ("utilization", util)) if v is None]
    reason = "Healthy portfolio: " + ", ".join(known) + dated + "."
    if missing:
        reason += f" No {'/'.join(missing)} data on record."
    return decision(ELIGIBLE, reason)


# ── Search ───────────────────────────────────────────────────────────────────

@dataclass
class PartnerMatch:
    partner: Partner
    distance_km: float | None
    routing: RoutingDecision


@dataclass
class PartnerSearchResult:
    partners: list[PartnerMatch] = field(default_factory=list)  # routable, best first
    excluded: list[PartnerMatch] = field(default_factory=list)  # routed away, with reasons
    note: str | None = None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def supports_scheme(scheme_code: str):
    """SQL condition: scheme_code is an element of the eligible_scheme_codes JSON array.

    A plain .contains() on a JSON column compiles to a LIKE substring match
    (so e.g. "MFS" would also match a hypothetical "MFS_PLUS"); json_each
    checks actual array membership.
    """
    codes = func.json_each(Partner.eligible_scheme_codes).table_valued("value")
    return select(codes.c.value).where(codes.c.value == scheme_code).exists()


def _in_district(partner: Partner, district: str) -> bool:
    """Whether the partner is in the named district, by structured field or by address."""
    wanted = district.strip().lower()
    if not wanted:
        return False
    if partner.district and partner.district.strip().lower() == wanted:
        return True
    return bool(partner.address) and re.search(rf"\b{re.escape(wanted)}\b", partner.address.lower()) is not None


def find_nearby_partners(
    db: Session,
    lat: float | None,
    lon: float | None,
    state: str | None,
    district: str | None,
    scheme_code: str | None,
    limit: int = 10,
    policy: RoutingPolicy | None = None,
    today: date | None = None,
) -> PartnerSearchResult:
    policy = policy or RoutingPolicy.from_env()
    has_location = lat is not None and lon is not None

    base = db.query(Partner)
    if scheme_code:
        base = base.filter(supports_scheme(scheme_code))

    def evaluate(partners: list[Partner]) -> list[PartnerMatch]:
        matches = []
        for p in partners:
            distance = None
            if has_location and p.lat is not None and p.lon is not None:
                distance = haversine_km(lat, lon, p.lat, p.lon)
            matches.append(PartnerMatch(p, distance, evaluate_routing(p, policy, today)))
        return matches

    note = None
    if has_location or not state:
        matches = evaluate(base.all())
    else:
        matches = evaluate(base.filter(Partner.state == state).all())
        if not any(m.routing.status != EXCLUDED for m in matches):
            state_had_excluded = bool(matches)
            matches = evaluate(base.all())
            if any(m.routing.status != EXCLUDED for m in matches):
                if state_had_excluded:
                    note = (f"Partners in {state} for this scheme are currently routed away (see below) — "
                            "showing partners from across India instead.")
                else:
                    note = (f"No compatible Channel Partners are listed in {state} yet — "
                            "showing partners from across India instead.")

    def locality_key(m: PartnerMatch):
        distance_rank = m.distance_km if m.distance_km is not None else float("inf")
        if has_location:
            return (distance_rank, m.partner.name)
        district_rank = 0 if district and _in_district(m.partner, district) else 1
        return (district_rank, m.partner.name)

    routable = [m for m in matches if m.routing.status != EXCLUDED]
    routable.sort(key=lambda m: (
        _ROUTING_RANK[m.routing.status],
        _CAPACITY_RANK.get(m.partner.capacity_status, 1),
        *locality_key(m),
    ))
    excluded = sorted((m for m in matches if m.routing.status == EXCLUDED), key=locality_key)

    return PartnerSearchResult(partners=routable[:limit], excluded=excluded[:limit], note=note)


def partner_out(partner: Partner, routing: RoutingDecision, distance_km: float | None = None) -> PartnerOut:
    item = PartnerOut.model_validate(partner)
    item.distance_km = round(distance_km, 1) if distance_km is not None else None
    item.routing_status = routing.status
    item.routing_reason = routing.reason
    item.metrics_is_demo = has_demo_metrics(partner)
    return item
