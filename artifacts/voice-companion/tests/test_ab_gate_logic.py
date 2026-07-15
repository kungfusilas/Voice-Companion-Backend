import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))
from ab_prompt_gate import (parse_llm_output, compute_metrics,   # noqa: E402
                            evaluate_gate_a, evaluate_gate_b)


def _result(turn_id, expect, facts, parse_failed=False, trap=False, gold=None):
    return {"id": turn_id, "expect_facts": expect, "trap": trap,
            "gold_predicates": gold or [], "parse_failed": parse_failed,
            "facts": facts or []}


def _fact(cat="location", sens="none", canonical=None):
    f = {"category": cat, "fact": "x", "sensitivity": sens}
    if canonical is not None:
        f["canonical"] = canonical
    return f


_GOOD_CANON = {"predicate": "home_city", "value_json": {"city": "Easton"}}


def test_parse_llm_output_handles_fences_and_garbage():
    assert parse_llm_output('```json\n[{"category":"work","fact":"a","sensitivity":"none"}]\n```') is not None
    assert parse_llm_output("not json at all") is None
    assert parse_llm_output('{"an":"object"}') is None


def test_compute_metrics_core_shapes():
    m = compute_metrics([
        _result("a", True, [_fact(canonical=_GOOD_CANON)], gold=["home_city"]),
        _result("b", True, [], parse_failed=True),
        _result("c", False, []),
        _result("t", False, [_fact("work")], trap=True),
    ])
    assert m["turns"] == 4 and m["parse_failures"] == 1
    assert m["capture_rate"] == 0.5
    assert m["trap_fp_rate"] == 1.0                     # 1 of 1 trap turns extracted a fact
    assert m["canonical_coverage"] == 0.5               # 1 of 2 fact-turns had a valid canonical
    assert m["canonical_validity"] == 1.0
    assert m["gold_hit_rate"] == 1.0
    assert m["no_fact_canonical"] == 0


def test_gate_a_fails_on_capture_and_trap_regression():
    old = compute_metrics([_result("a", True, [_fact()]), _result("b", True, [_fact()]),
                           _result("t", False, [], trap=True)])
    new = compute_metrics([_result("a", True, []), _result("b", True, [_fact()]),
                           _result("t", False, [_fact()], trap=True)])
    names = {n: ok for n, ok, _ in evaluate_gate_a(old, new)}
    assert names["capture_rate"] is False and names["trap_fp"] is False


def test_gate_b_fails_on_low_validity_and_no_fact_canonical():
    new = compute_metrics([
        _result("a", True, [_fact(canonical={"predicate": 123})], gold=["home_city"]),
        _result("n", False, [_fact(canonical=_GOOD_CANON)]),
    ])
    names = {n: ok for n, ok, _ in evaluate_gate_b(new)}
    assert names["canonical_validity"] is False
    assert names["no_fact_canonical"] is False


def test_gates_pass_on_clean_identical_runs():
    res = [_result("a", True, [_fact(canonical=_GOOD_CANON)], gold=["home_city"]),
           _result("b", True, [_fact("work", canonical={"predicate": "employer", "value_json": {"name": "Acme"}})], gold=["employer"]),
           _result("n", False, []),
           _result("t", False, [], trap=True)]
    old, new = compute_metrics(res), compute_metrics(res)
    assert all(ok for _, ok, _ in evaluate_gate_a(old, new))
    assert all(ok for _, ok, _ in evaluate_gate_b(new))
