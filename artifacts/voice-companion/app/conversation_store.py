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


async def get_session_info(session_id: str) -> dict | None:
    """
    Fetch a single session row from Supabase by session_id.
    Returns {user_id, companion_id, messages: [{role, content}]} or None if not found.
    Used for warm-boot recovery after a server restart and by the sessions API.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{_sb_url()}/rest/v1/conversations",
                headers=_sb_headers(prefer=""),
                params={
                    "session_id": f"eq.{session_id}",
                    "select": "user_id,companion_id,messages",
                    "limit": "1",
                },
            )
        if resp.status_code not in (200, 206):
            return None
        rows = resp.json()
        if not rows:
            return None
        row = rows[0]
        msgs = row.get("messages") or []
        msgs.sort(key=lambda m: m.get("ts", ""))
        return {
            "user_id": row.get("user_id", ""),
            "companion_id": row.get("companion_id", ""),
            "messages": [{"role": m["role"], "content": m["content"]} for m in msgs],
        }
    except Exception as exc:
        logger.debug("get_session_info error (non-fatal): %s", exc)
        return None


async def get_recent_messages(
    user_id: str,
    companion_id: str,
    limit: int = 20,
) -> list[dict]:
    """
    Return the most recent `limit` messages across all sessions for a user+companion pair.
    Returns [{role, content}] sorted oldest-first — ready to seed the in-memory store
    or display in the frontend.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{_sb_url()}/rest/v1/conversations",
                headers=_sb_headers(prefer=""),
                params={
                    "user_id":      f"eq.{user_id}",
                    "companion_id": f"eq.{companion_id}",
                    "select":       "messages",
                    "order":        "updated_at.desc",
                    "limit":        "5",        # last 5 sessions max
                },
            )
        if resp.status_code not in (200, 206):
            return []
        rows = resp.json()
        if not rows:
            return []

        # Flatten all messages from the returned sessions, sort by timestamp
        all_msgs: list[dict] = []
        for row in rows:
            all_msgs.extend(row.get("messages") or [])
        all_msgs.sort(key=lambda m: m.get("ts", ""))

        # Take the last `limit` messages and strip to just role+content
        return [
            {"role": m["role"], "content": m["content"]}
            for m in all_msgs[-limit:]
        ]
    except Exception as exc:
        logger.debug("get_recent_messages error (non-fatal): %s", exc)
        return []
