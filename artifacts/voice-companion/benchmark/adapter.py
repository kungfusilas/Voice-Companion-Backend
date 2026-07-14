from __future__ import annotations

from datetime import date

from app.canonical import engine


class MemoryAdapter:
    """Stable seam between the benchmark and the memory engine. Later slices (B/C/D)
    implement retrieve/answer/rebuild; the benchmark scenarios never change."""

    def __init__(self):
        self.facts = []
        self.prohibited = set()

    def apply_events(self, events):
        for ev in events:
            if ev["kind"] == "turn":
                for cand in ev["candidates"]:
                    self.facts = engine.apply_candidate(
                        self.facts, cand, now=ev["time"], prohibited=self.prohibited)
            elif ev["kind"] == "control":
                self.facts, self.prohibited = engine.apply_control(
                    self.facts, ev["control"], now=ev.get("time") or date.today(),
                    prohibited=self.prohibited)

    def active_facts(self, at_time: date, scope="global", companion_id=None):
        return engine.active_facts(self.facts, at_time, scope=scope, companion_id=companion_id)

    def retrieve(self, query, k):   # Layer B slice
        raise NotImplementedError

    def answer(self, query):        # Layer C slice
        raise NotImplementedError

    def rebuild(self):              # Layer D slice
        raise NotImplementedError
