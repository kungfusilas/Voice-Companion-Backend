"""
Account deletion — GDPR Article 17 / right to erasure.

DELETE /api/account

Permanently deletes ALL data stored for the authenticated user across every
table in the database, the user's vault storage objects, their Stripe
subscription, and the Supabase auth user itself. The deletion is scoped strictly
to the caller's own user_id (taken from the JWT) — no request body, no
client-supplied user_id.

To add a new user-scoped table to the cascade, append it to _TABLES_TO_CLEAR.

B-H5 fix: implements the previously missing account-deletion endpoint.
Hardening: previously omitted the vault tables (vault_sessions, vault_files,
legacy_recipients), messages, push_subscriptions, relationship_*, user_core_facts,
user_entitlements, user_milestones, the storage blobs, the Stripe subscription,
and the auth user — all of which now get cleaned up.
"""
import asyncio
import logging
import os

import httpx
import stripe
from fastapi import APIRouter, Depends, HTTPException

from app.auth_middleware import verify_token

logger = logging.getLogger(__name__)
router = APIRouter()

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")

# Tables to wipe. Each entry is (table, user_column). All confirmed to exist and
# carry the given per-user column. profiles is handled separately (keyed on `id`)
# and deleted last so the Stripe customer id is available beforehand.
_TABLES_TO_CLEAR: list[tuple[str, str]] = [
    ("memories", "user_id"),
    ("conversations", "user_id"),
    ("messages", "user_id"),
    ("bond_scores", "user_id"),
    ("user_hearts", "user_id"),
    ("goals", "user_id"),
    ("future_memories", "user_id"),
    ("legacy_chapters", "user_id"),
    ("legacy_recipients", "user_id"),
    ("conversation_debriefs", "user_id"),
    ("weekly_reports", "user_id"),
    ("relationship_profiles", "user_id"),
    ("relationship_sessions", "user_id"),
    ("relationship_stats", "user_id"),
    ("user_core_facts", "user_id"),
    ("user_entitlements", "user_id"),
    ("user_milestones", "user_id"),
    ("push_subscriptions", "user_id"),
    ("vault_sessions", "user_id"),
    ("vault_files", "user_id"),
]

_VAULT_BUCKET = "vault-files"


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
    """DELETE all rows in `table` where `user_col` = user_id.
    Returns the number of rows deleted (from Content-Range) or -1 if unknown.
    """
    resp = await client.delete(
        f"{_sb_url()}/rest/v1/{table}",
        headers={**_sb_headers(), "Prefer": "return=minimal,count=exact"},
        params={user_col: f"eq.{user_id}"},
    )
    if resp.status_code not in (200, 204):
        logger.warning("account delete: table=%s status=%d body=%s", table, resp.status_code, resp.text[:200])
        return -1
    cr = resp.headers.get("Content-Range", "")
    try:
        return int(cr.split("/")[-1])
    except Exception:
        return 0


async def _get_stripe_customer_id(client: httpx.AsyncClient, user_id: str) -> str | None:
    try:
        resp = await client.get(
            f"{_sb_url()}/rest/v1/profiles",
            headers={**_sb_headers(), "Prefer": ""},
            params={"id": f"eq.{user_id}", "select": "stripe_customer_id", "limit": "1"},
        )
        if resp.status_code == 200 and resp.json():
            return resp.json()[0].get("stripe_customer_id")
    except Exception as exc:
        logger.warning("account delete: could not read stripe_customer_id: %r", exc)
    return None


async def _cancel_stripe(customer_id: str) -> None:
    """Cancel all of the customer's subscriptions so they stop being billed."""
    if not stripe.api_key or not customer_id:
        return
    subs = await asyncio.to_thread(stripe.Subscription.list, customer=customer_id, status="all")
    for sub in subs.auto_paging_iter():
        if sub.get("status") in ("canceled", "incomplete_expired"):
            continue
        await asyncio.to_thread(stripe.Subscription.cancel, sub.id)


async def _delete_vault_storage(client: httpx.AsyncClient, user_id: str) -> int:
    """Delete every object under vault/<user_id>/ in the vault-files bucket."""
    prefix = f"vault/{user_id}"
    list_resp = await client.post(
        f"{_sb_url()}/storage/v1/object/list/{_VAULT_BUCKET}",
        headers=_sb_headers(),
        json={"prefix": prefix, "limit": 1000},
    )
    if list_resp.status_code != 200:
        logger.warning("account delete: storage list status=%d", list_resp.status_code)
        return -1
    names = [f"{prefix}/{o['name']}" for o in list_resp.json() if o.get("name")]
    if not names:
        return 0
    del_resp = await client.request(
        "DELETE",
        f"{_sb_url()}/storage/v1/object/{_VAULT_BUCKET}",
        headers=_sb_headers(),
        json={"prefixes": names},
    )
    if del_resp.status_code not in (200, 204):
        logger.warning("account delete: storage remove status=%d", del_resp.status_code)
        return -1
    return len(names)


async def _delete_auth_user(client: httpx.AsyncClient, user_id: str) -> bool:
    """Delete the Supabase auth user so they can no longer log in."""
    resp = await client.delete(
        f"{_sb_url()}/auth/v1/admin/users/{user_id}",
        headers=_sb_headers(),
    )
    if resp.status_code not in (200, 204):
        logger.warning("account delete: auth user delete status=%d body=%s", resp.status_code, resp.text[:200])
        return False
    return True


@router.delete("")
async def delete_account(user_id: str = Depends(verify_token)):
    """
    Permanently erase all data for the authenticated user. The user_id is taken
    exclusively from the verified JWT — there is no request body.

    Returns a per-table summary plus a `complete` flag indicating whether every
    step succeeded.
    """
    sb_url = _sb_url()
    if not sb_url:
        raise HTTPException(status_code=503, detail="Storage not configured")

    summary: dict[str, int] = {}
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Cancel billing BEFORE deleting the profile (needs stripe_customer_id).
        customer_id = await _get_stripe_customer_id(client, user_id)
        if customer_id:
            try:
                await _cancel_stripe(customer_id)
            except Exception as exc:
                logger.warning("account delete: stripe cancel error=%r", exc)
                errors.append("stripe")

        # 2. Delete vault storage blobs.
        try:
            summary["_storage_objects"] = await _delete_vault_storage(client, user_id)
            if summary["_storage_objects"] < 0:
                errors.append("storage")
        except Exception as exc:
            logger.warning("account delete: storage error=%r", exc)
            errors.append("storage")

        # 3. Delete all user-scoped table rows.
        for table, user_col in _TABLES_TO_CLEAR:
            try:
                count = await _delete_table_rows(client, table, user_id, user_col=user_col)
                summary[table] = count
                if count < 0:
                    errors.append(table)
            except Exception as exc:
                logger.warning("account delete: table=%s error=%r", table, exc)
                errors.append(table)

        # 4. Delete the profile row (keyed on id, not user_id).
        try:
            count = await _delete_table_rows(client, "profiles", user_id, user_col="id")
            summary["profiles"] = count
            if count < 0:
                errors.append("profiles")
        except Exception as exc:
            logger.warning("account delete: profiles error=%r", exc)
            errors.append("profiles")

        # 5. Delete the auth user itself (last — after all their data is gone).
        try:
            if not await _delete_auth_user(client, user_id):
                errors.append("auth_user")
        except Exception as exc:
            logger.warning("account delete: auth user error=%r", exc)
            errors.append("auth_user")

    complete = len(errors) == 0
    if not complete:
        logger.error("account delete: incomplete — failed steps: %s user=%s", errors, user_id[:8])
    logger.info("account delete: user=%s complete=%s steps=%s", user_id[:8], complete, list(summary.keys()))

    return {
        "deleted": True,
        "complete": complete,
        "user_id": user_id,
        "tables_cleared": summary,
        "errors": errors if errors else None,
    }
