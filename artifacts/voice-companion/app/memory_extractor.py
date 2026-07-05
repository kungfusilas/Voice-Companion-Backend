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
import json
import logging
import os
import re

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
