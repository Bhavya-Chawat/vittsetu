"""Deterministic activity classification for business requirements.

The taxonomy itself (categories, labels, keywords, tie-break order) lives in
reference_data/activity_taxonomy.json — this module only loads and applies
it. No LLM: the same description always yields the same category, and the
matched keywords are returned so the UI can show why.
"""

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

TAXONOMY_PATH = Path(__file__).resolve().parent / "reference_data" / "activity_taxonomy.json"


@dataclass(frozen=True)
class ActivityCategory:
    id: str
    label: str
    label_hi: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class Classification:
    category: str | None  # None when nothing matched
    matched_keywords: tuple[str, ...]


@lru_cache(maxsize=1)
def load_taxonomy() -> tuple[tuple[ActivityCategory, ...], tuple[str, ...]]:
    data = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    categories = tuple(
        ActivityCategory(c["id"], c["label"], c["label_hi"], tuple(k.lower() for k in c["keywords"]))
        for c in data["categories"]
    )
    order = tuple(data["tie_break_order"])
    ids = {c.id for c in categories}
    if set(order) != ids:
        raise ValueError("activity_taxonomy.json: tie_break_order must list every category id exactly once")
    return categories, order


def category_ids() -> list[str]:
    return [c.id for c in load_taxonomy()[0]]


def get_category(category_id: str) -> ActivityCategory | None:
    return next((c for c in load_taxonomy()[0] if c.id == category_id), None)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


@lru_cache(maxsize=None)
def _pattern(keyword: str) -> re.Pattern:
    if keyword.isascii():
        # Word boundaries on letters/digits, tolerant of plurals and of
        # hyphen/space variants ("e-rickshaw" / "e rickshaw").
        body = r"[\s-]+".join(re.escape(part) for part in re.split(r"[\s-]+", keyword))
        return re.compile(rf"(?<![a-z0-9]){body}(?:s|es)?(?![a-z0-9])")
    # Devanagari: \b is unreliable around vowel signs, so match as a substring.
    return re.compile(re.escape(keyword))


def classify(text: str | None) -> Classification:
    """Best-matching category for a free-text activity description."""
    if not text or not text.strip():
        return Classification(None, ())
    normalized = _normalize(text)
    categories, order = load_taxonomy()

    best: tuple[int, int, str, tuple[str, ...]] | None = None
    for cat in categories:
        matched = tuple(k for k in cat.keywords if _pattern(k).search(normalized))
        if not matched:
            continue
        score = sum(len(k.split()) for k in matched)
        rank = (-score, order.index(cat.id))
        if best is None or rank < best[:2]:
            best = (*rank, cat.id, matched)
    if best is None:
        return Classification(None, ())
    return Classification(best[2], best[3])
