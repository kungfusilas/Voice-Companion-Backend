import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))
from ab_prompt_gate import (parse_llm_output, compute_metrics,   # noqa: E402
                            evaluate_gate_b, evaluate_gate_split)


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
    assert m["no_fact_canonical"] == 0          # trap turn no longer counted here
    assert m["trap_canonical_count"] == 0       # trap turn's fact has no canonical
    assert m["canonical_total"] == 1            # only "a"'s fact carries a canonical key


def test_gate_b_fails_on_low_validity_and_no_fact_canonical():
    new = compute_metrics([
        _result("a", True, [_fact(canonical={"predicate": 123})], gold=["home_city"]),
        _result("n", False, [_fact(canonical=_GOOD_CANON)]),
    ])
    names = {n: ok for n, ok, _ in evaluate_gate_b(new)}
    assert names["canonical_validity"] is False
    assert names["no_fact_canonical"] is False


def test_trap_canonicals_gate():
    # 1 trap canonical out of 2 total canonicals = 50% > 3% -> fail
    new = compute_metrics([
        _result("a", True, [_fact(canonical=_GOOD_CANON)], gold=["home_city"]),
        _result("t", False, [_fact(canonical=_GOOD_CANON)], trap=True),
    ])
    names = {n: ok for n, ok, _ in evaluate_gate_b(new)}
    assert names["trap_unsupported"] is False
    assert names["no_fact_canonical"] is True      # trap turns no longer counted here


def test_zero_emission_reports_zero_validity_and_coverage():
    m = compute_metrics([_result("a", True, [_fact()])])   # a fact, but no canonical emitted
    assert m["canonical_validity"] == 0.0
    assert m["canonical_coverage"] == 0.0


def test_no_gold_turns_reports_zero_hit():
    m = compute_metrics([_result("a", True, [_fact(canonical=_GOOD_CANON)])])  # no gold labels
    assert m["gold_hit_rate"] == 0.0


def test_gates_pass_on_clean_identical_runs():
    res = [_result("a", True, [_fact(canonical=_GOOD_CANON)], gold=["home_city"]),
           _result("b", True, [_fact("work", canonical={"predicate": "employer", "value_json": {"name": "Acme"}})], gold=["employer"]),
           _result("n", False, []),
           _result("t", False, [], trap=True)]
    new = compute_metrics(res)
    assert all(ok for _, ok, _ in evaluate_gate_b(new))


def test_gate_split_includes_absolute_parse_check():
    ok = compute_metrics([_result("a", True, [_fact(canonical=_GOOD_CANON)], gold=["home_city"])])
    names = {n: ok_ for n, ok_, _ in evaluate_gate_split(ok)}
    assert names["parse_failure_abs"] is True
    bad = compute_metrics([_result(str(i), True, [_fact(canonical=_GOOD_CANON)], gold=["home_city"],
                                   parse_failed=(i == 0)) for i in range(10)])   # 10% parse fail
    names = {n: ok_ for n, ok_, _ in evaluate_gate_split(bad)}
    assert names["parse_failure_abs"] is False
