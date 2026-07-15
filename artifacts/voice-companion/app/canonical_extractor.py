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

from app import claude, memory_settings
from app.memory_extractor import (_CORE_FACTS_SYSTEM, _CORE_FACTS_VALID_CATEGORIES,
                                  _parse_fact_array)

logger = logging.getLogger(__name__)


def canonical_enabled(user_id: str) -> bool:
    """Stage-3c rollout: allowlist -> global flag -> percent bucket. Read per call."""
    allow = os.environ.get("CANONICAL_EXTRACTION_ALLOWLIST", "")
    if user_id and user_id in {u.strip() for u in allow.split(",") if u.strip()}:
        return True
    if os.environ.get("CANONICAL_EXTRACTION_ENABLED", "").strip().lower() in ("1", "true", "yes"):
        return True
    try:
        pct = int(os.environ.get("CANONICAL_EXTRACTION_PERCENT", "0"))
    except ValueError:
        return False
    if pct <= 0:
        return False
    bucket = int(hashlib.sha256(user_id.encode()).hexdigest(), 16) % 100
    return bucket < min(pct, 100)


def _canonical_hint_lines() -> str:
    from app.canonical import registry
    lines = []
    for p in registry.EXTRACTION_PREDICATES:
        hint = registry.value_hint(p)
        lines.append(f"  {p}: {hint}" if hint else f"  {p}")
    return "\n".join(lines)


_CORE_FACTS_CANONICAL_ADDON = (
    "\n\nAdditionally, for each fact ALSO include a \"canonical\" key holding an object with: "
    "\"predicate\" (snake_case), \"value_json\" (a small JSON object), "
    "\"confirmation_status\" (only \"explicitly_stated\" if the user said it directly, "
    "else \"inferred\"), and optionally \"valid_from\" / \"observed_at\" as ISO dates when "
    "the user gives timing.\n"
    "Prefer these predicates and value shapes when one fits:\n"
    + _canonical_hint_lines() + "\n"
    "If none fits, use a short snake_case predicate of your own. If you cannot produce a "
    "confident canonical object, omit the \"canonical\" key for that fact — never guess.\n"
    "Attach a \"canonical\" object to every fact the user claims as real for themselves or "
    "for an explicitly identified person in their own life (partner, child, pet). This "
    "INCLUDES the user's own stated goals, personality traits, identity details (pronouns, "
    "handedness), preferences, and past life events — a past home is home_city with "
    "\"valid_from\"/\"valid_until\", a stated goal gets a goal-style predicate.\n"
    "Do NOT attach a canonical object to content the user does not claim as real for "
    "themselves: fantasies and idle wishes (\"I'd love to\", \"maybe someday\"), negations "
    "(\"I'm not\", \"we don't\"), sarcasm, quoted sayings, or statements about unrelated "
    "third parties (coworkers, neighbors, celebrities).\n"
    "IMPORTANT: the canonical decision must never change WHICH facts you return — extract "
    "exactly the same facts array you would without these canonical instructions, and when "
    "a fact does not qualify for a canonical object, include the fact and simply omit its "
    "\"canonical\" key.\n"
    "Respond with the JSON array only. Never add explanations, notes, or any text before or "
    "after the array — when there are no facts at all, output exactly [] and nothing else.\n"
    'Example: [{"category": "location", "fact": "Lives in Easton, Pennsylvania", '
    '"sensitivity": "location", "canonical": {"predicate": "home_city", '
    '"value_json": {"city": "Easton", "state": "Pennsylvania"}, '
    '"confirmation_status": "explicitly_stated"}}]'
)

# Recall mandate: the dedicated extractor serves ONLY the ledger, so unlike the
# shared-prompt era we can push recall hard with zero legacy-behavior risk.
# Gate evidence (2026-07-15): misses cluster in soft categories (goals,
# personality, hobbies, religion/politics, finance, identity, past events).
_RECALL_MANDATE = (
    "\nRECALL MANDATE: you are a dedicated memory extractor — completeness matters as "
    "much as precision. Extract EVERY qualifying self-asserted fact, emphatically "
    "including the commonly under-extracted categories: goals and aspirations the user "
    "states for themselves, hobbies and interests, personality traits, identity details, "
    "financial milestones, religious or political affiliations, and past life events. "
    "A missed real fact is a permanently lost memory. Reserve omission for the excluded "
    "cases above (fantasies and idle wishes, negations, sarcasm, quotations, unrelated "
    "third parties).\n"
)

CANONICAL_EXTRACTION_SYSTEM = _CORE_FACTS_SYSTEM + _CORE_FACTS_CANONICAL_ADDON + _RECALL_MANDATE


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
        return [
            {**f, "sensitivity": (f.get("sensitivity")
                                  if f.get("sensitivity") in memory_settings.SENSITIVITY_TAGS
                                  else "none")}
            for f in items
            if isinstance(f, dict)
            and f.get("category") in _CORE_FACTS_VALID_CATEGORIES
            and isinstance(f.get("fact"), str) and f["fact"].strip()
        ]
    except Exception as exc:
        logger.warning("[canonical_extractor] EXCEPTION user=%.8s: %r", user_id[:8], exc)
        return []
