"""
Future Memory extractor — runs fire-and-forget after every chat exchange.

Extracts from the conversation:
  • Dates    → future_memories rows of type 'date_based'
  • People   → future_memories rows of type 'gap_based' (upserted, last_mentioned refreshed)
  • Patterns → future_memories rows of type 'pattern_based'

SQL to run in Supabase SQL Editor:
  CREATE TABLE IF NOT EXISTS future_memories (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        text NOT NULL,
    type           text NOT NULL CHECK (type IN ('date_based','gap_based','pattern_based')),
    person         text,
    description    text NOT NULL,
    target_date    date,
    last_mentioned timestamptz DEFAULT now(),
    created_at     timestamptz NOT NULL DEFAULT now(),
    acted_on_at    timestamptz,
    dismissed_at   timestamptz
  );
  CREATE INDEX IF NOT EXISTS future_memories_user_idx ON future_memories(user_id);
"""
import os
import json
import logging
from datetime import date, timedelta
import httpx
import anthropic

logger = logging.getLogger(__name__)

_SYSTEM = """You are a relationship intelligence system analyzing a single conversation exchange.

Today's date: {today}

Your task: extract structured data about important dates, people, and patterns from the user's message.

Return ONLY a valid JSON object — nothing else:
{{
  "dates": [
    {{
      "person": "first name or null",
      "description": "warm, personal one-sentence description (e.g. 'Your daughter starts kindergarten')",
      "target_date": "YYYY-MM-DD or null if no specific date can be determined",
      "days_from_now": null or integer (if a relative time was mentioned, e.g. 'in 3 months' = 90)
    }}
  ],
  "people": [
    {{
      "name": "first name or nickname",
      "relationship": "friend/partner/parent/sibling/colleague/child/etc",
      "context": "one phrase describing how they came up"
    }}
  ],
  "patterns": [
    {{
      "person": "first name or null",
      "description": "warm one-sentence description of the recurring pattern (e.g. 'You usually check in with your sister weekly')",
      "frequency": "daily/weekly/monthly"
    }}
  ]
}}

Rules:
- Only extract information clearly stated by the USER, never infer or invent
- dates: only include upcoming events with meaningful dates (past events don't count)
- dates: if a relative date is given (e.g. 'next month', 'in 6 weeks'), compute target_date from today
- people: include everyone the user mentions by name (first name or nickname only)
- patterns: only include genuine recurring habits the user explicitly describes
- Return empty arrays [] if nothing applicable is found
- Keep descriptions warm, personal, and second-person (e.g. 'Your...' not 'The user's...')"""


def _sb_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _sb_headers(prefer: str = "return=minimal") -> dict:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }


async def _call_claude(user_message: str, assistant_reply: str) -> dict:
    today = date.today().isoformat()
    client = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    prompt = f'User said: "{user_message}"\n\nCompanion replied: "{assistant_reply[:300]}"'
    msg = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        system=_SYSTEM.format(today=today),
        messages=[{"role": "user", "content": prompt}],
    )
    return json.loads(msg.content[0].text.strip())


async def _insert(client: httpx.AsyncClient, row: dict) -> None:
    await client.post(
        f"{_sb_url()}/rest/v1/future_memories",
        headers=_sb_headers(),
        json=row,
    )


async def _get_person_row(client: httpx.AsyncClient, user_id: str, name: str) -> dict | None:
    resp = await client.get(
        f"{_sb_url()}/rest/v1/future_memories",
        headers=_sb_headers(prefer=""),
        params={
            "user_id": f"eq.{user_id}",
            "type": "eq.gap_based",
            "person": f"ilike.{name}",
            "select": "id",
            "limit": "1",
        },
    )
    rows = resp.json() if resp.status_code in (200, 206) else []
    return rows[0] if rows else None


async def _upsert_person(client: httpx.AsyncClient, user_id: str, name: str, relationship: str, context: str) -> None:
    existing = await _get_person_row(client, user_id, name)
    if existing:
        # Refresh last_mentioned
        await client.patch(
            f"{_sb_url()}/rest/v1/future_memories?id=eq.{existing['id']}",
            headers=_sb_headers(),
            json={"last_mentioned": "now()"},
        )
    else:
        desc = f"Your {relationship} {name} was part of your conversation"
        await _insert(client, {
            "user_id": user_id,
            "type": "gap_based",
            "person": name,
            "description": desc,
        })


async def extract_and_save(
    user_id: str,
    _persona_id: str,
    user_message: str,
    assistant_reply: str,
) -> None:
    """
    Fire-and-forget: extract future memory signals from this exchange and persist.
    Errors are silently swallowed — never blocks chat.
    """
    try:
        extracted = await _call_claude(user_message, assistant_reply)
        today = date.today()

        async with httpx.AsyncClient(timeout=15) as client:
            # ── Date-based ────────────────────────────────────────────────
            for item in extracted.get("dates", []):
                td: str | None = item.get("target_date")
                daysfw: int | None = item.get("days_from_now")
                if not td and daysfw is not None:
                    td = (today + timedelta(days=int(daysfw))).isoformat()
                if not td:
                    continue  # no usable date
                desc = item.get("description", "").strip()
                if not desc:
                    continue
                await _insert(client, {
                    "user_id": user_id,
                    "type": "date_based",
                    "person": item.get("person"),
                    "description": desc,
                    "target_date": td,
                })

            # ── Gap-based (people) ─────────────────────────────────────
            for person in extracted.get("people", []):
                name = (person.get("name") or "").strip()
                if not name or name.lower() in ("i", "me", "you", "we"):
                    continue
                rel = person.get("relationship", "person")
                ctx = person.get("context", "")
                await _upsert_person(client, user_id, name, rel, ctx)

            # ── Pattern-based ─────────────────────────────────────────
            for patt in extracted.get("patterns", []):
                desc = (patt.get("description") or "").strip()
                if not desc:
                    continue
                await _insert(client, {
                    "user_id": user_id,
                    "type": "pattern_based",
                    "person": patt.get("person"),
                    "description": desc,
                })

        logger.info("Future memory extracted: user=%s", user_id[:8])

    except Exception as exc:
        logger.debug("Future memory extractor error (non-fatal): %s", exc)
