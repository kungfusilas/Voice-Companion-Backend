"""
Memory extraction and prompt formatting.

extract_and_save  — fire-and-forget post-chat: Haiku decides what to save,
                    memory.save_memory embeds and stores it in pgvector,
                    plus legacy tagging fields (person_mentioned, emotional_theme,
                    life_event, topic) for future Legacy Mode features.
                    After saving, a secondary Haiku call scores salience
                    (emotional_intensity, specificity, vulnerability) and
                    patches the row in place.
format_memories   — formats retrieved vector memories for system prompt injection.
"""
import json
import os

import httpx

from app import memory
from app import claude

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
        if resp.status_code in (200, 201, 204):
            print(f"[memory_extractor] salience scored: id={memory_id} {salience}")
        else:
            print(f"[memory_extractor] salience PATCH failed: HTTP {resp.status_code} {resp.text[:200]}")

    except Exception as exc:
        print(f"[memory_extractor] _score_salience EXCEPTION: id={memory_id} error={exc!r}")


async def extract_and_save(
    user_id: str,
    persona_id: str,
    user_message: str,
    assistant_reply: str,
) -> None:
    """
    Fire-and-forget: ask Haiku whether this exchange is worth remembering.
    If yes, embed the content with legacy tags and persist to pgvector.
    Then score salience (emotional_intensity, specificity, vulnerability) via
    a second Haiku call and PATCH the row — all wrapped so failures never
    block or slow chat.
    """
    print(f"[memory_extractor] extract_and_save: user={user_id} persona={persona_id} user_msg={user_message[:60]!r}")
    try:
        result = await memory.should_remember(user_message, assistant_reply)
        if result:
            saved = await memory.save_memory(
                user_id=user_id,
                companion_id=persona_id,
                content=result["content"],
                memory_type=result.get("type", "fact"),
                importance=int(result.get("importance", 5)),
                # Legacy Mode tags — extracted silently by Claude alongside the memory
                person_mentioned=result.get("person_mentioned") or None,
                emotional_theme=result.get("emotional_theme") or None,
                life_event=bool(result.get("life_event", False)),
                topic=result.get("topic") or None,
            )
            # Score salience on the saved row — fire-and-forget, never blocks
            memory_id = saved.get("id") if saved else None
            if memory_id:
                await _score_salience(memory_id, result["content"])
        else:
            print(f"[memory_extractor] extract_and_save: nothing to save for user={user_id}")
    except Exception as exc:
        print(f"[memory_extractor] extract_and_save EXCEPTION: user={user_id} persona={persona_id} error={exc!r}")


def format_memories_for_prompt(memories: list[dict]) -> str:
    """
    Format a list of memory dicts (from vector retrieval) into a system prompt block.
    Includes memory_type label so the companion knows the context.
    """
    if not memories:
        return ""
    lines = []
    for m in memories:
        content = m.get("content", "").strip()
        if not content:
            continue
        mtype = m.get("memory_type", "fact")
        lines.append(f"- [{mtype}] {content}")
    if not lines:
        return ""
    return (
        "\n\n## What you remember about this person:\n"
        + "\n".join(lines)
        + "\nUse these memories naturally — weave them into conversation when relevant, "
        "don't just list them. Never say 'I remember that...' robotically. "
        "Reference them the way a close friend would."
    )
