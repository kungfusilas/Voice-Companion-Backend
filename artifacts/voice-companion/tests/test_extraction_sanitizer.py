from app.shadow_ledger import sanitize_extraction_canonical, EXTRACTOR_VERSION


def test_version_bumped_for_canonical_era():
    assert EXTRACTOR_VERSION == "core-facts-canonical-v1"


def test_strips_authority_fields_and_clamps_confirmation():
    out = sanitize_extraction_canonical({
        "predicate": "home_city", "value_json": {"city": "Easton"},
        "subject_type": "companion", "subject_id": "other-user",
        "scope": "companion", "companion_id": "aeva",
        "confirmation_status": "user_confirmed"})
    for k in ("subject_type", "subject_id", "scope", "companion_id"):
        assert k not in out
    assert out["confirmation_status"] == "inferred"      # authority downgrade
    assert out["predicate"] == "home_city" and out["value_json"] == {"city": "Easton"}


def test_keeps_allowed_confirmations_and_dates():
    out = sanitize_extraction_canonical({
        "predicate": "home_city", "value_json": {"city": "X"},
        "confirmation_status": "explicitly_stated", "valid_from": "2026-06-01"})
    assert out["confirmation_status"] == "explicitly_stated"
    assert out["valid_from"] == "2026-06-01"


def test_non_dict_passes_through():
    assert sanitize_extraction_canonical(None) is None
    assert sanitize_extraction_canonical("garbage") == "garbage"   # mapper rejects it downstream
