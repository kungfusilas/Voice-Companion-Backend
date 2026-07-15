from __future__ import annotations

from dataclasses import dataclass
from datetime import date

CONFIRMATION_STATUSES = frozenset({
    "disputed", "inferred", "explicitly_stated", "user_confirmed", "user_corrected",
})


@dataclass
class Fact:
    id: str
    subject_type: str
    subject_id: str
    predicate: str
    value_json: dict
    normalized_value: str
    status: str = "active"          # active|superseded|deleted|expired|unconfirmed
    scope: str = "global"           # global|companion|session|vault
    companion_id: str | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    supersedes_fact_id: str | None = None
    confirmation_status: str = "inferred"
    sensitivity: str = "none"
    sub_key: str | None = None
    cardinality: str = "single"
    observed_at: date | None = None
    version: int = 1


@dataclass
class Candidate:
    subject_type: str
    predicate: str
    value_json: dict
    subject_id: str = "self"
    scope: str = "global"
    companion_id: str | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    confirmation_status: str = "inferred"
    sensitivity: str = "none"
    observed_at: date | None = None


@dataclass
class Control:
    op: str                          # forget|confirm|never_remember
    key: str                         # "<subject_type>.<predicate>" shorthand
    subject_id: str = "self"
    scope: str = "global"
    companion_id: str | None = None
