from datetime import date
from app.canonical.mapper import map_canonical


def test_maps_full_canonical_object():
    obj = {"subject_type": "user", "subject_id": "self", "predicate": "home_city",
           "value_json": {"city": "Easton", "state": "Pennsylvania"},
           "confirmation_status": "explicitly_stated",
           "observed_at": "2026-07-14", "valid_from": "2026-06-01"}
    c = map_canonical(obj, sensitivity="location", now=date(2026, 7, 14))
    assert c is not None
    assert c.predicate == "home_city"
    assert c.value_json == {"city": "Easton", "state": "Pennsylvania"}
    assert c.observed_at == date(2026, 7, 14)
    assert c.valid_from == date(2026, 6, 1)
    assert c.sensitivity == "location"


def test_alias_predicate_is_canonicalized():
    c = map_canonical({"predicate": "lives_in", "value_json": {"city": "Reading"}})
    assert c.predicate == "home_city"


def test_missing_predicate_or_value_returns_none():
    assert map_canonical({"value_json": {"city": "X"}}) is None
    assert map_canonical({"predicate": "home_city"}) is None
    assert map_canonical({"predicate": "home_city", "value_json": {}}) is None
    assert map_canonical(None) is None
    assert map_canonical("not a dict") is None


def test_defaults_and_invalid_confirmation():
    c = map_canonical({"predicate": "friend", "value_json": {"name": "Sue"},
                       "confirmation_status": "totally_made_up"})
    assert c.subject_type == "user"
    assert c.subject_id == "self"
    assert c.scope == "global"
    assert c.confirmation_status == "inferred"  # invalid value falls back


def test_bad_dates_are_dropped_not_fatal():
    c = map_canonical({"predicate": "home_city", "value_json": {"city": "X"},
                       "valid_from": "not-a-date"})
    assert c is not None
    assert c.valid_from is None
