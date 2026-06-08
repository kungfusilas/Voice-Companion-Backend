"""
Bond Score router.

SQL to run in Supabase SQL Editor:
  CREATE TABLE IF NOT EXISTS bond_scores (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             text NOT NULL,
    persona_id          text NOT NULL,
    session_id          text,
    listening           integer NOT NULL DEFAULT 50,
    empathy             integer NOT NULL DEFAULT 50,
    curiosity           integer NOT NULL DEFAULT 50,
    emotional_regulation integer NOT NULL DEFAULT 50,
    conflict_resolution integer NOT NULL DEFAULT 50,
    follow_through      integer NOT NULL DEFAULT 50,
    humor               integer NOT NULL DEFAULT 50,
    confidence          integer NOT NULL DEFAULT 50,
    bond_score          integer NOT NULL DEFAULT 50,
    created_at          timestamptz NOT NULL DEFAULT now()
  );
  CREATE INDEX IF NOT EXISTS bond_scores_user_idx ON bond_scores(user_id);
  CREATE INDEX IF NOT EXISTS bond_scores_user_time_idx ON bond_scores(user_id, created_at DESC);

Endpoints:
  GET /api/bond-score          — latest scores + history for the current user
"""
import os
from datetime import datetime, timezone
import httpx
from fastapi import APIRouter, Depends, HTTPException
from app.auth_middleware import verify_token

router = APIRouter()

SKILLS = [
    "listening", "empathy", "curiosity", "emotional_regulation",
    "conflict_resolution", "follow_through", "humor", "confidence",
]


def _sb_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


@router.get("")
async def get_bond_score(user_id: str = Depends(verify_token)):
    """
    Returns:
      latest   — the most recent bond_scores row (all 8 skills + bond_score)
      previous — the second most recent row (used to compute skill deltas)
      history  — last 30 bond_score values in chronological order (for sparkline)
      trend    — bond_score delta vs previous record (or None)
    """
    url = f"{_sb_url()}/rest/v1/bond_scores"
    fields = ",".join(["id", "bond_score", "created_at"] + SKILLS)
    params = {
        "user_id": f"eq.{user_id}",
        "order": "created_at.desc",
        "limit": "30",
        "select": fields,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers=_headers(), params=params)

    if resp.status_code not in (200, 206):
        raise HTTPException(500, "Failed to fetch bond scores")

    rows = resp.json()
    if not rows:
        return {"latest": None, "previous": None, "history": [], "trend": None}

    latest = rows[0]
    previous = rows[1] if len(rows) > 1 else None

    # History in chronological order for sparkline
    history = [
        {"bond_score": r["bond_score"], "created_at": r["created_at"]}
        for r in reversed(rows)
    ]

    # Trend vs previous record
    trend = None
    if previous:
        trend = latest["bond_score"] - previous["bond_score"]

    # Monthly trend: compare latest to oldest record this month
    monthly_trend = None
    now = datetime.now(timezone.utc)
    this_month = [
        r for r in rows
        if datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")).month == now.month
        and datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")).year == now.year
    ]
    if len(this_month) >= 2:
        monthly_trend = this_month[0]["bond_score"] - this_month[-1]["bond_score"]

    return {
        "latest": latest,
        "previous": previous,
        "history": history,
        "trend": trend,
        "monthly_trend": monthly_trend,
    }
