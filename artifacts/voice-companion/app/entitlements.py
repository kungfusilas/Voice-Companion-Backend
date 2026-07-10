"""
entitlements.py — LegacyBond AI

Session and memory cap enforcement per subscription tier.

Supabase table required (run once in Supabase SQL Editor):

  CREATE TABLE IF NOT EXISTS user_entitlements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    plan TEXT NOT NULL DEFAULT 'free',
    sessions_used INTEGER DEFAULT 0,
    period_start TIMESTAMPTZ DEFAULT NOW(),
    current_session_messages INTEGER DEFAULT 0,
    bonus_sessions INTEGER DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id)
  );

  CREATE OR REPLACE FUNCTION update_updated_at_column()
  RETURNS TRIGGER AS $$
  BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
  $$ language 'plpgsql';

  CREATE TRIGGER update_user_entitlements_updated_at
    BEFORE UPDATE ON user_entitlements
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

  ALTER TABLE user_entitlements ENABLE ROW LEVEL SECURITY;
  CREATE POLICY "Users can read own entitlements" ON user_entitlements
    FOR SELECT USING (auth.uid() = user_id);

  -- Atomic counter RPCs (avoid read-then-write races).
  -- Service-role only: EXECUTE is revoked from client roles so users cannot
  -- mutate other users' counters (the backend calls these with the service key).
  CREATE OR REPLACE FUNCTION entitlements_start_session(p_user_id uuid)
  RETURNS integer AS $$
    UPDATE user_entitlements
    SET sessions_used = sessions_used + 1, current_session_messages = 0
    WHERE user_id = p_user_id
    RETURNING sessions_used;
  $$ LANGUAGE sql;
  REVOKE EXECUTE ON FUNCTION entitlements_start_session(uuid) FROM anon, authenticated, public;
  GRANT EXECUTE ON FUNCTION entitlements_start_session(uuid) TO service_role;

  CREATE OR REPLACE FUNCTION entitlements_increment_message(p_user_id uuid)
  RETURNS integer AS $$
    UPDATE user_entitlements
    SET current_session_messages = current_session_messages + 1
    WHERE user_id = p_user_id
    RETURNING current_session_messages;
  $$ LANGUAGE sql;
  REVOKE EXECUTE ON FUNCTION entitlements_increment_message(uuid) FROM anon, authenticated, public;
  GRANT EXECUTE ON FUNCTION entitlements_increment_message(uuid) TO service_role;

All Supabase access uses the async httpx REST pattern (service key) used
throughout this app. Every check FAILS OPEN: if the table is missing or a
request errors, users are never blocked (matches billing guardrails).
"""
import logging
import os
from datetime import datetime, timezone

import httpx

logger = logging.getLogger("uvicorn.error")

# Tier limits. `elite` mirrors `power` (highest defined tier limits).
TIER_LIMITS = {
    "free":    {"sessions": 15,  "period_days": 7,  "messages": 25,  "max_facts": 25},
    "basic":   {"sessions": 80,  "period_days": 30, "messages": 50,  "max_facts": 100},
    "premium": {"sessions": 150, "period_days": 30, "messages": 75,  "max_facts": 500},
    "power":   {"sessions": 250, "period_days": 30, "messages": 100, "max_facts": 2000},
    "elite":   {"sessions": 250, "period_days": 30, "messages": 100, "max_facts": 2000},
}

_TIMEOUT = 6.0


def get_limits(plan: str) -> dict:
    return TIER_LIMITS.get(plan, TIER_LIMITS["free"])


def _sb_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _sb_key() -> str:
    return os.environ.get("SUPABASE_SERVICE_KEY", "")


def _headers(prefer: str = "return=minimal") -> dict:
    key = _sb_key()
    h = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h


def _configured() -> bool:
    return bool(_sb_url() and _sb_key())


def _parse_rpc_int(resp: httpx.Response) -> int | None:
    """Parse a PostgREST RPC response into an int, handling scalar/array/object shapes."""
    try:
        data = resp.json()
    except ValueError:
        return None
    if isinstance(data, list):
        data = data[0] if data else None
    if isinstance(data, dict):
        for v in data.values():
            data = v
            break
    try:
        return int(data)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None


async def get_or_create_entitlement(user_id: str, plan: str) -> dict | None:
    """Fetch entitlement row, create if missing, reset if period expired.

    Returns None on any backend failure (callers must fail open).
    """
    if not _configured():
        return None
    base = f"{_sb_url()}/rest/v1/user_entitlements"
    now = datetime.now(timezone.utc)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                base,
                headers=_headers(prefer=""),
                params={"user_id": f"eq.{user_id}", "select": "*", "limit": "1"},
            )
            if resp.status_code == 404:
                # Table not created yet — fail open.
                logger.warning("entitlements: user_entitlements table missing — failing open")
                return None
            if resp.status_code not in (200, 206):
                logger.warning("entitlements: fetch failed status=%s", resp.status_code)
                return None
            rows = resp.json() or []
            if not rows:
                row = {
                    "user_id": user_id,
                    "plan": plan,
                    "sessions_used": 0,
                    "period_start": now.isoformat(),
                    "current_session_messages": 0,
                    "bonus_sessions": 0,
                }
                ins = await client.post(base, headers=_headers(), json=row)
                if ins.status_code not in (200, 201):
                    logger.warning("entitlements: insert failed status=%s", ins.status_code)
                    return None
                return row

            row = rows[0]
            limits = get_limits(plan)
            updates: dict = {}
            try:
                period_start = datetime.fromisoformat(
                    str(row.get("period_start", "")).replace("Z", "+00:00")
                )
                if (now - period_start).days >= limits["period_days"]:
                    updates.update({"sessions_used": 0, "period_start": now.isoformat()})
                    row["sessions_used"] = 0
                    row["period_start"] = now.isoformat()
            except (ValueError, TypeError):
                # Unparseable period_start — fail open, don't reset.
                logger.warning("entitlements: unparseable period_start user=%s", user_id[:8])

            if row.get("plan") != plan:
                updates["plan"] = plan
                row["plan"] = plan

            if updates:
                await client.patch(
                    f"{base}?user_id=eq.{user_id}", headers=_headers(), json=updates
                )
            return row
    except Exception as e:
        logger.warning("entitlements: get_or_create error user=%s err=%s", user_id[:8], e)
        return None


async def check_session_allowed(user_id: str, plan: str) -> dict:
    """Returns {'allowed': bool, 'reason': str, 'used': int, 'limit': int}. Fails open."""
    row = await get_or_create_entitlement(user_id, plan)
    limits = get_limits(plan)
    if row is None:
        return {"allowed": True, "used": 0, "limit": limits["sessions"]}
    total_allowed = limits["sessions"] + int(row.get("bonus_sessions") or 0)
    used = int(row.get("sessions_used") or 0)
    if used >= total_allowed:
        return {"allowed": False, "reason": "session_limit", "used": used, "limit": total_allowed}
    return {"allowed": True, "used": used, "limit": total_allowed}


async def increment_session(user_id: str) -> None:
    """Call when a new session starts. Increments sessions_used, resets message count.

    Uses an atomic SQL RPC when available; falls back to read-then-write.
    """
    if not _configured():
        return
    base = f"{_sb_url()}/rest/v1/user_entitlements"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            rpc = await client.post(
                f"{_sb_url()}/rest/v1/rpc/entitlements_start_session",
                headers=_headers(prefer=""),
                json={"p_user_id": user_id},
            )
            if rpc.status_code in (200, 201, 204):
                return
            # RPC not installed yet — non-atomic fallback
            resp = await client.get(
                base,
                headers=_headers(prefer=""),
                params={"user_id": f"eq.{user_id}", "select": "sessions_used", "limit": "1"},
            )
            rows = resp.json() if resp.status_code in (200, 206) else []
            if not rows:
                return
            current = int(rows[0].get("sessions_used") or 0)
            await client.patch(
                f"{base}?user_id=eq.{user_id}",
                headers=_headers(),
                json={"sessions_used": current + 1, "current_session_messages": 0},
            )
    except Exception as e:
        logger.warning("entitlements: increment_session error user=%s err=%s", user_id[:8], e)


async def increment_message(user_id: str) -> dict:
    """Call on each user message.

    Returns {'allowed': bool, 'messages_used': int, 'limit': int}. Fails open.
    """
    if not _configured():
        return {"allowed": True, "messages_used": 0, "limit": 999}
    base = f"{_sb_url()}/rest/v1/user_entitlements"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            # Need the plan for the limit regardless of increment path.
            resp = await client.get(
                base,
                headers=_headers(prefer=""),
                params={"user_id": f"eq.{user_id}", "select": "plan,current_session_messages", "limit": "1"},
            )
            rows = resp.json() if resp.status_code in (200, 206) else []
            if not rows:
                return {"allowed": True, "messages_used": 0, "limit": 999}
            row = rows[0]
            plan = row.get("plan") or "free"
            limits = get_limits(plan)

            rpc = await client.post(
                f"{_sb_url()}/rest/v1/rpc/entitlements_increment_message",
                headers=_headers(prefer=""),
                json={"p_user_id": user_id},
            )
            if 200 <= rpc.status_code < 300:
                # RPC succeeded and already incremented — its result is
                # authoritative. Never run the fallback after a 2xx.
                new_count = _parse_rpc_int(rpc)
                if new_count is None:
                    new_count = int(row.get("current_session_messages") or 0) + 1
            else:
                # RPC not installed yet — non-atomic fallback
                new_count = int(row.get("current_session_messages") or 0) + 1
                await client.patch(
                    f"{base}?user_id=eq.{user_id}",
                    headers=_headers(),
                    json={"current_session_messages": new_count},
                )
            # Allow exactly `limit` messages; block starting at limit + 1.
            if new_count > limits["messages"]:
                return {"allowed": False, "messages_used": new_count, "limit": limits["messages"]}
            return {"allowed": True, "messages_used": new_count, "limit": limits["messages"]}
    except Exception as e:
        logger.warning("entitlements: increment_message error user=%s err=%s", user_id[:8], e)
        return {"allowed": True, "messages_used": 0, "limit": 999}


async def get_plan(user_id: str) -> str:
    """Read the user's subscription tier from profiles. Fails open to 'free'."""
    if not _configured():
        return "free"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_sb_url()}/rest/v1/profiles",
                headers=_headers(prefer=""),
                params={"id": f"eq.{user_id}", "select": "subscription_tier", "limit": "1"},
            )
            rows = resp.json() if resp.status_code in (200, 206) else []
            if rows and rows[0].get("subscription_tier"):
                return str(rows[0]["subscription_tier"])
    except Exception:
        pass
    return "free"


async def check_facts_allowed(user_id: str, plan: str) -> bool:
    """True if the user can store more core facts. Fails open (True) on errors."""
    if not _configured():
        return True
    limits = get_limits(plan)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_sb_url()}/rest/v1/user_core_facts",
                headers={**_headers(prefer="count=exact"), "Range": "0-0"},
                params={"user_id": f"eq.{user_id}", "select": "id"},
            )
            if resp.status_code not in (200, 206):
                return True
            content_range = resp.headers.get("content-range", "")
            if "/" in content_range:
                count = int(content_range.split("/")[-1])
                return count < limits["max_facts"]
    except Exception:
        pass
    return True
