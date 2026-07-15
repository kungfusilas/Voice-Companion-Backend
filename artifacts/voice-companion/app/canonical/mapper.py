"""Map a nested `canonical` extraction object to an engine Candidate.

The extraction LLM emits, per fact, a `canonical` sub-object alongside the
legacy category/fact/sensitivity fields. This mapper is the ONLY place that
turns that raw object into a Candidate; a missing/invalid/partial object
yields None (the fact is 'unmapped' and only the legacy path stores it).
"""
from __future__ import annotations

from datetime import date

from app.canonical import registry
from app.canonical.models import Candidate, CONFIRMATION_STATUSES


def _parse_date(v) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return None


def map_canonical(obj, sensitivity: str = "none", now: date | None = None) -> Candidate | None:
    if not isinstance(obj, dict):
        return None
    predicate = obj.get("predicate")
    value_json = obj.get("value_json")
    if not isinstance(predicate, str) or not predicate.strip():
        return None
    if not isinstance(value_json, dict) or not value_json:
        return None

    conf = obj.get("confirmation_status") or "inferred"
    if not isinstance(conf, str) or conf not in CONFIRMATION_STATUSES:
        conf = "inferred"

    return Candidate(
        subject_type=(obj.get("subject_type") or "user"),
        subject_id=(obj.get("subject_id") or "self"),
        predicate=registry.canonical_predicate(predicate),
        value_json=value_json,
        scope=(obj.get("scope") or "global"),
        companion_id=obj.get("companion_id"),
        valid_from=_parse_date(obj.get("valid_from")),
        valid_until=_parse_date(obj.get("valid_until")),
        observed_at=_parse_date(obj.get("observed_at")) or now,
        confirmation_status=conf,
        sensitivity=sensitivity,
    )
