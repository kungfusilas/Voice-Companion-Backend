"""
Connection Goals router.

SQL to run in Supabase SQL Editor:
  CREATE TABLE IF NOT EXISTS goals (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     text NOT NULL,
    goal        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
  );
  CREATE INDEX IF NOT EXISTS goals_user_idx ON goals(user_id);

Endpoints:
  GET    /api/goals          — list goals for authenticated user
  POST   /api/goals          — create a new goal
  DELETE /api/goals/{id}     — delete a goal
"""
import os
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.auth_middleware import verify_token

router = APIRouter()


def _sb_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


class GoalCreate(BaseModel):
    goal: str


@router.get("")
async def list_goals(user_id: str = Depends(verify_token)):
    url = f"{_sb_url()}/rest/v1/goals"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            url,
            headers=_headers(),
            params={"user_id": f"eq.{user_id}", "order": "created_at.asc"},
        )
    if resp.status_code not in (200, 206):
        raise HTTPException(500, "Failed to fetch goals")
    return {"goals": resp.json()}


@router.post("", status_code=201)
async def create_goal(body: GoalCreate, user_id: str = Depends(verify_token)):
    if not body.goal.strip():
        raise HTTPException(400, "Goal cannot be empty")
    url = f"{_sb_url()}/rest/v1/goals"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            url,
            headers=_headers(),
            json={"user_id": user_id, "goal": body.goal.strip()},
        )
    if resp.status_code not in (200, 201):
        raise HTTPException(500, "Failed to create goal")
    rows = resp.json()
    return rows[0] if rows else {}


@router.delete("/{goal_id}", status_code=204)
async def delete_goal(goal_id: str, user_id: str = Depends(verify_token)):
    url = f"{_sb_url()}/rest/v1/goals"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.delete(
            url,
            headers=_headers(),
            params={"id": f"eq.{goal_id}", "user_id": f"eq.{user_id}"},
        )
    if resp.status_code not in (200, 204):
        raise HTTPException(500, "Failed to delete goal")
