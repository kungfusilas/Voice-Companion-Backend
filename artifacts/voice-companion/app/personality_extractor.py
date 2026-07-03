"""
Personality Mapping — Power tier.

Extracts personality signals from each conversation exchange and
incrementally builds a profile stored in profiles.personality_map (JSONB).

Supabase: run once in SQL editor:
    alter table profiles
      add column if not exists personality_map jsonb default '{}'::jsonb;
"""

import os
import json
import logging
import httpx
from datetime import datetime, timezone

from app import claude

logger = logging.getLogger(__name__)

_HAIKU = "claude-haiku-4-5-20251001"

_EMPTY_MAP = {
    "communication_style": {"label": None, "signals": []},
    "attachment_style":    {"label": None, "signals": []},
    "leadership_style":    {"label": None, "signals": []},
    "emotional_triggers":  {"positive": [], "negative": []},
    "conversation_count":  0,
    "last_updated":        None,
}


def _supa_headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


async def _fetch_current_map(user_id: str) -> dict:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not url:
        return dict(_EMPTY_MAP)
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/profiles",
                headers=_supa_headers(),
                params={"id": f"eq.{user_id}", "select": "personality_map", "limit": "1"},
            )
        if resp.status_code == 200 and resp.json():
            raw = resp.json()[0].get("personality_map") or {}
            # Back-fill any missing keys
            merged = dict(_EMPTY_MAP)
            merged.update(raw)
            return merged
    except Exception as e:
        logger.debug("Fetch personality_map failed: %s", e)
    return dict(_EMPTY_MAP)


async def _save_map(user_id: str, personality_map: dict) -> None:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            await client.patch(
                f"{url}/rest/v1/profiles",
                headers=_supa_headers(),
                params={"id": f"eq.{user_id}"},
                json={"personality_map": personality_map},
            )
    except Exception as e:
        logger.debug("Save personality_map failed: %s", e)


def format_personality_for_prompt(pmap: dict) -> str:
    """
    Convert a personality_map dict into a compact plain-language block for
    injection into a Claude system prompt.  Only dimensions that have a label
    set are included; empty/unbuilt dimensions are silently skipped.
    Returns "" when the map has no useful data yet.
    """
    if not pmap or not pmap.get("conversation_count"):
        return ""

    lines: list[str] = []

    cs = pmap.get("communication_style") or {}
    if cs.get("label"):
        sigs = cs.get("signals") or []
        detail = f" ({'; '.join(sigs[:3])})" if sigs else ""
        lines.append(f"- Communication style: {cs['label']}{detail}")

    att = pmap.get("attachment_style") or {}
    if att.get("label"):
        sigs = att.get("signals") or []
        detail = f" ({'; '.join(sigs[:3])})" if sigs else ""
        lines.append(f"- Attachment style: {att['label']}{detail}")

    lead = pmap.get("leadership_style") or {}
    if lead.get("label"):
        sigs = lead.get("signals") or []
        detail = f" ({'; '.join(sigs[:3])})" if sigs else ""
        lines.append(f"- Decisiveness/leadership: {lead['label']}{detail}")

    trig = pmap.get("emotional_triggers") or {}
    pos = trig.get("positive") or []
    neg = trig.get("negative") or []
    if pos:
        lines.append(f"- Energised by: {', '.join(pos[:4])}")
    if neg:
        lines.append(f"- Handle gently (tends to drain them): {', '.join(neg[:4])}")

    if not lines:
        return ""

    return (
        "\n\n## User Personality Profile\n"
        "Observed patterns built from your conversations so far — use these to adapt your tone:\n"
        + "\n".join(lines)
        + "\n"
        "Match your style to theirs and be especially gentle when emotionally draining topics arise."
    )


async def extract_and_update(
    user_id: str,
    user_message: str,
    companion_reply: str,
) -> None:
    """Fire-and-forget: extract signals from one exchange and merge into the profile."""
    try:
        current = await _fetch_current_map(user_id)
        count = int(current.get("conversation_count") or 0)

        # Trim signals to keep prompts short
        def _trim(lst: list, n: int = 5) -> list:
            return lst[-n:] if len(lst) > n else lst

        compact = {
            "communication_style": {
                "label": current["communication_style"].get("label"),
                "signals": _trim(current["communication_style"].get("signals", [])),
            },
            "attachment_style": {
                "label": current["attachment_style"].get("label"),
                "signals": _trim(current["attachment_style"].get("signals", [])),
            },
            "leadership_style": {
                "label": current["leadership_style"].get("label"),
                "signals": _trim(current["leadership_style"].get("signals", [])),
            },
            "emotional_triggers": {
                "positive": _trim(current["emotional_triggers"].get("positive", [])),
                "negative": _trim(current["emotional_triggers"].get("negative", [])),
            },
        }

        prompt = f"""Analyze this conversation exchange and update the personality profile.

User message: "{user_message}"
Companion reply: "{companion_reply}"

Existing profile:
{json.dumps(compact, indent=2)}

Update the profile with any NEW signals observed. Return JSON with exactly these fields:
- communication_style: {{"label": "3-6 word description", "signals": ["observable pattern", ...]}}
- attachment_style: {{"label": "3-6 word description", "signals": ["observable pattern", ...]}}
- leadership_style: {{"label": "3-6 word description", "signals": ["observable pattern", ...]}}
- emotional_triggers: {{"positive": ["thing that energizes them", ...], "negative": ["thing that drains them", ...]}}

Rules:
- Keep existing signals. Add at most 1-2 new ones per field if the exchange shows clear evidence.
- Max 6 signals per field. Max 5 each for positive/negative triggers.
- Labels must reflect the overall pattern, not just this exchange.
- If no signal is observable for a field, keep it unchanged.
- Return ONLY valid JSON."""

        raw = await claude.send_message(
            system_prompt="You are a personality analyst. Return ONLY valid JSON — no markdown, no explanation.",
            history=[],
            user_message=prompt,
            model=_HAIKU,
            max_tokens=500,
        )
        updated = json.loads(raw.strip())

        updated["conversation_count"] = count + 1
        updated["last_updated"] = datetime.now(timezone.utc).isoformat()

        await _save_map(user_id, updated)

    except Exception as e:
        logger.debug("Personality extraction skipped: %s", e)
