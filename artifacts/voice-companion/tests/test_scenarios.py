import os

from benchmark import runner

DIR = os.path.join(os.path.dirname(__file__), "..", "benchmark", "scenarios")


def test_all_scenarios_pass():
    results = runner.run_all(DIR)
    assert len(results) >= 12, f"expected >=12 scenarios, found {len(results)}"
    failures = [(r.name, r.assertion_failures + r.gate_failures) for r in results if not r.passed]
    assert not failures, f"scenario failures: {failures}"
