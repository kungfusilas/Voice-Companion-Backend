"""Diff the engine's before/after fact lists into a persistable, race-safe delta.

The engine is pure and returns a NEW `after` list. This module turns
(before, after) into:
  - inserts: brand-new Fact rows (active or historical-superseded)
  - supersedes: conditional status changes on EXISTING rows, carrying the
    expected version for optimistic compare-and-swap (applied by the Stage-2 RPC)
  - events: an audit trail for canonical_fact_events (restrained payloads)
No truth logic lives here — it only observes what the engine decided.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.canonical.models import Fact


@dataclass
class Delta:
    inserts: list[Fact] = field(default_factory=list)
    supersedes: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.inserts and not self.supersedes


def _event(event_type, fact, *, engine_version, candidate_id, related_fact_id=None):
    return {
        "event_type": event_type,
        "fact_id": fact.id,
        "related_fact_id": related_fact_id,
        "predicate": fact.predicate,
        "engine_version": engine_version,
        "candidate_id": candidate_id,
        "payload": {
            "normalized_value": fact.normalized_value,
            "status": fact.status,
        },
    }


def compute_delta(before, after, *, engine_version: str, candidate_id: str | None = None) -> Delta:
    before_by_id = {f.id: f for f in before}
    after_ids = {f.id for f in after}
    delta = Delta()

    # New rows (ids not present in `before`).
    for f in after:
        if f.id in before_by_id:
            continue
        delta.inserts.append(f)
        if f.status == "active":
            delta.events.append(_event("fact_created", f, engine_version=engine_version,
                                       candidate_id=candidate_id,
                                       related_fact_id=f.supersedes_fact_id))
        else:  # historical value recorded as already-superseded
            delta.events.append(_event("candidate_unconfirmed", f, engine_version=engine_version,
                                       candidate_id=candidate_id))

    # Existing rows whose status changed (active -> superseded/deleted).
    for f in after:
        prev = before_by_id.get(f.id)
        if prev is None or prev.status == f.status:
            continue
        delta.supersedes.append({
            "id": f.id,
            "expected_version": prev.version,
            "new_status": f.status,
            "valid_until": f.valid_until,
        })
        etype = "fact_deleted" if f.status == "deleted" else "fact_superseded"
        delta.events.append(_event(etype, f, engine_version=engine_version,
                                   candidate_id=candidate_id))

    # Pure dedup / no-op: nothing new, nothing changed.
    if delta.is_empty() and len(after) == len(before) and after_ids == set(before_by_id):
        delta.events.append({"event_type": "fact_deduped", "engine_version": engine_version,
                             "candidate_id": candidate_id})

    return delta
