"""
Hearts router — the relationship progression currency.

SQL to run in Supabase SQL Editor:
  CREATE TABLE IF NOT EXISTS user_hearts (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    text NOT NULL,
    amount     integer NOT NULL DEFAULT 1,
    reason     text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
  );
  CREATE INDEX IF NOT EXISTS user_hearts_user_idx ON user_hearts(user_id);

Endpoints:
  GET  /api/hearts        — total hearts + current level for the authenticated user
  POST /api/hearts        — award hearts (requires auth; called by frontend for goal completions)
  POST /api/hearts/internal — award hearts from backend (service-key auth)
"""
import os
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from app.auth_middleware import verify_token
from app.rate_limit import limiter

router = APIRouter()

# Level thresholds: (min_hearts, title)
LEVELS = [
    (0,   "Small Talker"),
    (10,  "Connector"),
    (25,  "Trusted Friend"),
    (50,  "Mentor"),
    (100, "Relationship Master"),
]


def get_level_info(total: int) -> dict:
    title = LEVELS[0][1]
    next_threshold: int | None = LEVELS[1][0]
    for i, (threshold, name) in enumerate(LEVELS):
        if total >= threshold:
            title = name
            next_threshold = LEVELS[i + 1][0] if i + 1 < len(LEVELS) else None
    hearts_to_next = (next_threshold - total) if next_threshold is not None else None
    return {
        "level_title": title,
        "next_threshold": next_threshold,
        "hearts_to_next": hearts_to_next,
    }


def _sb_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


async def _get_total(user_id: str) -> int:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_sb_url()}/rest/v1/user_hearts",
            headers={**_headers(), "Prefer": ""},
            params={"user_id": f"eq.{user_id}", "select": "amount"},
        )
    if resp.status_code not in (200, 206):
        return 0
    rows = resp.json()
    return sum(r.get("amount", 0) for r in rows)


async def award_hearts(user_id: str, amount: int, reason: str) -> None:
    """Internal helper — called by bond_analyzer and goals router."""
    if amount <= 0:
        return
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            f"{_sb_url()}/rest/v1/user_hearts",
            headers=_headers(),
            json={"user_id": user_id, "amount": amount, "reason": reason},
        )


class AwardRequest(BaseModel):
    amount: int = 1
    reason: str


@router.get("")
async def get_hearts(user_id: str = Depends(verify_token)):
    total = await _get_total(user_id)
    level_info = get_level_info(total)
    return {"total_hearts": total, **level_info}


@router.post("", status_code=201)
@limiter.limit("20/minute")
async def post_hearts(request: Request, body: AwardRequest, user_id: str = Depends(verify_token)):
    if body.amount <= 0 or body.amount > 5:
        raise HTTPException(400, "Amount must be 1-5")
    await award_hearts(user_id, body.amount, body.reason)
    total = await _get_total(user_id)
    level_info = get_level_info(total)
    return {"total_hearts": total, **level_info}
