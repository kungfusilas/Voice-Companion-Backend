from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from benchmark.adapter import MemoryAdapter
from benchmark import loader as _loader
from app.canonical.engine import normalize_value


@dataclass
class Result:
    name: str
    passed: bool = True
    assertion_failures: list = field(default_factory=list)
    gate_failures: list = field(default_factory=list)


def _key(f):
    return f"{f.subject_type}.{f.predicate}"


def run_scenario(scenario) -> Result:
    res = Result(name=scenario.name)
    adapter = MemoryAdapter()
    last_time = date.min
    for ev in scenario.events:
        if ev["kind"] in ("turn", "control"):
            adapter.apply_events([ev])
            if ev.get("time"):
                last_time = ev["time"]
            continue
        # checkpoint: assert at an explicit `at:` time, else the most recent event time
        at = date.fromisoformat(ev["at"]) if ev.get("at") else (last_time if last_time != date.min else date.max)
        active = adapter.active_facts(at)
        active_by_key = {}
        for f in active:
            active_by_key.setdefault(_key(f), []).append(f)

        for exp in ev.get("expected_active", []):
            got = active_by_key.get(exp["key"], [])
            if not any(normalize_value(f.value_json) == normalize_value(exp["value"]) for f in got):
                res.assertion_failures.append(
                    f"[{ev['name']}] expected active {exp['key']}={exp['value']}, got {[f.value_json for f in got]}")
        for exp in ev.get("expected_absent", []):
            if active_by_key.get(exp["key"]):
                res.assertion_failures.append(
                    f"[{ev['name']}] expected absent {exp['key']}, but present")
        for exp in ev.get("expected_superseded", []):
            supers = [f for f in adapter.facts
                      if _key(f) == exp["key"] and f.status == "superseded"
                      and normalize_value(f.value_json) == normalize_value(exp["value"])]
            if not supers:
                res.assertion_failures.append(
                    f"[{ev['name']}] expected superseded {exp['key']}={exp['value']}, not found")
        for key, want in ev.get("expected_counts", {}).items():
            got = len(active_by_key.get(key, []))
            if got != want:
                res.assertion_failures.append(
                    f"[{ev['name']}] expected {want} active '{key}', got {got}")

        # HARD GATE: a forbidden key must not appear in another companion's active set
        other = ev.get("gate_no_leak_to")
        if other:
            leaked = adapter.active_facts(at, scope="companion", companion_id=other)
            for f in leaked:
                if _key(f) in ev.get("forbidden_keys", []):
                    res.gate_failures.append(
                        f"[{ev['name']}] LEAK: {_key(f)} visible to companion '{other}'")

    res.passed = not res.assertion_failures and not res.gate_failures
    return res


def run_all(scenario_dir: str) -> list:
    import glob
    return [run_scenario(_loader.load_scenario(p)) for p in sorted(glob.glob(f"{scenario_dir}/*.yaml"))]


if __name__ == "__main__":  # python -m benchmark.runner
    import os, json, sys, datetime
    d = os.path.join(os.path.dirname(__file__), "scenarios")
    results = run_all(d)
    gate_fail = any(r.gate_failures for r in results)
    passed = sum(1 for r in results if r.passed)
    for r in results:
        print(f"[{'PASS' if r.passed else 'FAIL'}] {r.name}")
        for m in r.assertion_failures + r.gate_failures:
            print(f"    {m}")
    print(f"\nA1: {passed}/{len(results)} scenarios passed. "
          f"Hard gates: {'FAILED' if gate_fail else 'clean'}.")
    results_dir = os.path.join(d, "..", "results")
    os.makedirs(results_dir, exist_ok=True)
    out = os.path.join(results_dir, datetime.datetime.now().strftime("%Y%m%dT%H%M%S") + ".json")
    with open(out, "w") as fh:
        json.dump({"passed": passed, "total": len(results), "gate_failed": gate_fail,
                   "results": [r.__dict__ for r in results]}, fh, indent=2, default=str)
    sys.exit(1 if (gate_fail or passed != len(results)) else 0)
