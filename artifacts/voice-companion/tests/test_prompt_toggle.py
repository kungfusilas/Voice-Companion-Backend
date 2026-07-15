import asyncio
import json

import pytest

from app import memory_extractor


def _capture_llm(monkeypatch, payload):
    captured = {}

    async def fake_send(*, system_prompt, history, user_message, model, max_tokens):
        captured.update(system_prompt=system_prompt, max_tokens=max_tokens)
        return json.dumps(payload)

    monkeypatch.setattr(memory_extractor.claude, "send_message", fake_send)
    return captured


@pytest.mark.parametrize("enabled", [None, "true"])
def test_legacy_call_is_byte_identical_regardless_of_rollout(monkeypatch, enabled):
    for v in ("CANONICAL_EXTRACTION_ENABLED", "CANONICAL_EXTRACTION_PERCENT",
              "CANONICAL_EXTRACTION_ALLOWLIST"):
        monkeypatch.delenv(v, raising=False)
    if enabled:
        monkeypatch.setenv("CANONICAL_EXTRACTION_ENABLED", enabled)
    cap = _capture_llm(monkeypatch, [])
    asyncio.run(memory_extractor.extract_and_save_core_facts("u1", "msg", "reply"))
    assert cap["system_prompt"] == memory_extractor._CORE_FACTS_SYSTEM
    assert cap["max_tokens"] == 400
