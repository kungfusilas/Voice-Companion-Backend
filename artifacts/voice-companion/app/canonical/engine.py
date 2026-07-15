from __future__ import annotations

import json
import uuid
from datetime import date

from app.canonical.models import Fact, Candidate, Control
from app.canonical import registry

# Confirmation authority: a higher-ranked fact cannot be overridden by a lower-ranked
# conflicting candidate (the engine decides truth, not the raw model output).
_CONFIRM_RANK = {
    "disputed": 0, "inferred": 1, "explicitly_stated": 2,
    "user_confirmed": 3, "user_corrected": 3,
}


def normalize_value(value_json: dict) -> str:
    """Deterministic, case-insensitive canonical string for comparison."""
    def norm(v):
        if isinstance(v, str):
            return v.strip().lower()
        if isinstance(v, dict):
            return {k: norm(x) for k, x in v.items()}
        if isinstance(v, list):
            return [norm(x) for x in v]
        return v
    return json.dumps(norm(value_json), sort_keys=True, ensure_ascii=False)


def identity(subject_type, subject_id, predicate, scope, companion_id, value_json, reg=registry) -> tuple:
    """Slot identity for supersession/dedup.
    single  -> value-independent (one slot per predicate)
    multi   -> keyed by sub_key (one slot per entity)
    unknown -> keyed by normalized_value (each distinct value is its own slot,
               so differing values accumulate and never supersede)."""
    card = reg.cardinality(predicate)
    if card == "multi":
        disc = reg.sub_key(predicate, value_json)
    elif card == "unknown":
        disc = normalize_value(value_json)
    else:
        disc = None
    return (subject_type, subject_id, predicate, scope, companion_id, disc)


def _new_fact(cand: Candidate, now: date, status="active", supersedes=None,
              sub_key=None, cardinality="single") -> Fact:
    return Fact(
        id=str(uuid.uuid4()),
        subject_type=cand.subject_type, subject_id=cand.subject_id, predicate=cand.predicate,
        value_json=cand.value_json, normalized_value=normalize_value(cand.value_json),
        status=status, scope=cand.scope, companion_id=cand.companion_id,
        valid_from=cand.valid_from or now, valid_until=cand.valid_until,
        supersedes_fact_id=supersedes, confirmation_status=cand.confirmation_status,
        sensitivity=cand.sensitivity, sub_key=sub_key,
        cardinality=cardinality, observed_at=cand.observed_at,
    )


def apply_candidate(facts, cand: Candidate, now: date, reg=registry, prohibited=None):
    """Run a proposed fact through the lifecycle. Returns a NEW list; never mutates input."""
    facts = list(facts)
    if prohibited and f"{cand.subject_type}.{cand.predicate}" in prohibited:
        return facts  # user prohibited this key from ever being stored
    card = reg.cardinality(cand.predicate)
    stored_sk = reg.sub_key(cand.predicate, cand.value_json) if card == "multi" else None
    ident = identity(cand.subject_type, cand.subject_id, cand.predicate, cand.scope,
                     cand.companion_id, cand.value_json, reg)
    norm = normalize_value(cand.value_json)
    peers = [
        f for f in facts
        if f.status == "active"
        and identity(f.subject_type, f.subject_id, f.predicate, f.scope, f.companion_id, f.value_json, reg) == ident
    ]
    if not peers:
        facts.append(_new_fact(cand, now, sub_key=stored_sk, cardinality=card))
        return facts
    cur = peers[0]
    if cur.normalized_value == norm:
        return facts  # dedup / idempotent — same value, same identity
    cand_from = cand.valid_from or now
    if _CONFIRM_RANK[cand.confirmation_status] < _CONFIRM_RANK[cur.confirmation_status]:
        return facts  # lower-authority candidate cannot override a higher-authority current fact
    if cur.valid_from and cand_from < cur.valid_from:
        # candidate is historical (older effective date) → record as superseded, keep current
        facts.append(_new_fact(cand, now, status="superseded", sub_key=stored_sk, cardinality=card))
        return facts
    idx = facts.index(cur)
    facts[idx] = Fact(**{**cur.__dict__, "status": "superseded", "valid_until": cand_from})
    facts.append(_new_fact(cand, now, supersedes=cur.id, sub_key=stored_sk, cardinality=card))
    return facts


def _key_of(x) -> str:
    return f"{x.subject_type}.{x.predicate}"


def apply_control(facts, ctrl: Control, now: date, prohibited=None):
    """Apply a user control (forget/confirm/never_remember). Returns (facts, prohibited)."""
    facts = list(facts)
    prohibited = set(prohibited or set())
    if ctrl.op == "never_remember":
        prohibited.add(ctrl.key)
        return facts, prohibited
    for i, f in enumerate(facts):
        if f.status != "active" or _key_of(f) != ctrl.key:
            continue
        if ctrl.op == "forget":
            facts[i] = Fact(**{**f.__dict__, "status": "deleted", "valid_until": now})
        elif ctrl.op == "confirm":
            facts[i] = Fact(**{**f.__dict__, "confirmation_status": "user_confirmed"})
    return facts, prohibited


def active_facts(facts, at_time: date, scope="global", companion_id=None):
    """Facts that are active and valid at `at_time`, respecting scope visibility."""
    out = []
    for f in facts:
        if f.status != "active":
            continue
        if f.valid_from and f.valid_from > at_time:
            continue
        if f.valid_until and f.valid_until <= at_time:
            continue
        if f.scope == "global":
            out.append(f)
        elif f.scope == "companion" and scope == "companion" and f.companion_id == companion_id:
            out.append(f)
    return out
