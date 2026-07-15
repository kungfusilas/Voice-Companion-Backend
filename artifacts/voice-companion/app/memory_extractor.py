"""
Memory extraction and prompt formatting.

extract_and_save  — fire-and-forget post-chat: Haiku decides what to save,
                    memory.save_memory embeds and stores it in pgvector,
                    plus legacy tagging fields (person_mentioned, emotional_theme,
                    life_event, topic) for future Legacy Mode features.
                    After saving, a secondary Haiku call scores salience
                    (emotional_intensity, specificity, vulnerability) and
                    patches the row in place.
format_memories_for_prompt — formats retrieved vector memories for system
                    prompt injection. Content is sanitized to prevent stored
                    prompt injection before being inserted into the system prompt.
"""
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from app import memory
from app import claude

logger = logging.getLogger(__name__)

_SALIENCE_SYSTEM = (
    "You are a memory salience scorer. Given a memory excerpt, score it on three dimensions. "
    "Return ONLY a valid JSON object with exactly these keys (float values 0.0–1.0):\n"
    '{"emotional_intensity": 0.0, "specificity": 0.0, "vulnerability": 0.0}\n\n'
    "Scoring guide:\n"
    "  emotional_intensity — how emotionally charged is this memory? "
    "    (0 = neutral fact, 1 = intense grief/joy/fear/love)\n"
    "  specificity — does it contain named people, dates, places, or concrete details? "
    "    (0 = vague/general, 1 = full of proper nouns and specifics)\n"
    "  vulnerability — how much personal disclosure or self-revelation does it contain? "
    "    (0 = surface-level, 1 = deep personal secret or confession)\n\n"
    "Return ONLY the JSON object — no markdown, no explanation."
)


def _parse_fact_array(raw: str) -> list | None:
    """Parse the LLM's fact array, tolerating code fences and surrounding prose.
    Returns the list, or None if no JSON array can be recovered."""
    cleaned = (raw or "").strip()
    if "```" in cleaned:
        parts = cleaned.split("```")
        cleaned = parts[1] if len(parts) > 1 else parts[0]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, list) else None
    except (ValueError, TypeError):
        pass
    # Fallback: recover the outermost [...] span from prose-wrapped output.
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start != -1 and end > start:
        try:
            data = json.loads(cleaned[start:end + 1])
            return data if isinstance(data, list) else None
        except (ValueError, TypeError):
            return None
    return None


def _sanitize_memory_content(content: str) -> str:
    """
    Sanitize memory content before injection into the system prompt.

    Newlines are the primary attack vector for breaking out of the memory block
    and injecting new system instructions.  We also collapse any sequence of
    whitespace that could form a visual paragraph break.

    This is defence-in-depth: the system prompt already wraps memories in a
    clearly labelled section, but a crafted memory could still inject text that
    looks like a new section header (e.g. "## New Instructions: ...").
    """
    # Replace all newline variants with a single space
    sanitized = content.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    # Collapse multiple spaces into one
    sanitized = re.sub(r" {2,}", " ", sanitized)
    return sanitized.strip()


async def _score_salience(memory_id: str, content: str) -> None:
    """
    Secondary Haiku call: score salience of a saved memory and PATCH the row.
    Fully wrapped in try/except — failure is logged and never propagates.
    """
    try:
        raw = await claude.send_message(
            system_prompt=_SALIENCE_SYSTEM,
            history=[],
            user_message=f"Memory to score:\n\n{content}",
            model="claude-haiku-4-5-20251001",
            max_tokens=128,
        )
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()

        scores = json.loads(cleaned)

        def _clamp(v) -> float:
            return max(0.0, min(1.0, float(v)))

        salience = {
            "emotional_intensity": _clamp(scores.get("emotional_intensity", 0.0)),
            "specificity":         _clamp(scores.get("specificity", 0.0)),
            "vulnerability":       _clamp(scores.get("vulnerability", 0.0)),
        }

        supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        service_key  = os.environ.get("SUPABASE_SERVICE_KEY", "")

        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.patch(
                f"{supabase_url}/rest/v1/memories",
                headers={
                    "Authorization": f"Bearer {service_key}",
                    "apikey": service_key,
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
                params={"id": f"eq.{memory_id}"},
                json={"salience": salience},
            )
        if resp.status_code not in (200, 201, 204):
            logger.warning(
                "[memory_extractor] salience PATCH failed: HTTP %d", resp.status_code
            )
        else:
            logger.debug("[memory_extractor] salience scored: id=%s", memory_id)

    except Exception as exc:
        logger.warning("[memory_extractor] _score_salience EXCEPTION id=%s: %r", memory_id, exc)


async def extract_and_save(
    user_id: str,
    persona_id: str,
    user_message: str,
    assistant_reply: str,
) -> None:
    """
    Fire-and-forget: ask Haiku whether this exchange is worth remembering.
    If yes, sanitize and embed the content with legacy tags, persist to pgvector.
    Then score salience via a second Haiku call and PATCH the row.
    All wrapped so failures never block or slow chat.
    """
    logger.debug(
        "[memory_extractor] extract_and_save: user=%s persona=%s", user_id[:8], persona_id
    )
    try:
        result = await memory.should_remember(user_message, assistant_reply)
        if result:
            # Sanitize the extracted content before persisting — a crafted user
            # message could cause Claude to output injection strings as the memory
            # content, which would then be re-injected into future system prompts.
            raw_content = result.get("content", "")
            safe_content = _sanitize_memory_content(raw_content)
            if not safe_content:
                logger.debug("[memory_extractor] sanitized content is empty, skipping save")
                return

            from app import memory_settings
            sens = (result.get("sensitivity")
                    if result.get("sensitivity") in memory_settings.SENSITIVITY_TAGS else "none")
            settings = await memory_settings.get_settings(user_id)
            if not memory_settings.should_collect(settings, sens):
                logger.debug("[memory_extractor] gated by settings (sens=%s) user=%.8s", sens, user_id[:8])
                return

            saved = await memory.save_memory(
                user_id=user_id,
                companion_id=persona_id,
                content=safe_content,
                memory_type=result.get("type", "fact"),
                importance=int(result.get("importance", 5)),
                person_mentioned=result.get("person_mentioned") or None,
                emotional_theme=result.get("emotional_theme") or None,
                life_event=bool(result.get("life_event", False)),
                topic=result.get("topic") or None,
                sensitivity=sens,
            )
            memory_id = saved.get("id") if saved else None
            if memory_id:
                await _score_salience(memory_id, safe_content)
        else:
            logger.debug("[memory_extractor] extract_and_save: nothing to save for user=%s", user_id[:8])
    except Exception as exc:
        logger.warning(
            "[memory_extractor] extract_and_save EXCEPTION: user=%s: %r", user_id[:8], exc
        )


_CORE_FACTS_SYSTEM = (
    "Extract permanent facts about the user from this conversation turn. "
    "Focus on: family members (names, ages, relationships), job/occupation, "
    "location/city, health conditions, important life events, goals, and personality traits.\n"
    "Return ONLY a JSON array of objects with 'category', 'fact', and 'sensitivity' keys.\n"
    "Valid categories: family, work, location, health, goals, personality, history.\n"
    "Valid sensitivity: health, mental-health, location, financial, sexual, family, "
    "religion-beliefs, political-views, none. Use 'none' if the fact is not sensitive.\n"
    "Include only specific, concrete facts — not opinions or inferences. "
    "If nothing new is revealed, return [].\n"
    'Example: [{"category": "family", "fact": "Daughter named Emma, age 8", "sensitivity": "family"}, '
    '{"category": "work", "fact": "Works as a nurse on night shifts", "sensitivity": "none"}]'
)

_CORE_FACTS_VALID_CATEGORIES = frozenset(
    {"family", "work", "location", "health", "goals", "personality", "history"}
)


def _canonical_enabled(user_id: str) -> bool:
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


@dataclass
class LegacyOutcome:
    status: str
    facts: list[dict] = field(default_factory=list)


async def extract_and_save_core_facts(
    user_id: str,
    user_message: str,
    ai_response: str,
) -> LegacyOutcome:
    """
    Fire-and-forget: extract permanent user facts from a conversation turn and
    upsert them into the user_core_facts Supabase table (max 50 per user).
    Never raises — failures are logged and swallowed.
    """
    parsed: list = []
    try:
        enabled = _canonical_enabled(user_id)
        raw = await claude.send_message(
            system_prompt=(_CORE_FACTS_SYSTEM + _CORE_FACTS_CANONICAL_ADDON
                           if enabled else _CORE_FACTS_SYSTEM),
            history=[],
            user_message=(
                f"User said: {user_message}\n\n"
                f"Companion replied: {ai_response}"
            ),
            model="claude-haiku-4-5-20251001",
            max_tokens=900 if enabled else 400,
        )
        parsed_list = _parse_fact_array(raw)
        if not parsed_list:
            return LegacyOutcome(status="empty", facts=[])
        facts: list = parsed_list

        from app import memory_settings
        facts = [
            {**f, "sensitivity": (
                f.get("sensitivity")
                if f.get("sensitivity") in memory_settings.SENSITIVITY_TAGS else "none"
            )}
            for f in facts
            if isinstance(f, dict)
            and isinstance(f.get("category"), str)
            and f["category"] in _CORE_FACTS_VALID_CATEGORIES
            and isinstance(f.get("fact"), str)
            and f["fact"].strip()
        ]
        parsed = facts
        if not facts:
            return LegacyOutcome(status="empty", facts=parsed)

        settings = await memory_settings.get_settings(user_id)

        supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        service_key  = os.environ.get("SUPABASE_SERVICE_KEY", "")
        if not supabase_url or not service_key:
            return LegacyOutcome(status="gated", facts=parsed)

        base_headers = {
            "Authorization": f"Bearer {service_key}",
            "apikey": service_key,
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=15.0) as http:
            # Fetch existing facts to deduplicate and enforce 50-fact cap
            resp = await http.get(
                f"{supabase_url}/rest/v1/user_core_facts",
                headers=base_headers,
                params={"user_id": f"eq.{user_id}", "select": "category,fact"},
            )
            existing: list = resp.json() if resp.status_code == 200 else []
            if not isinstance(existing, list):
                existing = []

            if len(existing) >= 50:
                return LegacyOutcome(status="capped", facts=parsed)  # hard cap reached

            existing_set: set[tuple[str, str]] = {
                (row["category"], row["fact"].lower().strip())
                for row in existing
                if isinstance(row, dict)
            }

            now = datetime.now(timezone.utc).isoformat()
            to_insert: list[dict] = []
            for item in facts:
                cat       = item["category"]
                fact_text = item["fact"].strip()
                sens      = item.get("sensitivity", "none")
                if not memory_settings.should_collect(settings, sens):
                    continue  # user disabled this sensitivity class or paused collection
                key       = (cat, fact_text.lower())
                if key in existing_set:
                    continue
                to_insert.append({
                    "user_id":     user_id,
                    "category":    cat,
                    "fact":        fact_text,
                    "sensitivity": sens,
                    "confidence":  1.0,
                    "created_at":  now,
                    "updated_at":  now,
                })
                existing_set.add(key)

            if not to_insert:
                return LegacyOutcome(status="duplicate", facts=parsed)

            remaining  = 50 - len(existing)
            to_insert  = to_insert[:remaining]

            await http.post(
                f"{supabase_url}/rest/v1/user_core_facts",
                headers={**base_headers, "Prefer": "return=minimal"},
                json=to_insert,
            )
            logger.debug(
                "[memory_extractor] core_facts saved: user=%s count=%d",
                user_id[:8], len(to_insert),
            )
            return LegacyOutcome(status="inserted", facts=parsed)
    except Exception as exc:
        logger.warning(
            "[memory_extractor] extract_and_save_core_facts EXCEPTION user=%s: %r",
            user_id[:8], exc,
        )
        return LegacyOutcome(status="error", facts=parsed)


def format_memories_for_prompt(memories: list[dict]) -> str:
    """
    Format a list of memory dicts (from vector retrieval) into a system prompt block.

    Each memory's content is sanitized to strip newlines and other characters that
    could be used to break out of the memory section and inject new instructions.
    """
    if not memories:
        return ""
    lines = []
    for m in memories:
        raw_content = m.get("content", "").strip()
        if not raw_content:
            continue
        content = _sanitize_memory_content(raw_content)
        if not content:
            continue
        mtype = m.get("memory_type", "fact")
        lines.append(f"- [{mtype}] {content}")
    if not lines:
        return ""
    return (
        "\n\n## What you remember about this person:\n"
        + "\n".join(lines)
        + "\n---\n"
        "Use these memories naturally — weave them into conversation when relevant, "
        "don't just list them. Never say 'I remember that...' robotically. "
        "Reference them the way a close friend would."
    )
