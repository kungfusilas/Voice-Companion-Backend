import asyncio
import json

from app import canonical_extractor, memory_extractor


def _clear_rollout(monkeypatch):
    for v in ("CANONICAL_EXTRACTION_ENABLED", "CANONICAL_EXTRACTION_PERCENT",
              "CANONICAL_EXTRACTION_ALLOWLIST"):
        monkeypatch.delenv(v, raising=False)


def test_system_prompt_is_legacy_plus_addon():
    s = canonical_extractor.CANONICAL_EXTRACTION_SYSTEM
    assert s.startswith(memory_extractor._CORE_FACTS_SYSTEM)
    assert '"canonical"' in s and "home_city" in s
    for banned in ("subject_type", "subject_id", '"scope"', "companion_id",
                   "user_confirmed", "user_corrected", "disputed"):
        assert banned not in s.replace(memory_extractor._CORE_FACTS_SYSTEM, "")


def test_rollout_logic_moved(monkeypatch):
    _clear_rollout(monkeypatch)
    assert canonical_extractor.canonical_enabled("u1") is False
    monkeypatch.setenv("CANONICAL_EXTRACTION_ALLOWLIST", "u1")
    assert canonical_extractor.canonical_enabled("u1") is True
    assert canonical_extractor.canonical_enabled("u2") is False
    monkeypatch.setenv("CANONICAL_EXTRACTION_ENABLED", "true")
    assert canonical_extractor.canonical_enabled("u2") is True


def test_extract_candidates_parses_and_validates(monkeypatch):
    payload = [
        {"category": "location", "fact": "Lives in Easton", "sensitivity": "location",
         "canonical": {"predicate": "home_city", "value_json": {"city": "Easton"}}},
        {"category": "bogus-cat", "fact": "dropped", "sensitivity": "none"},
        "not a dict",
    ]

    async def fake_send(*, system_prompt, history, user_message, model, max_tokens):
        assert system_prompt == canonical_extractor.CANONICAL_EXTRACTION_SYSTEM
        assert max_tokens == 900
        return "Here you go:\n" + json.dumps(payload)   # prose-wrapped: parser must recover

    monkeypatch.setattr(canonical_extractor.claude, "send_message", fake_send)
    out = asyncio.run(canonical_extractor.extract_canonical_candidates("u1", "m", "r"))
    assert len(out) == 1 and out[0]["canonical"]["predicate"] == "home_city"


def test_extract_candidates_never_raises(monkeypatch):
    async def boom(*a, **kw):
        raise RuntimeError("llm down")
    monkeypatch.setattr(canonical_extractor.claude, "send_message", boom)
    assert asyncio.run(canonical_extractor.extract_canonical_candidates("u1", "m", "r")) == []


def test_sensitivity_coerced_to_vocabulary(monkeypatch):
    payload = [
        {"category": "health", "fact": "a", "sensitivity": "super-secret-custom"},
        {"category": "location", "fact": "b", "sensitivity": "location"},
        {"category": "work", "fact": "c"},
    ]

    async def fake_send(*a, **kw):
        return json.dumps(payload)

    monkeypatch.setattr(canonical_extractor.claude, "send_message", fake_send)
    out = asyncio.run(canonical_extractor.extract_canonical_candidates("u1", "m", "r"))
    assert [f["sensitivity"] for f in out] == ["none", "location", "none"]
