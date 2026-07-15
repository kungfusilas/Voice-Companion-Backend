import asyncio
import json

from app import memory_extractor


def _capture_llm(monkeypatch, payload):
    captured = {}

    async def fake_send(*, system_prompt, history, user_message, model, max_tokens):
        captured.update(system_prompt=system_prompt, max_tokens=max_tokens)
        return json.dumps(payload)

    monkeypatch.setattr(memory_extractor.claude, "send_message", fake_send)
    return captured


def _clear_rollout(monkeypatch):
    for v in ("CANONICAL_EXTRACTION_ENABLED", "CANONICAL_EXTRACTION_PERCENT",
              "CANONICAL_EXTRACTION_ALLOWLIST"):
        monkeypatch.delenv(v, raising=False)


def test_rollout_off_is_byte_identical(monkeypatch):
    _clear_rollout(monkeypatch)
    cap = _capture_llm(monkeypatch, [])
    asyncio.run(memory_extractor.extract_and_save_core_facts("u1", "msg", "reply"))
    assert cap["system_prompt"] == memory_extractor._CORE_FACTS_SYSTEM
    assert cap["max_tokens"] == 400


def test_enabled_flag_extends_prompt(monkeypatch):
    _clear_rollout(monkeypatch)
    monkeypatch.setenv("CANONICAL_EXTRACTION_ENABLED", "true")
    cap = _capture_llm(monkeypatch, [])
    asyncio.run(memory_extractor.extract_and_save_core_facts("u1", "msg", "reply"))
    assert cap["system_prompt"].startswith(memory_extractor._CORE_FACTS_SYSTEM)
    assert '"canonical"' in cap["system_prompt"]
    assert "home_city" in cap["system_prompt"]
    # authority fields are NOT requested from the model:
    for banned in ("subject_type", "subject_id", '"scope"', "companion_id",
                   "user_confirmed", "user_corrected"):
        assert banned not in cap["system_prompt"]
    assert cap["max_tokens"] == 900


def test_allowlist_enables_only_listed_user(monkeypatch):
    _clear_rollout(monkeypatch)
    monkeypatch.setenv("CANONICAL_EXTRACTION_ALLOWLIST", "test-user-a, test-user-b")
    assert memory_extractor._canonical_enabled("test-user-a") is True
    assert memory_extractor._canonical_enabled("someone-else") is False


def test_percent_bucket_is_deterministic_and_bounded(monkeypatch):
    _clear_rollout(monkeypatch)
    monkeypatch.setenv("CANONICAL_EXTRACTION_PERCENT", "0")
    assert memory_extractor._canonical_enabled("any-user") is False
    monkeypatch.setenv("CANONICAL_EXTRACTION_PERCENT", "100")
    assert memory_extractor._canonical_enabled("any-user") is True
    monkeypatch.setenv("CANONICAL_EXTRACTION_PERCENT", "37")
    first = memory_extractor._canonical_enabled("stable-user")
    assert all(memory_extractor._canonical_enabled("stable-user") == first for _ in range(5))
    monkeypatch.setenv("CANONICAL_EXTRACTION_PERCENT", "garbage")
    assert memory_extractor._canonical_enabled("any-user") is False  # unparseable -> off
