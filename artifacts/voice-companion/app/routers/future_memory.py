"""
Future Memory router.

GET  /api/future-memory           — active future memory cards for user
POST /api/future-memory/{id}/act  — mark acted on (awards 1 heart)
POST /api/future-memory/{id}/dismiss — soft-dismiss card
"""
import os
from datetime import date, datetime, timezone, timedelta
import httpx
from fastapi import APIRouter, Depends, HTTPException
from app.auth_middleware import verify_token
from app.routers.hearts import award_hearts

router = APIRouter()

# Surface a gap card if person last mentioned > this many days ago
GAP_DAYS = 21
# Surface date-based cards if target_date within this many days
DATE_WINDOW_DAYS = 90


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


async def _fetch_active(user_id: str) -> list[dict]:
    """Fetch all non-acted, non-dismissed rows for user."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_sb_url()}/rest/v1/future_memories",
            headers=_sb_headers(prefer=""),
            params={
                "user_id": f"eq.{user_id}",
                "acted_on_at": "is.null",
                "dismissed_at": "is.null",
                "select": "id,type,person,description,target_date,last_mentioned,created_at",
                "order": "created_at.asc",
            },
        )
    return resp.json() if resp.status_code in (200, 206) else []


def _enrich(row: dict) -> dict | None:
    """
    Add computed fields and filter by relevance windows.
    Returns None if the card shouldn't surface yet.
    """
    today = date.today()
    now = datetime.now(timezone.utc)
    rtype = row["type"]

    if rtype == "date_based":
        td_str: str | None = row.get("target_date")
        if not td_str:
            return None
        try:
            td = date.fromisoformat(td_str)
        except ValueError:
            return None
        days_until = (td - today).days
        if not (0 <= days_until <= DATE_WINDOW_DAYS):
            return None
        row["days_until"] = days_until
        row["days_since"] = None

    elif rtype == "gap_based":
        lm_str: str | None = row.get("last_mentioned")
        if not lm_str:
            return None
        try:
            lm = datetime.fromisoformat(lm_str.replace("Z", "+00:00"))
            if lm.tzinfo is None:
                lm = lm.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
        days_since = (now - lm).days
        if days_since < GAP_DAYS:
            return None
        row["days_since"] = days_since
        row["days_until"] = None

    elif rtype == "pattern_based":
        row["days_since"] = None
        row["days_until"] = None

    return row


@router.get("")
async def get_future_memories(user_id: str = Depends(verify_token)):
    rows = await _fetch_active(user_id)
    enriched: list[dict] = []
    for row in rows:
        result = _enrich(row)
        if result:
            enriched.append(result)

    # Sort: date_based first (soonest first), then gap_based (longest first), then pattern
    def sort_key(r: dict):
        if r["type"] == "date_based":
            return (0, r.get("days_until") or 999)
        if r["type"] == "gap_based":
            return (1, -(r.get("days_since") or 0))
        return (2, 0)

    enriched.sort(key=sort_key)
    return {"memories": enriched[:5]}


@router.post("/{memory_id}/act", status_code=200)
async def act_on_memory(memory_id: str, user_id: str = Depends(verify_token)):
    async with httpx.AsyncClient(timeout=10) as client:
        # Verify ownership
        resp = await client.get(
            f"{_sb_url()}/rest/v1/future_memories",
            headers=_sb_headers(prefer=""),
            params={"id": f"eq.{memory_id}", "user_id": f"eq.{user_id}", "select": "id", "limit": "1"},
        )
        rows = resp.json() if resp.status_code in (200, 206) else []
        if not rows:
            raise HTTPException(404, "Memory not found")

        await client.patch(
            f"{_sb_url()}/rest/v1/future_memories?id=eq.{memory_id}",
            headers=_sb_headers(),
            json={"acted_on_at": datetime.now(timezone.utc).isoformat()},
        )

    await award_hearts(user_id, 1, "future_memory_acted")
    return {"ok": True}


@router.post("/{memory_id}/dismiss", status_code=200)
async def dismiss_memory(memory_id: str, user_id: str = Depends(verify_token)):
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_sb_url()}/rest/v1/future_memories",
            headers=_sb_headers(prefer=""),
            params={"id": f"eq.{memory_id}", "user_id": f"eq.{user_id}", "select": "id", "limit": "1"},
        )
        rows = resp.json() if resp.status_code in (200, 206) else []
        if not rows:
            raise HTTPException(404, "Memory not found")

        await client.patch(
            f"{_sb_url()}/rest/v1/future_memories?id=eq.{memory_id}",
            headers=_sb_headers(),
            json={"dismissed_at": datetime.now(timezone.utc).isoformat()},
        )

    return {"ok": True}
