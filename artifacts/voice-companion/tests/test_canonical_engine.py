from datetime import date

import pytest

from app.canonical import engine, registry
from app.canonical.models import Candidate, Control


# ── helpers ──────────────────────────────────────────────────────────────────

def _cand(**kw):
    base = dict(subject_type="user", predicate="home_city", value_json={"city": "Bethlehem"},
                confirmation_status="explicitly_stated", valid_from=date(2026, 1, 10))
    base.update(kw)
    return Candidate(**base)


def _active(facts):
    return [f for f in facts if f.status == "active"]


def _kid(name, **kw):
    return Candidate(subject_type="user", predicate="children", value_json={"name": name},
                     confirmation_status="explicitly_stated", valid_from=date(2026, 1, 1), **kw)


# ── T1: normalize / registry / identity ──────────────────────────────────────

def test_normalize_is_case_and_order_insensitive():
    assert engine.normalize_value({"city": "Easton"}) == engine.normalize_value({"city": "easton"})
    assert engine.normalize_value({"a": "x", "b": "y"}) == engine.normalize_value({"b": "y", "a": "x"})


def test_registry_cardinality():
    assert registry.cardinality("home_city") == "single"
    assert registry.cardinality("children") == "multi"
    assert registry.cardinality("unknown_predicate") == "unknown"


def test_identity_single_ignores_value_multi_uses_subkey():
    single = engine.identity("user", "u1", "home_city", "global", None, {"city": "Easton"}, registry)
    single2 = engine.identity("user", "u1", "home_city", "global", None, {"city": "Erie"}, registry)
    assert single == single2
    kid_a = engine.identity("user", "u1", "children", "global", None, {"name": "Emmie"}, registry)
    kid_b = engine.identity("user", "u1", "children", "global", None, {"name": "Sam"}, registry)
    assert kid_a != kid_b


# ── T2: apply_candidate single-valued ────────────────────────────────────────

def test_upsert_new_fact():
    facts = engine.apply_candidate([], _cand(), now=date(2026, 1, 10))
    assert len(_active(facts)) == 1
    assert _active(facts)[0].value_json == {"city": "Bethlehem"}


def test_dedup_identical_mentions():
    facts = engine.apply_candidate([], _cand(), now=date(2026, 1, 10))
    facts = engine.apply_candidate(facts, _cand(), now=date(2026, 1, 11))
    assert len(_active(facts)) == 1


def test_idempotent_double_apply():
    facts = engine.apply_candidate([], _cand(), now=date(2026, 1, 10))
    n = len(facts)
    facts2 = engine.apply_candidate(facts, _cand(), now=date(2026, 1, 10))
    assert len(facts2) == n


def test_supersession_new_value():
    facts = engine.apply_candidate([], _cand(), now=date(2026, 1, 10))
    facts = engine.apply_candidate(
        facts, _cand(value_json={"city": "Easton"}, confirmation_status="user_corrected",
                     valid_from=date(2027, 3, 15)), now=date(2027, 4, 15))
    act = _active(facts)
    assert len(act) == 1 and act[0].value_json == {"city": "Easton"}
    superseded = [f for f in facts if f.status == "superseded"]
    assert len(superseded) == 1 and superseded[0].value_json == {"city": "Bethlehem"}
    assert act[0].supersedes_fact_id == superseded[0].id


def test_confirmation_precedence_blocks_inferred_override():
    facts = engine.apply_candidate(
        [], _cand(value_json={"city": "Easton"}, confirmation_status="user_confirmed"), now=date(2027, 1, 1))
    facts = engine.apply_candidate(
        facts, _cand(value_json={"city": "Reading"}, confirmation_status="inferred",
                     valid_from=date(2027, 2, 1)), now=date(2027, 2, 1))
    act = _active(facts)
    assert len(act) == 1 and act[0].value_json == {"city": "Easton"}


def test_out_of_order_correction_keeps_current():
    facts = engine.apply_candidate(
        [], _cand(value_json={"city": "Easton"}, valid_from=date(2027, 3, 15)), now=date(2027, 4, 1))
    facts = engine.apply_candidate(
        facts, _cand(value_json={"city": "Bethlehem"}, valid_from=date(2026, 1, 10)), now=date(2027, 4, 2))
    act = _active(facts)
    assert len(act) == 1 and act[0].value_json == {"city": "Easton"}


# ── T3: apply_candidate multi-valued ─────────────────────────────────────────

def test_multi_accumulates_distinct():
    facts = engine.apply_candidate([], _kid("Emmie"), now=date(2026, 1, 1))
    facts = engine.apply_candidate(facts, _kid("Sam"), now=date(2026, 1, 2))
    act = _active(facts)
    assert {f.value_json["name"] for f in act} == {"Emmie", "Sam"}
    assert not [f for f in facts if f.status == "superseded"]


def test_multi_dedup_same_subkey():
    facts = engine.apply_candidate([], _kid("Emmie"), now=date(2026, 1, 1))
    facts = engine.apply_candidate(facts, _kid("emmie"), now=date(2026, 1, 2))
    assert len(_active(facts)) == 1


# ── T4: apply_control ────────────────────────────────────────────────────────

def test_forget_deletes_active():
    facts = engine.apply_candidate([], _cand(), now=date(2026, 1, 10))
    facts, _ = engine.apply_control(facts, Control(op="forget", key="user.home_city"), now=date(2026, 2, 1))
    assert not _active(facts)
    assert [f for f in facts if f.status == "deleted"]


def test_confirm_upgrades_status():
    facts = engine.apply_candidate([], _cand(confirmation_status="inferred"), now=date(2026, 1, 10))
    facts, _ = engine.apply_control(facts, Control(op="confirm", key="user.home_city"), now=date(2026, 2, 1))
    assert _active(facts)[0].confirmation_status == "user_confirmed"


def test_never_remember_blocks_future_candidate():
    facts, prohibited = engine.apply_control(
        [], Control(op="never_remember", key="user.home_city"), now=date(2026, 1, 1))
    facts = engine.apply_candidate(facts, _cand(), now=date(2026, 1, 10), prohibited=prohibited)
    assert not _active(facts)


# ── T5: active_facts ─────────────────────────────────────────────────────────

def test_active_facts_scope_isolation():
    aeva = engine.apply_candidate([], _cand(scope="companion", companion_id="aeva"), now=date(2026, 1, 10))
    assert len(engine.active_facts(aeva, date(2026, 2, 1), scope="companion", companion_id="aeva")) == 1
    assert len(engine.active_facts(aeva, date(2026, 2, 1), scope="companion", companion_id="aria")) == 0


def test_global_visible_to_any_companion():
    g = engine.apply_candidate([], _cand(scope="global"), now=date(2026, 1, 10))
    assert len(engine.active_facts(g, date(2026, 2, 1), scope="companion", companion_id="aria")) == 1


def test_expiry_excludes_past_valid_until():
    facts = engine.apply_candidate(
        [], _cand(valid_from=date(2026, 1, 1), valid_until=date(2026, 2, 1)), now=date(2026, 1, 1))
    assert len(engine.active_facts(facts, date(2026, 1, 15))) == 1
    assert len(engine.active_facts(facts, date(2026, 3, 1))) == 0


def test_not_yet_valid_excluded():
    facts = engine.apply_candidate([], _cand(valid_from=date(2027, 1, 1)), now=date(2027, 1, 1))
    assert len(engine.active_facts(facts, date(2026, 6, 1))) == 0


# ── T6: unknown cardinality ──────────────────────────────────────────────────

def _friend(name):
    return Candidate(subject_type="user", predicate="friend",
                     value_json={"name": name}, confirmation_status="explicitly_stated")


def test_unknown_predicate_accumulates_never_supersedes():
    now = date(2027, 1, 1)
    facts = engine.apply_candidate([], _friend("Susan"), now)
    facts = engine.apply_candidate(facts, _friend("Michael"), now)
    active = engine.active_facts(facts, now)
    names = sorted(f.value_json["name"] for f in active)
    assert names == ["Michael", "Susan"]  # both survive; no supersession


def test_unknown_predicate_dedups_identical_value():
    now = date(2027, 1, 1)
    facts = engine.apply_candidate([], _friend("Susan"), now)
    facts = engine.apply_candidate(facts, _friend("susan"), now)  # case-insensitive repeat
    assert len(engine.active_facts(facts, now)) == 1


def test_fact_carries_cardinality_and_sub_key_semantics():
    now = date(2027, 1, 1)
    facts = engine.apply_candidate([], _friend("Susan"), now)
    f = engine.active_facts(facts, now)[0]
    assert f.cardinality == "unknown"
    assert f.sub_key is None  # unknown uses normalized_value, not sub_key column
