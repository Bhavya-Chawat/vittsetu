"""Token-protected admin endpoints: partner capacity + portfolio metrics,
scheme/partner CRUD.

MVP auth: a single shared token via the ADMIN_TOKEN env var, not a full user
table — documented as an upgrade path in the transformation plan, appropriate
for a hackathon MVP where the only "admin" role is the team operating a demo
or an NSFDC ops user manually keeping partner capacity current.
"""

import csv
import io
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Header, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from db import get_db
from models import Scheme, Partner
from partner_engine import DEMO_DATA_TAG, RoutingPolicy, evaluate_routing, has_demo_metrics, partner_out
from schemas import CapacityUpdateRequest, PartnerMetricsUpdate, PartnerOut, SchemeOut

# Load .env here rather than relying on some other module having done it first.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

router = APIRouter(prefix="/api/admin", tags=["admin"])

DEFAULT_ADMIN_TOKEN = "vittsetu-admin-dev"


def require_admin(x_admin_token: Optional[str] = Header(default=None)):
    if x_admin_token != os.environ.get("ADMIN_TOKEN", DEFAULT_ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid or missing admin token")


class PartnerCreate(BaseModel):
    name: str
    partner_type: str
    state: Optional[str] = None
    district: Optional[str] = None
    address: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    eligible_scheme_codes: list[str] = []
    source_url: Optional[str] = None


class SchemeUpdate(BaseModel):
    """All fields optional — admin sends only what changed."""
    max_project_cost: Optional[float] = None
    max_financing_pct: Optional[float] = None
    max_loan_amount: Optional[float] = None
    interest_rate_to_beneficiary_pct: Optional[float] = None
    moratorium_min_months: Optional[int] = None
    moratorium_max_months: Optional[int] = None
    repayment_tenure_max_months: Optional[int] = None
    source_url: Optional[str] = None


def _out(partner: Partner, policy: RoutingPolicy | None = None) -> PartnerOut:
    return partner_out(partner, evaluate_routing(partner, policy or RoutingPolicy.from_env()))


@router.get("/partners", response_model=list[PartnerOut], dependencies=[Depends(require_admin)])
def admin_list_partners(db: Session = Depends(get_db)):
    policy = RoutingPolicy.from_env()
    return [_out(p, policy) for p in db.query(Partner).order_by(Partner.id)]


@router.post("/partners", response_model=PartnerOut, dependencies=[Depends(require_admin)])
def admin_create_partner(payload: PartnerCreate, db: Session = Depends(get_db)):
    partner = Partner(**payload.model_dump())
    db.add(partner)
    db.commit()
    db.refresh(partner)
    return _out(partner)


@router.patch("/partners/{partner_id}/capacity", response_model=PartnerOut, dependencies=[Depends(require_admin)])
def admin_update_capacity(partner_id: int, payload: CapacityUpdateRequest, db: Session = Depends(get_db)):
    partner = db.get(Partner, partner_id)
    if not partner:
        raise HTTPException(status_code=404, detail="Partner not found")
    partner.capacity_status = payload.capacity_status
    partner.capacity_status_updated_by = payload.updated_by
    partner.capacity_status_updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(partner)
    return _out(partner)


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


@router.patch("/partners/{partner_id}/metrics", response_model=PartnerOut, dependencies=[Depends(require_admin)])
def admin_update_metrics(partner_id: int, payload: PartnerMetricsUpdate, db: Session = Depends(get_db)):
    """Set a partner's portfolio figures. Omitted fields keep their current
    value; an explicit null clears a figure to "no data"."""
    partner = db.get(Partner, partner_id)
    if not partner:
        raise HTTPException(status_code=404, detail="Partner not found")
    try:
        values = _validated_metrics(partner, payload)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    _apply_metrics(partner, values, payload)
    db.commit()
    db.refresh(partner)
    return _out(partner)


CSV_COLUMNS = ["partner_id", "name", "partner_type", "state", *METRIC_FIELDS, "metrics_as_of_date"]
MAX_CSV_BYTES = 1_000_000


@router.get("/partners/metrics/template.csv", dependencies=[Depends(require_admin)])
def admin_metrics_template(db: Session = Depends(get_db)):
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


@router.post("/partners/metrics/import", dependencies=[Depends(require_admin)])
async def admin_import_metrics(
    file: UploadFile, updated_by: str = "admin", dry_run: bool = False, db: Session = Depends(get_db),
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
            _apply_metrics(partner, values, update)
        db.commit()
    return {
        "dry_run": dry_run,
        "updated": len(planned),
        "unchanged": unchanged,
        "skipped_blank": skipped_blank,
        "partner_ids": [p.id for p, _, _ in planned],
    }


@router.get("/schemes", response_model=list[SchemeOut], dependencies=[Depends(require_admin)])
def admin_list_schemes(db: Session = Depends(get_db)):
    return db.query(Scheme).all()


@router.put("/schemes/{code}", response_model=SchemeOut, dependencies=[Depends(require_admin)])
def admin_update_scheme(code: str, payload: SchemeUpdate, db: Session = Depends(get_db)):
    scheme = db.query(Scheme).filter_by(code=code.upper()).first()
    if not scheme:
        raise HTTPException(status_code=404, detail="Scheme not found")
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(scheme, field, value)
    if updates:
        scheme.last_verified_date = datetime.now(timezone.utc).date().isoformat()
    db.commit()
    db.refresh(scheme)
    return scheme
