"""Admin audit trail: before/after snapshots of every admin change.

Call snapshot() before mutating an entity, mutate, then record(); the entry
is added to the same session, so it commits (or rolls back) with the change.
"""

from datetime import date, datetime

from sqlalchemy.orm import Session

from models import AdminAuditLog, Application, Partner, Scheme

# Fields captured per entity. Timestamps and ids are left out of the diff.
PARTNER_FIELDS = [
    "name", "partner_type", "state", "district", "address", "lat", "lon", "phone", "email",
    "eligible_scheme_codes", "source_url", "capacity_status",
    "fund_utilization_pct", "npa_pct", "overdue_pct", "allocated_funds_inr", "disbursed_funds_inr",
    "metrics_as_of_date", "metrics_updated_by",
]
SCHEME_FIELDS = [
    "name", "income_limit_annual", "min_project_cost", "max_project_cost", "max_financing_pct",
    "max_loan_amount", "interest_rate_to_beneficiary_pct", "rates_by_partner_type",
    "moratorium_min_months", "moratorium_max_months", "repayment_tenure_max_months",
    "moratorium_rules", "tenure_rules", "eligible_partner_types", "source_url", "last_verified_date",
]
APPLICATION_FIELDS = ["status", "partner_id", "scheme_id", "requested_loan_amount"]

_FIELDS = {Partner: PARTNER_FIELDS, Scheme: SCHEME_FIELDS, Application: APPLICATION_FIELDS}


def _jsonable(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, list):
        return list(value)  # copy: JSON columns may be mutated in place later
    if isinstance(value, dict):
        return dict(value)
    return value


def snapshot(entity) -> dict:
    return {f: _jsonable(getattr(entity, f)) for f in _FIELDS[type(entity)]}


def changed_fields(before: dict | None, after: dict | None) -> list[str]:
    before, after = before or {}, after or {}
    return [k for k in sorted(set(before) | set(after)) if before.get(k) != after.get(k)]


def record(db: Session, entity_type: str, entity_id, action: str, actor: str,
           before: dict | None, after: dict | None) -> AdminAuditLog | None:
    """Add an audit entry; skipped when an update changed nothing."""
    if before is not None and after is not None and not changed_fields(before, after):
        return None
    entry = AdminAuditLog(
        entity_type=entity_type, entity_id=str(entity_id), action=action, actor=actor,
        before=before, after=after,
    )
    db.add(entry)
    return entry
