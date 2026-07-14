"""Per-user memory privacy settings + the pure collection gate.

`should_collect` is a pure function (no I/O) so it is unit-tested directly.
Supabase I/O (`get_settings` / `update_settings`) reads/writes
`profiles.memory_settings` (jsonb) and imports httpx lazily so importing this
module — and testing the gate — needs no network dependencies.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Exact sensitivity tag set (see spec). "none" means "not sensitive".
SENSITIVITY_TAGS = frozenset({
    "health", "mental-health", "location", "financial", "sexual",
    "family", "religion-beliefs", "political-views", "none",
})


def should_collect(settings: dict, sensitivity: str, now: datetime | None = None) -> bool:
    """Pure decision: may we save a fact with this sensitivity for this user?

    Rules:
      - collection paused (and not yet expired) -> False
      - sensitivity is in the user's disabled list -> False
      - otherwise -> True
    Callers fail open: an empty/unknown settings dict collects everything.
    """
    now = now or datetime.now(timezone.utc)
    if settings.get("collection_paused"):
        paused_until = settings.get("paused_until")
        if not paused_until:
            return False  # paused indefinitely
        try:
            until = datetime.fromisoformat(str(paused_until).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return False  # unparseable -> treat as paused (safer)
        if now < until:
            return False  # still within the pause window
    if sensitivity in set(settings.get("disabled_sensitivities") or []):
        return False
    return True


def _sb_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _sb_headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


async def get_settings(user_id: str) -> dict:
    """Read profiles.memory_settings. Returns {} on any error so callers fail open."""
    if not _sb_url():
        return {}
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{_sb_url()}/rest/v1/profiles",
                headers=_sb_headers(),
                params={"id": f"eq.{user_id}", "select": "memory_settings", "limit": "1"},
            )
        if resp.status_code == 200 and resp.json():
            return resp.json()[0].get("memory_settings") or {}
    except Exception as exc:
        logger.warning("get_settings failed user=%.8s: %s", user_id, exc)
    return {}


async def update_settings(user_id: str, **fields) -> dict:
    """Merge non-None fields into memory_settings and persist. Returns merged settings."""
    import httpx
    current = await get_settings(user_id)
    current.update({k: v for k, v in fields.items() if v is not None})
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.patch(
            f"{_sb_url()}/rest/v1/profiles",
            headers={**_sb_headers(), "Prefer": "return=minimal"},
            params={"id": f"eq.{user_id}"},
            json={"memory_settings": current},
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"settings update failed (status {resp.status_code})")
    return current
