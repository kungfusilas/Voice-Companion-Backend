# Canonical Ledger — Split Extraction (the spec's pre-registered fallback)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move canonical extraction to a **dedicated second LLM call**, restoring the legacy core-facts call to byte-identical behavior **unconditionally** (even when the rollout is enabled). This eliminates the piggyback's one irreducible failure class — strictness-in-context suppressing legacy soft-category recall — by construction.

**Why now (evidence):** six shared-prompt variants, six gate invocations. Everything fixable was fixed (parse 4.1%, trap canonicals 0 in 300+ evals, validity 99–100%, coverage 91–94%, gold 91–93%); the remaining failure straddled the GATE-A capture line (94.9% PASS → 91.0% FAIL on the same binary) with a recurring soft-category suppression cluster (`goal-1`, `hobby-1`, `pers-1`, `fin-1`) that survived an invariance rule and a category whitelist. Per the approved spec: *"piggyback stays the default; the A/B result is what earns it — else fall back to a separate call."*

**The key economy:** the dedicated call's prompt is `_CORE_FACTS_SYSTEM + _CORE_FACTS_CANONICAL_ADDON` — the exact combined prompt whose canonical-side quality is **already measured** (three consecutive GATE-B green invocations). We are not gambling on a new prompt; we are shipping the proven one, minus the arm it was hurting.

**Architecture:** `app/canonical_extractor.py` owns the rollout check + the dedicated call, returning the same fact-dict shape (`{category, fact, sensitivity, canonical{...}}`) so `shadow_ledger.run` consumes it **unchanged**. `memory_extractor` returns to pure legacy (prompt/tokens unconditional). `chat._extract_and_shadow` gates on the rollout, runs legacy first (always), then the canonical call inside the shadow timeout. The A/B gate becomes single-arm (no regression arm needed — legacy is untouched by construction), halving its cost.

**Tech Stack:** unchanged (Haiku via `claude.send_message`, pytest, fakes; no new deps).

## Global Constraints

- **Legacy call byte-identical UNCONDITIONALLY.** `extract_and_save_core_facts` always sends `_CORE_FACTS_SYSTEM` with `max_tokens=400`, regardless of any rollout var. Test-pinned for both enabled and disabled states.
- **Zero changes to** `shadow_ledger.py`, `app/canonical/*`, migrations, or the corpus.
- The dedicated prompt = `_CORE_FACTS_SYSTEM + _CORE_FACTS_CANONICAL_ADDON` verbatim (constants moved, not reworded), `max_tokens=900`, same model. Authority tokens stay banned from the addon.
- **Cost boundary:** the second call fires ONLY when `canonical_enabled(user_id)` (allowlist → flag → percent) — zero extra calls for un-enrolled users.
- **Single-arm gate thresholds (pre-registered):** parse ≤ 5% absolute (now enforceable — no legacy baggage); coverage ≥ 90%; validity ≥ 95%; gold-hit ≥ 85%; no-fact canonicals == 0 (explicit no-fact turns); trap canonicals ≤ 3% of all canonicals (raw counts shown). Double-PASS rule (two independent invocations) retained.
- Clean-env full suite + benchmark stay green. All commands from `artifacts/voice-companion/` via `./venv/bin/python`.

---

## File Structure

- Create `app/canonical_extractor.py` — `canonical_enabled(user_id)`, `CANONICAL_EXTRACTION_SYSTEM`, `extract_canonical_candidates(user_id, user_message, ai_response) -> list[dict]`.
- Modify `app/memory_extractor.py` — remove the toggle branch from the LLM call (always legacy); move `_canonical_enabled`, `_canonical_hint_lines`, `_CORE_FACTS_CANONICAL_ADDON` out (addon/hints go to `canonical_extractor`; expose `_CORE_FACTS_SYSTEM`, `_parse_fact_array`, `_CORE_FACTS_VALID_CATEGORIES` for import).
- Modify `app/routers/chat.py` — `_extract_and_shadow` gates on `canonical_extractor.canonical_enabled`, feeds the second call's candidates to the shadow; `SHADOW_TIMEOUT_SECONDS` 8.0 → 20.0 (now covers an LLM call; still under `_bg`'s own 20s+drain envelope).
- Modify `tests/test_prompt_toggle.py` — becomes the byte-identical-always proof + rollout tests pointing at `canonical_extractor`.
- Create `tests/test_canonical_extractor.py` — prompt composition, banned tokens, candidate parsing/validation, fail-safe empty.
- Modify `tests/test_shadow_wiring.py` — wiring gates on enabled; candidates feed shadow; disabled → zero extra calls.
- Modify `scripts/ab_prompt_gate.py` + `tests/test_ab_gate_logic.py` — single-arm mode (`evaluate_gate_split`), GATE A retired.

---

### Task 1: `canonical_extractor` module + legacy restored to unconditional

**Files:**
- Create: `app/canonical_extractor.py`
- Modify: `app/memory_extractor.py`
- Test: `tests/test_canonical_extractor.py` (create), `tests/test_prompt_toggle.py` (rewrite)

**Interfaces:**
- Produces: `canonical_extractor.canonical_enabled(user_id) -> bool` (same allowlist → flag → percent logic, moved); `canonical_extractor.CANONICAL_EXTRACTION_SYSTEM: str`; `async canonical_extractor.extract_canonical_candidates(user_id, user_message, ai_response) -> list[dict]` (validated fact dicts, same shape shadow already consumes; `[]` on any failure — never raises). `memory_extractor.extract_and_save_core_facts` loses all rollout awareness.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_canonical_extractor.py`:

```python
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
```

Rewrite `tests/test_prompt_toggle.py` (byte-identical becomes unconditional):

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `./venv/bin/python -m pytest tests/test_canonical_extractor.py tests/test_prompt_toggle.py -q`
Expected: FAIL (`No module named 'app.canonical_extractor'`; the enabled-parametrized case gets the addon prompt today).

- [ ] **Step 3: Create `app/canonical_extractor.py`**

Move `_canonical_enabled` (renamed `canonical_enabled`), `_canonical_hint_lines`, and `_CORE_FACTS_CANONICAL_ADDON` VERBATIM from `memory_extractor` into this module (update the hint fn's registry import path as-is), then add:

```python
"""Dedicated canonical-candidate extraction (the spec's split-extraction fallback).

Runs as a SECOND background LLM call, only for rollout-enabled users, so the
legacy core-facts call stays byte-identical forever. Output uses the same
fact-dict shape the shadow ledger already consumes; failures return [] —
never raises, never touches user_core_facts.
"""
from __future__ import annotations

import hashlib
import logging
import os

from app import claude
from app.memory_extractor import (_CORE_FACTS_SYSTEM, _CORE_FACTS_VALID_CATEGORIES,
                                  _parse_fact_array)

logger = logging.getLogger(__name__)

# ... canonical_enabled / _canonical_hint_lines / _CORE_FACTS_CANONICAL_ADDON here ...

CANONICAL_EXTRACTION_SYSTEM = _CORE_FACTS_SYSTEM + _CORE_FACTS_CANONICAL_ADDON


async def extract_canonical_candidates(user_id: str, user_message: str,
                                       ai_response: str) -> list[dict]:
    try:
        raw = await claude.send_message(
            system_prompt=CANONICAL_EXTRACTION_SYSTEM,
            history=[],
            user_message=(f"User said: {user_message}\n\n"
                          f"Companion replied: {ai_response}"),
            model="claude-haiku-4-5-20251001",
            max_tokens=900,
        )
        items = _parse_fact_array(raw)
        if not items:
            return []
        return [f for f in items
                if isinstance(f, dict)
                and f.get("category") in _CORE_FACTS_VALID_CATEGORIES
                and isinstance(f.get("fact"), str) and f["fact"].strip()]
    except Exception as exc:
        logger.warning("[canonical_extractor] EXCEPTION user=%.8s: %r", user_id[:8], exc)
        return []
```

- [ ] **Step 4: Restore `app/memory_extractor.py` to pure legacy**

Delete `_canonical_enabled`, `_canonical_hint_lines`, `_CORE_FACTS_CANONICAL_ADDON` (moved), the `import hashlib` if now unused, and revert the LLM call to the unconditional form:

```python
        raw = await claude.send_message(
            system_prompt=_CORE_FACTS_SYSTEM,
            history=[],
            user_message=(
                f"User said: {user_message}\n\n"
                f"Companion replied: {ai_response}"
            ),
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
        )
```

(`_parse_fact_array`, `LegacyOutcome`, and everything else stay.)

- [ ] **Step 5: Run + full suite**

Run: `./venv/bin/python -m pytest tests/test_canonical_extractor.py tests/test_prompt_toggle.py -q` (PASS) — then the full suite. `tests/test_shadow_wiring.py` and the gate tests may fail here (they reference moved pieces); that is Task 2/3's job — run them to SEE the failures, and fix only if trivially import-path related.

- [ ] **Step 6: Commit**

```bash
git add app/canonical_extractor.py app/memory_extractor.py tests/test_canonical_extractor.py tests/test_prompt_toggle.py
git commit -m "feat(shadow): dedicated canonical extractor; legacy call unconditional (split fallback)"
```

---

### Task 2: Rewire the shadow path

**Files:**
- Modify: `app/routers/chat.py`
- Test: `tests/test_shadow_wiring.py` (rewrite the affected tests)

**Interfaces:**
- Consumes: `canonical_extractor.canonical_enabled` / `.extract_canonical_candidates`, `LegacyOutcome`.
- Produces: `_extract_and_shadow` runs legacy always; when enabled, runs the canonical call + shadow inside `asyncio.wait_for(SHADOW_TIMEOUT_SECONDS=20.0)`; disabled ⇒ zero canonical-path work (no LLM call, no settings read, no executor).

- [ ] **Step 1: Rewrite `_extract_and_shadow` in `app/routers/chat.py`**

```python
SHADOW_TIMEOUT_SECONDS = 20.0   # now covers the dedicated canonical LLM call


async def _extract_and_shadow(user_id: str, message: str, reply: str, exchange_id: str) -> None:
    """Legacy core-facts write (always, untouched), then — for rollout-enabled
    users only — the dedicated canonical extraction feeding the shadow ledger."""
    try:
        await memory_extractor.extract_and_save_core_facts(user_id, message, reply)
    except Exception as exc:
        _chat_logger.warning("core-facts extraction failed user=%.8s: %r", user_id, exc)
    if not canonical_extractor.canonical_enabled(user_id):
        return  # dormant path: no second call, no settings read, no executor
    try:
        async def _shadow():
            candidates = await canonical_extractor.extract_canonical_candidates(
                user_id, message, reply)
            if not any(isinstance(f, dict) and f.get("canonical") for f in candidates):
                return
            settings = await memory_settings.get_settings(user_id)
            await shadow_ledger.run(
                memory_extractor.LegacyOutcome("canonical", candidates),
                owner_user_id=user_id, exchange_id=exchange_id,
                executor=PostgrestExecutor(), settings=settings)
        await asyncio.wait_for(_shadow(), timeout=SHADOW_TIMEOUT_SECONDS)
    except Exception as exc:
        _chat_logger.warning("shadow ledger skipped user=%.8s exchange=%s: %r",
                             user_id, exchange_id, exc)
```

Add `from app import canonical_extractor` to chat.py's imports. Note the legacy failure no longer aborts the shadow path (the two are now independent — a legacy Supabase blip shouldn't starve the ledger).

- [ ] **Step 2: Rewrite the affected wiring tests**

In `tests/test_shadow_wiring.py`: patch `chat.canonical_extractor.canonical_enabled` and `.extract_canonical_candidates`; assert (a) legacy-then-canonical-then-shadow order with the same `exchange_id`; (b) `canonical_enabled` False ⇒ `extract_canonical_candidates`, `get_settings`, and `shadow_ledger.run` are all never called; (c) enabled but candidates carry no `canonical` ⇒ settings/shadow never called; (d) never raises when everything explodes. Keep the `save_exchange` message-id test as-is.

- [ ] **Step 3: Run + commit**

Run: `./venv/bin/python -m pytest tests/test_shadow_wiring.py -q` then the full suite (clean env).

```bash
git add app/routers/chat.py tests/test_shadow_wiring.py
git commit -m "feat(shadow): wire dedicated canonical call into the shadow path (rollout-gated)"
```

---

### Task 3: Single-arm gate + green gate + finish

**Files:**
- Modify: `scripts/ab_prompt_gate.py`, `tests/test_ab_gate_logic.py`

- [ ] **Step 1:** Add `evaluate_gate_split(new) -> list[tuple]` = the five GATE-B checks PLUS `("parse_failure_abs", new["parse_failure_rate"] <= 0.05, f"{rate:.1%} (<=5% absolute)")`. Rework `main()` to run a SINGLE variant — `canonical_extractor.CANONICAL_EXTRACTION_SYSTEM`, `max_tokens=900` — over the corpus (`--runs`, `--quick` unchanged), evaluate `evaluate_gate_split`, keep per-turn forensics + `gold_misses` + latency reports + results JSON (drop the `old` arm entirely). Delete `evaluate_gate_a` and its tests; keep `compute_metrics`/`evaluate_gate_b` and their tests; add a test for `evaluate_gate_split` (parse-abs fails at 6%+, passes ≤5%).
- [ ] **Step 2:** Verify: gate-logic tests + clean-env full suite + benchmark all green; script imports clean-env.
- [ ] **Step 3:** Commit (`feat(shadow): single-arm canonical gate (regression arm retired by construction)`), then announce and use **superpowers:finishing-a-development-branch**.

---

## Runbook delta (replaces the gate step only — everything else stands)

- Gate command unchanged: `python scripts/ab_prompt_gate.py --runs 2`, run from `artifacts/voice-companion`, **twice**; both must PASS all six single-arm checks. Roughly half the previous cost/time (one variant).
- Expected: the dedicated prompt's canonical metrics are already measured (coverage 91–93.6%, validity 99–100%, gold 91–93%, traps 0, parse 3.3–4.9%) — the gate should confirm, not surprise.
- After double-PASS + benign `gold_misses`: migration 0002 → Republish → allowlist first-light → staged percent, exactly as before. The enabled path now costs one extra background Haiku call per enrolled turn.
