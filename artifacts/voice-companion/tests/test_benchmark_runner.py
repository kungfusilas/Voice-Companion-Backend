from datetime import date

from benchmark.adapter import MemoryAdapter
from benchmark import loader, runner
from app.canonical.models import Candidate, Control


def test_adapter_applies_turns_and_controls():
    a = MemoryAdapter()
    a.apply_events([
        {"kind": "turn", "time": date(2026, 1, 10),
         "candidates": [Candidate("user", "home_city", {"city": "Bethlehem"},
                                  valid_from=date(2026, 1, 10), confirmation_status="explicitly_stated")]},
        {"kind": "control", "time": date(2026, 2, 1), "control": Control(op="forget", key="user.home_city")},
    ])
    assert a.active_facts(date(2026, 2, 2)) == []


def test_runner_passes_good_scenario(tmp_path):
    p = tmp_path / "g.yaml"
    p.write_text('''
scenario: g
events:
  - time: "2026-01-10"
    companion: aeva
    user: "I live in Bethlehem."
    extraction:
      - {subject_type: user, predicate: home_city, value_json: {city: Bethlehem}, confirmation_status: explicitly_stated, valid_from: "2026-01-10"}
  - checkpoint: c1
    expected_active:
      - {key: user.home_city, value: {city: Bethlehem}}
''')
    res = runner.run_scenario(loader.load_scenario(str(p)))
    assert res.passed and not res.assertion_failures


def test_runner_fails_on_wrong_value(tmp_path):
    p = tmp_path / "b.yaml"
    p.write_text('''
scenario: b
events:
  - time: "2026-01-10"
    companion: aeva
    user: "x"
    extraction:
      - {subject_type: user, predicate: home_city, value_json: {city: Bethlehem}, confirmation_status: explicitly_stated, valid_from: "2026-01-10"}
  - checkpoint: c1
    expected_active:
      - {key: user.home_city, value: {city: Easton}}
''')
    res = runner.run_scenario(loader.load_scenario(str(p)))
    assert not res.passed and res.assertion_failures


def test_gate_holds_when_engine_isolates(tmp_path):
    p = tmp_path / "leak.yaml"
    p.write_text('''
scenario: leak
events:
  - time: "2026-01-10"
    companion: aeva
    user: "secret"
    extraction:
      - {subject_type: user, predicate: secret_note, value_json: {v: s}, scope: companion, companion_id: aeva, confirmation_status: explicitly_stated, valid_from: "2026-01-10"}
  - checkpoint: c1
    gate_no_leak_to: aria
    forbidden_keys: [user.secret_note]
''')
    res = runner.run_scenario(loader.load_scenario(str(p)))
    assert res.passed and not res.gate_failures
