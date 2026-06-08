"""
Conversation store — permanently archives every conversation exchange in Supabase.
This is the foundational data layer for Legacy Mode.

SQL to run in Supabase SQL Editor:
  CREATE TABLE IF NOT EXISTS conversations (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      text NOT NULL,
    companion_id text NOT NULL,
    session_id   text NOT NULL,
    messages     jsonb NOT NULL DEFAULT '[]',
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
  );
  CREATE INDEX IF NOT EXISTS conversations_user_idx ON conversations(user_id, companion_id);
  CREATE UNIQUE INDEX IF NOT EXISTS conversations_session_idx ON conversations(session_id);

Design principles:
  - One row per session_id (upserted — first exchange inserts, subsequent ones append).
  - messages is a jsonb array: [{role, content, ts}]
  - Rows are NEVER deleted — this is the permanent archive.
  - All writes are fire-and-forget; errors are swallowed silently.
"""
import os
import json
import logging
from datetime import datetime, timezone
import httpx

logger = logging.getLogger(__name__)


def _sb_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _sb_headers(prefer: str = "return=representation") -> dict:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _fetch_session(client: httpx.AsyncClient, session_id: str) -> dict | None:
    resp = await client.get(
        f"{_sb_url()}/rest/v1/conversations",
        headers=_sb_headers(prefer=""),
        params={"session_id": f"eq.{session_id}", "select": "id,messages", "limit": "1"},
    )
    if resp.status_code in (200, 206):
        rows = resp.json()
        return rows[0] if rows else None
    return None


async def save_exchange(
    user_id: str,
    companion_id: str,
    session_id: str,
    user_message: str,
    assistant_reply: str,
) -> None:
    """
    Fire-and-forget: append this exchange to the permanent conversation archive.
    Inserts a new session row on first exchange; appends on subsequent ones.
    """
    try:
        ts = _now_iso()
        new_msgs = [
            {"role": "user",      "content": user_message,    "ts": ts},
            {"role": "assistant", "content": assistant_reply, "ts": ts},
        ]

        async with httpx.AsyncClient(timeout=10) as client:
            existing = await _fetch_session(client, session_id)

            if existing:
                # Append to existing messages array
                current: list = existing.get("messages") or []
                current.extend(new_msgs)
                await client.patch(
                    f"{_sb_url()}/rest/v1/conversations?session_id=eq.{session_id}",
                    headers=_sb_headers(prefer="return=minimal"),
                    json={"messages": current, "updated_at": ts},
                )
            else:
                # First exchange in this session — insert
                await client.post(
                    f"{_sb_url()}/rest/v1/conversations",
                    headers=_sb_headers(prefer="return=minimal"),
                    json={
                        "user_id":      user_id,
                        "companion_id": companion_id,
                        "session_id":   session_id,
                        "messages":     new_msgs,
                    },
                )

        logger.debug("Conversation archived: session=%s", session_id[:8])

    except Exception as exc:
        logger.debug("Conversation store error (non-fatal): %s", exc)
