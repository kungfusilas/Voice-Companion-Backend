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

B-H2 fix: DB-level atomicity via Postgres stored function.
Run this ONCE in the Supabase SQL editor to enable truly atomic appends:

  CREATE OR REPLACE FUNCTION append_conversation_exchange(
    p_session_id   text,
    p_user_id      text,
    p_companion_id text,
    p_messages     jsonb
  ) RETURNS void
  LANGUAGE plpgsql AS $$
  BEGIN
    INSERT INTO conversations (user_id, companion_id, session_id, messages)
    VALUES (p_user_id, p_companion_id, p_session_id, p_messages)
    ON CONFLICT (session_id) DO UPDATE
      SET messages   = conversations.messages || EXCLUDED.messages,
          updated_at = now();
  END;
  $$;

When this function is present, save_exchange calls it via Supabase RPC and the
append is atomic inside a single DB transaction — safe for autoscale deploys.

If the function has not yet been created (RPC returns 404), save_exchange falls
back to a fetch+patch approach. The fallback is correct for single-instance
deploys but has a TOCTOU race window on concurrent writes to the same session.

Design principles:
  - One row per session_id.
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


async def _save_via_rpc(
    client: httpx.AsyncClient,
    user_id: str,
    companion_id: str,
    session_id: str,
    new_msgs: list[dict],
) -> bool:
    """
    Call the append_conversation_exchange Postgres function via Supabase RPC.
    Returns True if the call succeeded, False if the function doesn't exist (404)
    or if any other error occurs.

    The RPC is a single atomic DB transaction: it does INSERT ... ON CONFLICT DO
    UPDATE atomically, eliminating the TOCTOU race of fetch+patch.
    """
    try:
        resp = await client.post(
            f"{_sb_url()}/rest/v1/rpc/append_conversation_exchange",
            headers=_sb_headers(prefer="return=minimal"),
            json={
                "p_session_id": session_id,
                "p_user_id": user_id,
                "p_companion_id": companion_id,
                "p_messages": new_msgs,
            },
        )
        if resp.status_code == 404:
            return False  # function not yet created — fall back
        if resp.status_code in (200, 201, 204):
            return True
        logger.debug(
            "conversation_store: RPC returned unexpected status %d", resp.status_code
        )
        return False
    except Exception as exc:
        logger.debug("conversation_store: RPC call failed: %s", exc)
        return False


async def save_exchange(
    user_id: str,
    companion_id: str,
    session_id: str,
    user_message: str,
    assistant_reply: str,
) -> None:
    """
    Fire-and-forget: append this exchange to the permanent conversation archive.

    Attempts atomic append via the append_conversation_exchange Postgres function
    (requires one-time SQL migration above).  Falls back to fetch+patch if the
    function is not installed.
    """
    try:
        ts = _now_iso()
        new_msgs = [
            {"role": "user",      "content": user_message,    "ts": ts},
            {"role": "assistant", "content": assistant_reply, "ts": ts},
        ]

        async with httpx.AsyncClient(timeout=10) as client:
            # Preferred path: atomic DB-level append via stored function
            if await _save_via_rpc(client, user_id, companion_id, session_id, new_msgs):
                logger.debug("Conversation archived (atomic RPC): session=%s", session_id[:8])
                return

            # Fallback: fetch+patch (TOCTOU risk on concurrent writes to same session)
            existing = await _fetch_session(client, session_id)

            if existing:
                current: list = existing.get("messages") or []
                current.extend(new_msgs)
                await client.patch(
                    f"{_sb_url()}/rest/v1/conversations?session_id=eq.{session_id}",
                    headers=_sb_headers(prefer="return=minimal"),
                    json={"messages": current, "updated_at": ts},
                )
            else:
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

        logger.debug("Conversation archived (fetch+patch fallback): session=%s", session_id[:8])

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
    Returns [{role, content}] sorted oldest-first.
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
                    "limit":        "5",
                },
            )
        if resp.status_code not in (200, 206):
            return []
        rows = resp.json()
        if not rows:
            return []

        all_msgs: list[dict] = []
        for row in rows:
            all_msgs.extend(row.get("messages") or [])
        all_msgs.sort(key=lambda m: m.get("ts", ""))

        return [
            {"role": m["role"], "content": m["content"]}
            for m in all_msgs[-limit:]
        ]
    except Exception as exc:
        logger.debug("get_recent_messages error (non-fatal): %s", exc)
        return []
