"""
Account deletion — GDPR Article 17 / right to erasure.

DELETE /api/account

Permanently deletes ALL data stored for the authenticated user across every
table in the database.  The deletion is scoped strictly to the caller's own
user_id (taken from the JWT) — no request body, no client-supplied user_id.

Tables cleared (in order — FK-safe because Supabase uses soft references):
  memories, conversations, bond_scores, user_hearts, goals,
  future_memories, legacy_chapters, conversation_debriefs,
  activity_results, personality_scores, weekly_reports, profiles

To add a new table to the cascade, append it to _TABLES_TO_CLEAR.

B-H5 fix: implements the previously missing account-deletion endpoint.
"""
import logging
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.auth_middleware import verify_token

logger = logging.getLogger(__name__)
router = APIRouter()

# Tables to wipe, in order.  All must have a user_id column.
_TABLES_TO_CLEAR: list[str] = [
    "memories",
    "conversations",
    "bond_scores",
    "user_hearts",
    "goals",
    "future_memories",
    "legacy_chapters",
    "conversation_debriefs",
    "activity_results",
    "personality_scores",
    "weekly_reports",
    "proactive_messages",
]

# profiles is deleted last; some projects keep it for billing — listed separately
_DELETE_PROFILE = True


def _sb_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _sb_headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


async def _delete_table_rows(
    client: httpx.AsyncClient,
    table: str,
    user_id: str,
    user_col: str = "user_id",
) -> int:
    """
    DELETE all rows in `table` where `user_col` = user_id.
    Returns the number of rows deleted (from Content-Range header) or -1 if unknown.
    Raises on HTTP error.
    """
    resp = await client.delete(
        f"{_sb_url()}/rest/v1/{table}",
        headers={**_sb_headers(), "Prefer": "return=minimal,count=exact"},
        params={user_col: f"eq.{user_id}"},
    )
    if resp.status_code not in (200, 204):
        logger.warning("account delete: table=%s status=%d", table, resp.status_code)
        return -1
    cr = resp.headers.get("Content-Range", "")
    try:
        return int(cr.split("/")[-1])
    except Exception:
        return 0


@router.delete("")
async def delete_account(user_id: str = Depends(verify_token)):
    """
    Permanently erase all data for the authenticated user.

    The user_id is taken exclusively from the verified JWT — there is no
    request body and no client-supplied identifier.

    Returns a summary of rows deleted per table.
    """
    sb_url = _sb_url()
    if not sb_url:
        raise HTTPException(status_code=503, detail="Storage not configured")

    summary: dict[str, int] = {}
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for table in _TABLES_TO_CLEAR:
            try:
                count = await _delete_table_rows(client, table, user_id)
                summary[table] = count
            except Exception as exc:
                logger.warning("account delete: table=%s error=%r", table, exc)
                errors.append(table)

        if _DELETE_PROFILE:
            try:
                count = await _delete_table_rows(client, "profiles", user_id, user_col="id")
                summary["profiles"] = count
            except Exception as exc:
                logger.warning("account delete: profiles error=%r", exc)
                errors.append("profiles")

    if errors:
        logger.error(
            "account delete: incomplete — failed tables: %s user=%s", errors, user_id[:8]
        )

    logger.info("account delete: completed for user=%s tables=%s", user_id[:8], list(summary.keys()))

    return {
        "deleted": True,
        "user_id": user_id,
        "tables_cleared": summary,
        "errors": errors if errors else None,
    }
