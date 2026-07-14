from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import yaml

from app.canonical.models import Candidate, Control


def _to_date(s):
    return date.fromisoformat(str(s))


@dataclass
class Scenario:
    name: str
    events: list = field(default_factory=list)  # each: {"kind", ...}


def _parse_candidate(d: dict) -> Candidate:
    return Candidate(
        subject_type=d["subject_type"], predicate=d["predicate"], value_json=d["value_json"],
        subject_id=d.get("subject_id", "user"), scope=d.get("scope", "global"),
        companion_id=d.get("companion_id"),
        valid_from=_to_date(d["valid_from"]) if d.get("valid_from") else None,
        valid_until=_to_date(d["valid_until"]) if d.get("valid_until") else None,
        confirmation_status=d.get("confirmation_status", "inferred"),
        sensitivity=d.get("sensitivity", "none"),
    )


def load_scenario(path: str) -> Scenario:
    with open(path) as fh:
        raw = yaml.safe_load(fh)
    if not raw or "scenario" not in raw:
        raise ValueError(f"{path}: missing 'scenario'")
    events = []
    for ev in raw.get("events", []):
        if "checkpoint" in ev:
            for a in (ev.get("expected_active", []) + ev.get("expected_superseded", [])
                      + ev.get("expected_absent", [])):
                if not isinstance(a.get("key"), str):
                    raise ValueError(f"{path}: assertion 'key' must be a string, got {a.get('key')!r}")
            events.append({"kind": "checkpoint", "name": ev["checkpoint"], **ev})
        elif "control" in ev:
            c = ev["control"]
            events.append({
                "kind": "control",
                "time": _to_date(ev["time"]) if ev.get("time") else None,
                "control": Control(op=c["op"], key=c["key"], subject_id=c.get("subject_id", "user"),
                                   scope=c.get("scope", "global"), companion_id=c.get("companion_id")),
            })
        else:
            events.append({
                "kind": "turn",
                "time": _to_date(ev["time"]),
                "candidates": [_parse_candidate(x) for x in ev.get("extraction", [])],
            })
    return Scenario(name=raw["scenario"], events=events)
