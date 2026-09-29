"""Deterministic eligibility + scheme recommendation rules.

No LLM involvement anywhere in this module — every decision traces to a
scheme's stored, source-cited fields (scripts/seed_schemes.py), the activity
taxonomy data (reference_data/activity_taxonomy.json), and the partner
routing policy (partner_engine.py).

Best fit: among the schemes an applicant matches, prefer one with a routable
Channel Partner near them, then the lowest effective interest rate (the rate
via the partner types actually available to them), then the larger loan for
this cost, then the lower total interest. Every other match gets its
trade-offs spelled out against the best fit.
"""

import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

import activity_taxonomy
from financial_engine import (
    LoanContext, calculate_loan, max_eligible_loan, rate_options, resolve_moratorium, resolve_tenure,
)
from models import Scheme
from partner_engine import find_nearby_partners
from schemas import (
    ActivityOut, ApplicantProfile, BestFit, BusinessRequirement, EducationRequirement, PartnerAvailability,
    RecommendRequest, RecommendResponse, SchemeComparison, SchemeMatch,
)

# NSFDC's general target-group ceiling (nsfdc.nic.in/scheme). Used only for a
# scheme whose own income_limit_annual is not set.
GENERAL_INCOME_LIMIT = 500_000

# With a device location, a routable partner within this distance counts as "near you".
NEARBY_KM = 100

_AVAILABILITY_TIER = {"local": 0, "unspecified": 0, "elsewhere": 1, "none": 2}


def _inr(value: float) -> str:
    return f"₹{value:,.0f}"


def _pct(value: float) -> str:
    return f"{value:g}%"


def income_limit(scheme: Scheme) -> float:
    return scheme.income_limit_annual if scheme.income_limit_annual is not None else GENERAL_INCOME_LIMIT


def candidate_schemes(db: Session, purpose: str) -> list[Scheme]:
    query = db.query(Scheme)
    if purpose == "education":
        query = query.filter(Scheme.scheme_type == "education_loan")
    else:
        query = query.filter(Scheme.scheme_type != "education_loan")
    return query.order_by(Scheme.id).all()


# ── Eligibility ──────────────────────────────────────────────────────────────

def check_eligibility(profile: ApplicantProfile, schemes: list[Scheme]) -> tuple[bool, list[str]]:
    """Baseline eligibility for any of `schemes` (those for the applicant's purpose).
    Per-scheme income ceilings are applied again when matching."""
    reasons: list[str] = []
    eligible = True

    if not profile.is_sc_category:
        eligible = False
        reasons.append(
            "NSFDC schemes are for persons belonging to the Scheduled Caste (SC) "
            "category. Your Channel Partner will verify your SC certificate at "
            "the application stage."
        )
    else:
        reasons.append("SC category self-declaration recorded.")

    limits = sorted({income_limit(s) for s in schemes}) or [GENERAL_INCOME_LIMIT]
    highest = limits[-1]
    income = profile.annual_family_income
    if income > highest:
        eligible = False
        reasons.append(
            f"Annual family income of {_inr(income)} exceeds the {_inr(highest)} ceiling of "
            f"NSFDC's {profile.purpose} schemes."
        )
    elif len(limits) > 1 and income > limits[0]:
        reasons.append(
            f"Annual family income of {_inr(income)} is within the highest ceiling ({_inr(highest)}); "
            "some schemes have lower ceilings and are checked individually."
        )
    else:
        reasons.append(f"Annual family income of {_inr(income)} is within the {_inr(highest)} ceiling.")

    return eligible, reasons


def _income_rejection(scheme: Scheme, income: float) -> str | None:
    limit = income_limit(scheme)
    if income > limit:
        return f"Annual family income of {_inr(income)} exceeds this scheme's {_inr(limit)} ceiling."
    return None


# ── Activity ─────────────────────────────────────────────────────────────────

def resolve_activity(requirement: BusinessRequirement) -> ActivityOut:
    if requirement.activity_category:
        cat = activity_taxonomy.get_category(requirement.activity_category)
        return ActivityOut(category=cat.id, label=cat.label, source="user_confirmed")
    result = activity_taxonomy.classify(requirement.project_type)
    if result.category is None:
        return ActivityOut(category=None, label=None, source="unclassified")
    cat = activity_taxonomy.get_category(result.category)
    return ActivityOut(category=cat.id, label=cat.label, source="keyword_match",
                       matched_keywords=list(result.matched_keywords))


# ── Education course matching ────────────────────────────────────────────────

# Words that say nothing about which course it is.
_GENERIC_WORDS = {
    "in", "of", "and", "the", "for", "a", "an", "to", "with", "from", "course", "courses", "degree",
    "study", "studies", "program", "programme", "diploma", "bachelor", "bachelors", "master", "masters",
    "higher", "education", "recognized", "institutions", "leading",
}


def _course_tokens(text: str) -> set[str]:
    text = text.lower().replace(".", "")  # "B.Tech" → "btech", "M.Sc" → "msc"
    return {t for t in re.findall(r"[a-z0-9]+", text) if len(t) >= 2 and t not in _GENERIC_WORDS}


def match_course(course_name: str, courses: list[str]) -> str | None:
    """Best-matching recognized course, weighting rarer tokens higher; ties go to the first listed."""
    wanted = _course_tokens(course_name)
    if not wanted:
        return None
    course_tokens = [_course_tokens(c) for c in courses]
    doc_freq: dict[str, int] = {}
    for tokens in course_tokens:
        for t in tokens:
            doc_freq[t] = doc_freq.get(t, 0) + 1
    best, best_score = None, 0.0
    for course, tokens in zip(courses, course_tokens):
        score = sum(1 / doc_freq[t] for t in wanted & tokens)
        if score > best_score:
            best, best_score = course, score
    return best


# ── Partner availability ─────────────────────────────────────────────────────

@dataclass
class _Availability:
    out: PartnerAvailability
    partner_types: set[str]


def _availability(db: Session, scheme: Scheme, profile: ApplicantProfile,
                  lat: float | None, lon: float | None) -> _Availability:
    result = find_nearby_partners(db, lat, lon, profile.state, profile.district, scheme.code, limit=10_000)
    routable = result.partners
    types = {m.partner.partner_type for m in routable}
    n = len(routable)
    if not routable:
        return _Availability(PartnerAvailability(
            level="none", routable_partner_count=0,
            summary="No Channel Partner that can currently take applications is listed for this scheme.",
        ), types)

    if lat is not None and lon is not None:
        with_distance = sorted((m for m in routable if m.distance_km is not None), key=lambda m: m.distance_km)
        if with_distance:
            nearest = with_distance[0]
            level = "local" if nearest.distance_km <= NEARBY_KM else "elsewhere"
            return _Availability(PartnerAvailability(
                level=level, routable_partner_count=n,
                nearest_partner_name=nearest.partner.name, nearest_distance_km=round(nearest.distance_km, 1),
                summary=f"Nearest routable partner: {nearest.partner.name}, about {nearest.distance_km:,.0f} km away.",
            ), types)
    if profile.state:
        if result.note:  # state had none; results fell back to all of India
            return _Availability(PartnerAvailability(
                level="elsewhere", routable_partner_count=n,
                summary=f"No routable partner in {profile.state}; {n} elsewhere in India.",
            ), types)
        return _Availability(PartnerAvailability(
            level="local", routable_partner_count=n,
            summary=f"{n} routable partner{'s' if n != 1 else ''} in {profile.state}.",
        ), types)
    return _Availability(PartnerAvailability(
        level="unspecified", routable_partner_count=n,
        summary=f"{n} routable partner{'s' if n != 1 else ''} across India — add your state to check local availability.",
    ), types)


def _effective_rate(scheme: Scheme, available_types: set[str]) -> tuple[float, str | None]:
    """Lowest rate via a partner type the applicant can actually reach; else the lowest overall.
    The partner type is only named when the scheme's rate actually varies by partner type."""
    options = rate_options(scheme)
    if len(set(options.values())) <= 1:
        return next(iter(options.values()), scheme.interest_rate_to_beneficiary_pct), None
    reachable = {pt: r for pt, r in options.items() if pt in available_types} or options
    partner_type = min(reachable, key=lambda pt: (reachable[pt], pt))
    return reachable[partner_type], partner_type


def _rate_display(scheme: Scheme) -> str:
    rates = sorted(set(rate_options(scheme).values())) or [scheme.interest_rate_to_beneficiary_pct]
    return _pct(rates[0]) if len(rates) == 1 else f"{rates[0]:g}–{rates[-1]:g}%"


# ── Comparison + best fit ────────────────────────────────────────────────────

def _compare(db: Session, scheme: Scheme, cost: float, ctx: LoanContext, profile: ApplicantProfile,
             lat: float | None, lon: float | None) -> SchemeComparison:
    availability = _availability(db, scheme, profile, lat, lon)
    rate, rate_type = _effective_rate(scheme, availability.partner_types)
    moratorium, moratorium_basis = resolve_moratorium(scheme, ctx)
    tenure_months, includes, tenure_basis = resolve_tenure(scheme, ctx)

    instalment = interest = None
    try:
        illustration = calculate_loan(scheme, cost, context=ctx, partner_type=rate_type)
        instalment, interest = illustration.instalment_amount, illustration.total_interest
    except ValueError:
        pass  # e.g. ELS without a course duration — the table shows the rule instead

    return SchemeComparison(
        code=scheme.code, name=scheme.name, is_best_fit=False,
        rate_display=_rate_display(scheme), effective_rate_pct=rate, effective_rate_partner_type=rate_type,
        loan_for_this_cost=max_eligible_loan(scheme, cost), max_loan_amount=scheme.max_loan_amount,
        moratorium_months=moratorium, moratorium_basis=moratorium_basis,
        tenure_max_months=tenure_months if includes else tenure_months + (moratorium or 0),
        tenure_basis=tenure_basis, partner_types=list(scheme.eligible_partner_types or []),
        availability=availability.out, quarterly_instalment=instalment, total_interest=interest,
    )


def _best_fit_key(row: SchemeComparison):
    return (
        _AVAILABILITY_TIER[row.availability.level],
        row.effective_rate_pct,
        -row.loan_for_this_cost,
        row.total_interest if row.total_interest is not None else float("inf"),
        row.code,
    )


def _via(row: SchemeComparison) -> str:
    return f" via {row.effective_rate_partner_type}" if row.effective_rate_partner_type else ""


def _rate_sentence_end(row: SchemeComparison) -> str:
    """"6.5% p.a." or "15% p.a. via Small Finance Bank." — one closing period either way."""
    via = _via(row)
    return f"{_pct(row.effective_rate_pct)} p.a.{via}{'.' if via else ''}"


def _trade_offs(alt: SchemeComparison, best: SchemeComparison) -> list[str]:
    notes = []
    if alt.effective_rate_pct > best.effective_rate_pct:
        notes.append(f"Higher interest: {_pct(alt.effective_rate_pct)}{_via(alt)} vs "
                     f"{_pct(best.effective_rate_pct)} p.a.")
    elif alt.effective_rate_pct < best.effective_rate_pct:
        notes.append(f"Lower interest ({_pct(alt.effective_rate_pct)}{_via(alt)} vs "
                     f"{_pct(best.effective_rate_pct)} p.a.), but see partner availability.")
    if alt.rate_display != _pct(alt.effective_rate_pct):
        notes.append(f"Rate depends on the partner: {alt.rate_display} by partner type.")
    if alt.total_interest is not None and best.total_interest is not None:
        diff = alt.total_interest - best.total_interest
        if abs(diff) >= 1:
            notes.append(f"{_inr(abs(diff))} {'more' if diff > 0 else 'less'} interest over the full tenure "
                         f"(at the maximum loan and tenure).")
    if alt.tenure_max_months != best.tenure_max_months and alt.quarterly_instalment and best.quarterly_instalment:
        longer = alt.tenure_max_months > best.tenure_max_months
        notes.append(
            f"{'Longer' if longer else 'Shorter'} repayment ({alt.tenure_max_months} vs {best.tenure_max_months} "
            f"months), so a {'smaller' if longer else 'bigger'} quarterly instalment: "
            f"{_inr(alt.quarterly_instalment)} vs {_inr(best.quarterly_instalment)}."
        )
    if alt.moratorium_months is not None and best.moratorium_months is not None \
            and alt.moratorium_months != best.moratorium_months:
        notes.append(f"{'Longer' if alt.moratorium_months > best.moratorium_months else 'Shorter'} moratorium: "
                     f"{alt.moratorium_months} vs {best.moratorium_months} months.")
    if round(alt.loan_for_this_cost) != round(best.loan_for_this_cost):
        notes.append(f"Lends up to {_inr(alt.loan_for_this_cost)} for this project vs "
                     f"{_inr(best.loan_for_this_cost)}.")
    notes.append(f"Channelled via {', '.join(alt.partner_types)}. {alt.availability.summary}")
    return notes


def _best_fit(rows: list[SchemeComparison], extra_reasons: dict[str, list[str]]) -> BestFit | None:
    if not rows:
        return None
    ranked = sorted(rows, key=_best_fit_key)
    best = ranked[0]
    best.is_best_fit = True

    reasons = []
    cheapest = min(rows, key=lambda r: (r.effective_rate_pct, r.code))
    if len(rows) == 1:
        reasons.append(f"The only scheme that matches: {_rate_sentence_end(best)}")
    elif cheapest.code == best.code:
        reasons.append(f"Lowest effective interest among the {len(rows)} matching schemes: "
                       f"{_rate_sentence_end(best)}")
    else:
        why_not = {
            "none": "has no Channel Partner that can currently take applications",
            "elsewhere": "has no routable partner near you",
        }.get(cheapest.availability.level, "is less available to you")
        reasons.append(
            f"{cheapest.name} is cheaper ({_pct(cheapest.effective_rate_pct)}) but {why_not}, so "
            f"{best.name} ({_pct(best.effective_rate_pct)}{_via(best)}) is the best option you can reach."
        )
    reasons.append(best.availability.summary)
    if best.moratorium_months is not None:
        months_phrase = f"{best.moratorium_months}-month moratorium"
        moratorium = (best.moratorium_basis[0].upper() + best.moratorium_basis[1:]
                      if months_phrase in best.moratorium_basis
                      else f"{months_phrase} ({best.moratorium_basis})")
        reasons.append(f"{moratorium}; repay within {best.tenure_max_months} months of disbursement.")
    else:
        reasons.append(f"Moratorium: {best.moratorium_basis}.")
    reasons += extra_reasons.get(best.code, [])

    return BestFit(
        scheme_code=best.code, scheme_name=best.name,
        effective_rate_pct=best.effective_rate_pct, effective_rate_partner_type=best.effective_rate_partner_type,
        reasons=reasons,
        alternatives={r.code: _trade_offs(r, best) for r in ranked[1:]},
    )


# ── Recommenders ─────────────────────────────────────────────────────────────

def _business(db: Session, req: RecommendRequest, schemes: list[Scheme]):
    requirement = req.business
    cost = requirement.estimated_cost
    activity = resolve_activity(requirement)
    ctx = LoanContext(activity_category=activity.category)
    matched: list[tuple[Scheme, list[str]]] = []
    rejected: list[tuple[Scheme, list[str]]] = []

    for scheme in schemes:
        reasons: list[str] = []
        income_problem = _income_rejection(scheme, req.profile.annual_family_income)
        fits_min = scheme.min_project_cost is None or cost >= scheme.min_project_cost
        fits_max = cost <= scheme.max_project_cost
        if income_problem or not (fits_min and fits_max):
            if income_problem:
                reasons.append(income_problem)
            if not fits_min:
                reasons.append(f"Project cost {_inr(cost)} is below this scheme's minimum "
                               f"(more than {_inr(scheme.min_project_cost - 0.01)}).")
            if not fits_max:
                reasons.append(f"Project cost {_inr(cost)} exceeds this scheme's maximum {_inr(scheme.max_project_cost)}.")
            rejected.append((scheme, reasons))
            continue

        loan = max_eligible_loan(scheme, cost)
        reasons.append(f"Project cost {_inr(cost)} fits this scheme's band (up to {_inr(scheme.max_project_cost)}).")
        reasons.append(f"Financing up to {scheme.max_financing_pct:g}% — {_inr(loan)} for this project — at "
                       f"{_rate_display(scheme)} p.a. via {', '.join(scheme.eligible_partner_types)}.")
        months, basis = resolve_moratorium(scheme, ctx)
        reasons.append(f"Moratorium: {months} month(s) — {basis}.")
        matched.append((scheme, reasons))

    rows = [_compare(db, s, cost, ctx, req.profile, req.lat, req.lon) for s, _ in matched]
    best = _best_fit(rows, {})
    return matched, rejected, activity, best, rows


def _education(db: Session, req: RecommendRequest, schemes: list[Scheme]):
    requirement = req.education
    ctx = LoanContext(repayment_started=requirement.repayment_started,
                      course_duration_months=requirement.course_duration_months)
    matched: list[tuple[Scheme, list[str], str | None]] = []
    rejected: list[tuple[Scheme, list[str], str | None]] = []
    extra: dict[str, list[str]] = {}

    for scheme in schemes:
        income_problem = _income_rejection(scheme, req.profile.annual_family_income)
        if income_problem:
            rejected.append((scheme, [income_problem], None))
            continue
        if requirement.course_fee <= 0:
            rejected.append((scheme, ["Course fee must be greater than zero."], None))
            continue

        loan = max_eligible_loan(scheme, requirement.course_fee)
        reasons = [f"Eligible for up to {_inr(loan)} ({scheme.max_financing_pct:g}% of the course fee, "
                   f"capped at {_inr(scheme.max_loan_amount)}) at {_rate_display(scheme)} p.a."]

        course = match_course(requirement.course_name, (scheme.education_criteria or {}).get("courses", []))
        if course:
            reasons.append(f"'{requirement.course_name}' matches NSFDC's recognized course: {course}.")
            extra[scheme.code] = [f"Recognized course: {course}."]
        else:
            reasons.append("Course name not automatically matched to NSFDC's recognized list — ask your "
                           "Channel Partner to confirm it qualifies as a recognized professional/technical "
                           "course before applying.")

        months, basis = resolve_moratorium(scheme, ctx)
        tenure, _, tenure_basis = resolve_tenure(scheme, ctx)
        if months is None:
            reasons.append(f"Moratorium: {basis} — add your course duration to calculate it.")
        else:
            reasons.append(f"Moratorium: {months} months — {basis}.")
        reasons.append(f"Repayment: {tenure_basis}.")
        matched.append((scheme, reasons, course))

    rows = [_compare(db, s, requirement.course_fee, ctx, req.profile, req.lat, req.lon) for s, _, _ in matched]
    best = _best_fit(rows, extra)
    return matched, rejected, best, rows


def recommend(db: Session, req: RecommendRequest) -> RecommendResponse:
    """Raises ValueError if the requirement for the profile's purpose is missing."""
    purpose = req.profile.purpose
    schemes = candidate_schemes(db, purpose)
    eligible, eligibility_reasons = check_eligibility(req.profile, schemes)
    if not eligible:
        return RecommendResponse(eligible=False, eligibility_reasons=eligibility_reasons, matched=[], rejected=[])

    if purpose == "education":
        if not req.education:
            raise ValueError("education requirement is required for purpose=education")
        matched, rejected, best, rows = _education(db, req, schemes)
        return RecommendResponse(
            eligible=True, eligibility_reasons=eligibility_reasons,
            matched=[SchemeMatch(scheme=s, reasons=r, matched_course=c) for s, r, c in matched],
            rejected=[SchemeMatch(scheme=s, reasons=r) for s, r, _ in rejected],
            best_fit=best, comparison=_best_first(rows),
        )

    if not req.business:
        raise ValueError("business requirement is required for purpose=business")
    matched, rejected, activity, best, rows = _business(db, req, schemes)
    return RecommendResponse(
        eligible=True, eligibility_reasons=eligibility_reasons,
        matched=_order_matches([SchemeMatch(scheme=s, reasons=r) for s, r in matched], rows),
        rejected=[SchemeMatch(scheme=s, reasons=r) for s, r in rejected],
        activity=activity, best_fit=best, comparison=_best_first(rows),
    )


def _best_first(rows: list[SchemeComparison]) -> list[SchemeComparison]:
    return sorted(rows, key=_best_fit_key)


def _order_matches(matches: list[SchemeMatch], rows: list[SchemeComparison]) -> list[SchemeMatch]:
    order = {r.code: i for i, r in enumerate(_best_first(rows))}
    return sorted(matches, key=lambda m: order[m.scheme.code])
