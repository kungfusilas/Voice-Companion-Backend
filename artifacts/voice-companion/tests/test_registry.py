from app.canonical import registry as reg


def test_registered_single_and_multi():
    assert reg.cardinality("home_city") == "single"
    assert reg.cardinality("children") == "multi"


def test_scenario_predicates_keep_current_cardinality():
    # These are relied on by existing benchmark scenarios and were "single" by default.
    for p in ("home_city", "current_trip", "therapy_note"):
        assert reg.cardinality(p) == "single"


def test_unregistered_predicate_is_unknown():
    assert reg.cardinality("friend") == "unknown"
    assert reg.cardinality("favorite_conspiracy_theory") == "unknown"


def test_alias_resolves_before_cardinality():
    assert reg.canonical_predicate("city_of_residence") == "home_city"
    assert reg.canonical_predicate("lives_in") == "home_city"
    assert reg.cardinality("city_of_residence") == "single"
    assert reg.canonical_predicate("unknown_thing") == "unknown_thing"


def test_sub_key_multi_only():
    assert reg.sub_key("children", {"name": "Emma"}) == "emma"
    assert reg.sub_key("home_city", {"city": "Easton"}) is None


def test_is_registered_and_value_hint():
    assert reg.is_registered("home_city") is True
    assert reg.is_registered("friend") is False
    assert "city" in reg.value_hint("home_city")
    assert reg.value_hint("friend") is None
