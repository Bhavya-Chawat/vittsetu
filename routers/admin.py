"""Token-protected admin endpoints: partner CRUD + capacity + portfolio metrics,
scheme edits, geocoding, the audit trail and operational metrics.

Auth: a single shared token (ADMIN_TOKEN), compared in constant time. With
VITTSETU_ENV=production the well-known default token is refused, so a real
deployment can't run with it. Callers may identify themselves with an
X-Admin-User header, which is what the audit log records as the actor.

Every change to a partner, scheme or application status is written to
AdminAuditLog with before/after snapshots (see audit.py), in the same
transaction as the change itself.
"""

import csv
import hmac
import io
import os
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import unquote

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, Header, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

import audit
import geocoding
from db import get_db
from models import AdminAuditLog, Application, ApplicationEvent, Partner, Scheme
from partner_engine import (
    DEMO_DATA_TAG, DEPRIORITIZED, ELIGIBLE, EXCLUDED, NO_DATA, RoutingPolicy, evaluate_routing, has_demo_metrics,
    partner_out,
)
from schemas import (
    AdminMetrics, AuditEntryOut, AuditListResponse, CapacityUpdateRequest, FieldChange, GeocodeRequest,
    GeocodeResponse, PartnerCreate, PartnerListResponse, PartnerMetricsUpdate, PartnerOut, PartnerUpdate,
    SchemeEditResult, SchemeOut, SchemeUpdate,
)

# Load .env here rather than relying on some other module having done it first.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

router = APIRouter(prefix="/api/admin", tags=["admin"])

DEFAULT_ADMIN_TOKEN = "vittsetu-admin-dev"


# ── Auth ─────────────────────────────────────────────────────────────────────

def is_production() -> bool:
    return os.environ.get("VITTSETU_ENV", "").strip().lower() == "production"


def expected_admin_token() -> str | None:
    """The configured token, or None if admin access must be refused."""
    token = os.environ.get("ADMIN_TOKEN") or DEFAULT_ADMIN_TOKEN
    if is_production() and token == DEFAULT_ADMIN_TOKEN:
        return None
    return token


def require_admin(
    x_admin_token: Optional[str] = Header(default=None),
    x_admin_user: Optional[str] = Header(default=None),
) -> str:
    """Validates the admin token; returns the actor name for the audit log."""
    expected = expected_admin_token()
    if expected is None:
        raise HTTPException(
            status_code=503,
            detail="Admin console disabled: VITTSETU_ENV=production requires a non-default ADMIN_TOKEN.",
        )
    if not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid or missing admin token")
    # Percent-encoded by the console, since header values must be ASCII (names may not be).
    actor = unquote(x_admin_user or "").strip()[:100]
    return actor or "admin"


# ── Partners ─────────────────────────────────────────────────────────────────

def _out(partner: Partner, policy: RoutingPolicy | None = None) -> PartnerOut:
    return partner_out(partner, evaluate_routing(partner, policy or RoutingPolicy.from_env()))


def _get_partner(db: Session, partner_id: int) -> Partner:
    partner = db.get(Partner, partner_id)
    if not partner:
        raise HTTPException(status_code=404, detail="Partner not found")
    return partner


def _validate_partner(db: Session, partner: Partner) -> None:
    """Cross-field checks on a partner's final state."""
    if (partner.lat is None) != (partner.lon is None):
        raise HTTPException(status_code=422, detail="Set both latitude and longitude, or neither.")
    known = {code for (code,) in db.query(Scheme.code)}
    unknown = sorted(set(partner.eligible_scheme_codes or []) - known)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown scheme code(s): {', '.join(unknown)}")


@router.get("/partners", response_model=PartnerListResponse)
def admin_list_partners(
    q: Optional[str] = Query(default=None, max_length=100, description="Search name, address, state, district, type"),
    partner_type: Optional[str] = None,
    state: Optional[str] = None,
    routing_status: Optional[Literal["eligible", "deprioritized", "excluded", "no_data"]] = None,
    missing: Optional[Literal["coordinates", "district"]] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    policy = RoutingPolicy.from_env()
    partners = db.query(Partner).order_by(Partner.id).all()
    missing_coordinates = sum(1 for p in partners if p.lat is None or p.lon is None)
    missing_district = sum(1 for p in partners if not p.district)

    rows = [_out(p, policy) for p in partners]
    if q:
        needle = q.strip().lower()
        rows = [r for r in rows if any(needle in (v or "").lower()
                                       for v in (r.name, r.address, r.state, r.district, r.partner_type))]
    if partner_type:
        rows = [r for r in rows if r.partner_type == partner_type]
    if state:
        rows = [r for r in rows if r.state == state]
    if routing_status:
        rows = [r for r in rows if r.routing_status == routing_status]
    if missing == "coordinates":
        rows = [r for r in rows if r.lat is None or r.lon is None]
    elif missing == "district":
        rows = [r for r in rows if not r.district]

    start = (page - 1) * page_size
    return PartnerListResponse(
        items=rows[start:start + page_size], total=len(rows), page=page, page_size=page_size,
        missing_coordinates=missing_coordinates, missing_district=missing_district,
    )


@router.post("/partners", response_model=PartnerOut, status_code=201)
def admin_create_partner(payload: PartnerCreate, db: Session = Depends(get_db), actor: str = Depends(require_admin)):
    partner = Partner(**payload.model_dump(), capacity_status="available")
    _validate_partner(db, partner)
    db.add(partner)
    db.flush()
    audit.record(db, "partner", partner.id, "created", actor, None, audit.snapshot(partner))
    db.commit()
    db.refresh(partner)
    return _out(partner)


@router.patch("/partners/{partner_id}", response_model=PartnerOut)
def admin_update_partner(partner_id: int, payload: PartnerUpdate,
                         db: Session = Depends(get_db), actor: str = Depends(require_admin)):
    """Edit partner details. Omitted fields are unchanged; explicit null clears one.
    Capacity and metrics have their own endpoints."""
    partner = _get_partner(db, partner_id)
    updates = payload.model_dump(exclude_unset=True)
    for required in ("name", "partner_type"):
        if required in updates and updates[required] is None:
            raise HTTPException(status_code=422, detail=f"{required} cannot be cleared")
    if "eligible_scheme_codes" in updates and updates["eligible_scheme_codes"] is None:
        updates["eligible_scheme_codes"] = []

    before = audit.snapshot(partner)
    for field, value in updates.items():
        setattr(partner, field, value)
    _validate_partner(db, partner)
    audit.record(db, "partner", partner.id, "updated", actor, before, audit.snapshot(partner))
    db.commit()
    db.refresh(partner)
    return _out(partner)


@router.patch("/partners/{partner_id}/capacity", response_model=PartnerOut)
def admin_update_capacity(partner_id: int, payload: CapacityUpdateRequest,
                          db: Session = Depends(get_db), actor: str = Depends(require_admin)):
    partner = _get_partner(db, partner_id)
    before = audit.snapshot(partner)
    partner.capacity_status = payload.capacity_status
    partner.capacity_status_updated_by = payload.updated_by
    partner.capacity_status_updated_at = datetime.now(timezone.utc)
    audit.record(db, "partner", partner.id, "capacity_changed", actor, before, audit.snapshot(partner))
    db.commit()
    db.refresh(partner)
    return _out(partner)


@router.post("/geocode", response_model=GeocodeResponse)
def admin_geocode(payload: GeocodeRequest, actor: str = Depends(require_admin)):
    """Look up coordinates for an address via OpenStreetMap Nominatim (rate-limited,
    see geocoding.py). Doesn't save anything — the admin reviews, then saves the partner."""
    query = payload.address.strip()
    if payload.state and payload.state.lower() not in query.lower():
        query = f"{query}, {payload.state}"
    try:
        result = geocoding.geocode(query)
    except geocoding.GeocodingError as e:
        raise HTTPException(status_code=502, detail=f"Geocoding service unavailable: {e}")
    if result is None:
        raise HTTPException(status_code=404, detail="No match found for that address — try a simpler address or the PIN code.")
    return GeocodeResponse(lat=result.lat, lon=result.lon, display_name=result.display_name, query=query)


# ── Portfolio metrics (NPA / overdue / fund utilization) ─────────────────────

METRIC_FIELDS = ["fund_utilization_pct", "npa_pct", "overdue_pct", "allocated_funds_inr", "disbursed_funds_inr"]


def _validated_metrics(partner: Partner, update: PartnerMetricsUpdate) -> dict:
    """The partner's full metric set after applying `update` (fields it omits keep
    their current value). Raises ValueError on an inconsistent result."""
    if update.updated_by.strip().upper() == DEMO_DATA_TAG:
        raise ValueError(f'updated_by "{DEMO_DATA_TAG}" is reserved for scripts/seed_demo_metrics.py')

    # Real figures replace demo ones wholesale, so no leftover demo value
    # ends up relabelled as admin-entered.
    base = {f: None if has_demo_metrics(partner) else getattr(partner, f) for f in METRIC_FIELDS}
    values = {**base, **update.model_dump(include=set(METRIC_FIELDS), exclude_unset=True)}

    allocated, disbursed = values["allocated_funds_inr"], values["disbursed_funds_inr"]
    if allocated is not None and disbursed is not None and disbursed > allocated:
        raise ValueError("disbursed_funds_inr cannot exceed allocated_funds_inr")
    return values


def _apply_metrics(partner: Partner, values: dict, update: PartnerMetricsUpdate) -> None:
    for f, v in values.items():
        setattr(partner, f, v)
    partner.metrics_as_of_date = update.metrics_as_of_date.isoformat()
    partner.metrics_updated_by = update.updated_by.strip()


@router.patch("/partners/{partner_id}/metrics", response_model=PartnerOut)
def admin_update_metrics(partner_id: int, payload: PartnerMetricsUpdate,
                         db: Session = Depends(get_db), actor: str = Depends(require_admin)):
    """Set a partner's portfolio figures. Omitted fields keep their current
    value; an explicit null clears a figure to "no data"."""
    partner = _get_partner(db, partner_id)
    try:
        values = _validated_metrics(partner, payload)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    before = audit.snapshot(partner)
    _apply_metrics(partner, values, payload)
    audit.record(db, "partner", partner.id, "metrics_updated", actor, before, audit.snapshot(partner))
    db.commit()
    db.refresh(partner)
    return _out(partner)


CSV_COLUMNS = ["partner_id", "name", "partner_type", "state", *METRIC_FIELDS, "metrics_as_of_date"]
MAX_CSV_BYTES = 1_000_000


@router.get("/partners/metrics/template.csv")
def admin_metrics_template(db: Session = Depends(get_db), actor: str = Depends(require_admin)):
    """Every partner with its current real figures, ready to edit and re-import.
    Demo figures are left blank so they can't be re-imported as real data."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    for p in db.query(Partner).order_by(Partner.id):
        demo = has_demo_metrics(p)
        writer.writerow([
            p.id, p.name, p.partner_type, p.state or "",
            *["" if demo or getattr(p, f) is None else getattr(p, f) for f in METRIC_FIELDS],
            "" if demo else (p.metrics_as_of_date or ""),
        ])
    return Response(
        content=buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="partner_metrics_template.csv"'},
    )


def _parse_number(raw: str) -> float:
    """Accept spreadsheet-style numbers: "1,00,000", "₹ 5000", "12.5%"."""
    return float(re.sub(r"[,\s₹%]", "", raw))


@router.post("/partners/metrics/import")
async def admin_import_metrics(
    file: UploadFile, updated_by: str = "admin", dry_run: bool = False,
    db: Session = Depends(get_db), actor: str = Depends(require_admin),
):
    """Bulk-set portfolio figures from a CSV (see template.csv).

    Required columns: partner_id, metrics_as_of_date. Metric columns that are
    absent leave those figures unchanged; an empty cell clears the figure to
    "no data". Rows with no date and no figures are skipped. All-or-nothing:
    if any row is invalid, nothing is written and every error is returned.
    """
    raw = await file.read(MAX_CSV_BYTES + 1)
    if len(raw) > MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail="CSV larger than 1 MB")
    try:
        text = raw.decode("utf-8-sig")  # tolerate Excel's BOM
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded")

    reader = csv.DictReader(io.StringIO(text))
    header = [h.strip() for h in (reader.fieldnames or [])]
    missing = {"partner_id", "metrics_as_of_date"} - set(header)
    if missing:
        raise HTTPException(status_code=400, detail=f"CSV is missing required column(s): {', '.join(sorted(missing))}")
    metric_cols = [f for f in METRIC_FIELDS if f in header]

    errors: list[dict] = []
    planned: list[tuple[Partner, dict, PartnerMetricsUpdate]] = []
    skipped_blank = unchanged = 0
    seen_ids: set[int] = set()

    for line_no, row in enumerate(reader, start=2):  # line 1 is the header
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        as_of = row.get("metrics_as_of_date", "")
        if not as_of and not any(row.get(c) for c in metric_cols):
            skipped_blank += 1
            continue
        try:
            partner_id = int(row.get("partner_id", ""))
        except ValueError:
            errors.append({"line": line_no, "error": f"invalid partner_id {row.get('partner_id')!r}"})
            continue
        if partner_id in seen_ids:
            errors.append({"line": line_no, "error": f"partner_id {partner_id} appears more than once"})
            continue
        seen_ids.add(partner_id)
        partner = db.get(Partner, partner_id)
        if not partner:
            errors.append({"line": line_no, "error": f"no partner with id {partner_id}"})
            continue
        try:
            fields = {c: (_parse_number(row[c]) if row[c] else None) for c in metric_cols}
            update = PartnerMetricsUpdate(**fields, metrics_as_of_date=as_of or None, updated_by=updated_by)
            values = _validated_metrics(partner, update)
        except ValidationError as e:
            errors.append({"line": line_no, "error": "; ".join(
                f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()
            )})
            continue
        except ValueError as e:  # float() parse errors and consistency checks
            errors.append({"line": line_no, "error": str(e)})
            continue

        current = {f: getattr(partner, f) for f in METRIC_FIELDS}
        if (values == current and partner.metrics_as_of_date == update.metrics_as_of_date.isoformat()
                and not has_demo_metrics(partner)):
            unchanged += 1
            continue
        planned.append((partner, values, update))

    if errors:
        raise HTTPException(status_code=422, detail={"message": "No changes applied — fix these rows.", "errors": errors})

    if not dry_run:
        for partner, values, update in planned:
            before = audit.snapshot(partner)
            _apply_metrics(partner, values, update)
            audit.record(db, "partner", partner.id, "metrics_imported", actor, before, audit.snapshot(partner))
        db.commit()
    return {
        "dry_run": dry_run,
        "updated": len(planned),
        "unchanged": unchanged,
        "skipped_blank": skipped_blank,
        "partner_ids": [p.id for p, _, _ in planned],
    }


# ── Schemes ──────────────────────────────────────────────────────────────────

# Scheme columns that are NOT NULL — an edit may change them but never clear them.
REQUIRED_SCHEME_FIELDS = {
    "max_project_cost", "max_financing_pct", "max_loan_amount",
    "interest_rate_to_beneficiary_pct", "repayment_tenure_max_months",
}

@router.get("/schemes", response_model=list[SchemeOut])
def admin_list_schemes(db: Session = Depends(get_db), actor: str = Depends(require_admin)):
    return db.query(Scheme).order_by(Scheme.id).all()


@router.put("/schemes/{code}", response_model=SchemeEditResult)
def admin_update_scheme(code: str, payload: SchemeUpdate, dry_run: bool = False,
                        db: Session = Depends(get_db), actor: str = Depends(require_admin)):
    """Edit a scheme's figures, citing the source of the change (source_url is
    mandatory). With dry_run=true, returns the field-by-field diff without saving —
    the console shows it for confirmation first."""
    scheme = db.query(Scheme).filter_by(code=code.upper()).first()
    if not scheme:
        raise HTTPException(status_code=404, detail="Scheme not found")

    updates = payload.model_dump(exclude_unset=True)
    cleared = sorted(f for f in REQUIRED_SCHEME_FIELDS if f in updates and updates[f] is None)
    if cleared:
        raise HTTPException(status_code=422, detail=f"Cannot clear required field(s): {', '.join(cleared)}")
    if "rates_by_partner_type" in updates and updates["rates_by_partner_type"]:
        unknown = sorted(set(updates["rates_by_partner_type"]) - set(scheme.eligible_partner_types or []))
        if unknown:
            raise HTTPException(status_code=422, detail=f"Not a partner type for this scheme: {', '.join(unknown)}")

    before = audit.snapshot(scheme)
    after = {**before, **updates}
    min_cost, max_cost = after["min_project_cost"], after["max_project_cost"]
    if min_cost is not None and min_cost >= max_cost:
        raise HTTPException(status_code=422, detail="min_project_cost must be below max_project_cost")
    if after["max_loan_amount"] > max_cost:
        raise HTTPException(status_code=422, detail="max_loan_amount cannot exceed max_project_cost")
    mor_min, mor_max = after["moratorium_min_months"], after["moratorium_max_months"]
    if mor_min is not None and mor_max is not None and mor_min > mor_max:
        raise HTTPException(status_code=422, detail="moratorium_min_months cannot exceed moratorium_max_months")

    changes = [FieldChange(field=f, before=before.get(f), after=after.get(f))
               for f in audit.changed_fields(before, after)]
    if dry_run or not changes:
        return SchemeEditResult(scheme=SchemeOut.model_validate(scheme), changes=changes, applied=False)

    for field, value in updates.items():
        setattr(scheme, field, value)
    scheme.last_verified_date = datetime.now(timezone.utc).date().isoformat()
    audit.record(db, "scheme", scheme.code, "updated", actor, before, audit.snapshot(scheme))
    db.commit()
    db.refresh(scheme)
    return SchemeEditResult(scheme=SchemeOut.model_validate(scheme), changes=changes, applied=True)


# ── Audit log ────────────────────────────────────────────────────────────────

@router.get("/audit", response_model=AuditListResponse)
def admin_audit_log(
    entity_type: Optional[Literal["partner", "scheme", "application"]] = None,
    entity_id: Optional[str] = Query(default=None, max_length=40),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    query = db.query(AdminAuditLog)
    if entity_type:
        query = query.filter(AdminAuditLog.entity_type == entity_type)
    if entity_id:
        query = query.filter(AdminAuditLog.entity_id == entity_id.strip())
    total = query.count()
    entries = query.order_by(AdminAuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return AuditListResponse(
        items=[AuditEntryOut(
            id=e.id, entity_type=e.entity_type, entity_id=e.entity_id, action=e.action, actor=e.actor,
            before=e.before, after=e.after, changed_fields=audit.changed_fields(e.before, e.after),
            created_at=e.created_at,
        ) for e in entries],
        total=total, page=page, page_size=page_size,
    )


# ── Operational metrics ──────────────────────────────────────────────────────

APPLICATION_STATUSES = [
    "routed", "acknowledged_by_partner", "handed_off_to_pmsuraj", "sanctioned", "disbursed", "rejected",
]


@router.get("/metrics", response_model=AdminMetrics)
def admin_metrics(db: Session = Depends(get_db), actor: str = Depends(require_admin)):
    applications = db.query(Application).filter(Application.reference.isnot(None)).all()
    by_status = {s: 0 for s in APPLICATION_STATUSES}
    for a in applications:
        by_status[a.status] = by_status.get(a.status, 0) + 1

    # Routed → disbursed: from the creation event to the event that set "disbursed".
    days = []
    for a in (a for a in applications if a.status == "disbursed"):
        disbursed_at = (db.query(ApplicationEvent.created_at)
                        .filter_by(application_id=a.id, to_status="disbursed")
                        .order_by(ApplicationEvent.id.desc()).scalar())
        if disbursed_at and a.created_at:
            days.append((disbursed_at - a.created_at).total_seconds() / 86400)

    policy = RoutingPolicy.from_env()
    partners = db.query(Partner).all()
    by_routing = {s: 0 for s in (ELIGIBLE, NO_DATA, DEPRIORITIZED, EXCLUDED)}
    for p in partners:
        by_routing[evaluate_routing(p, policy).status] += 1

    return AdminMetrics(
        applications_total=len(applications),
        applications_by_status=by_status,
        disbursed_count=len(days),
        median_days_routed_to_disbursed=round(statistics.median(days), 1) if days else None,
        partners_total=len(partners),
        partners_by_routing_status=by_routing,
        partners_with_real_metrics=sum(1 for p in partners if p.metrics_updated_by not in (None, DEMO_DATA_TAG)),
        partners_with_demo_metrics=sum(1 for p in partners if has_demo_metrics(p)),
        partners_missing_coordinates=sum(1 for p in partners if p.lat is None or p.lon is None),
        partners_missing_district=sum(1 for p in partners if not p.district),
    )
