import os
from datetime import datetime, timezone
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from app.auth_middleware import verify_token
from typing import Optional

router = APIRouter()

PLAN_CAPS = {
    # Must be >= usage_config.ALLOWANCES[tier]["msgs"] (what the usage meter
    # shows) so this secondary cap never blocks a user below their displayed
    # allowance. Basic was 500 while the meter showed 600 — bug fixed here.
    "free": 75,
    "basic": 600,
    "premium": 1500,
    "power": 3500,
}

STRIPE_PRICE_MAP = {
    price_id: plan
    for price_id, plan in (
        (os.environ.get("STRIPE_PRICE_BASIC", ""), "basic"),
        (os.environ.get("STRIPE_PRICE_PREMIUM", ""), "premium"),
        (os.environ.get("STRIPE_PRICE_POWER", ""), "power"),
    )
    if price_id
}


def _sb_headers():
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}

def _sb_url(path: str) -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/") + path


async def get_or_create_entitlement(user_id: str) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as hx:
        r = await hx.get(_sb_url("/rest/v1/user_entitlements"), headers=_sb_headers(),
                         params={"user_id": f"eq.{user_id}", "limit": "1"})
    if r.status_code == 200 and r.json():
        return r.json()[0]
    now = datetime.now(timezone.utc)
    period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    m, y = (period_start.month + 1, period_start.year) if period_start.month < 12 else (1, period_start.year + 1)
    period_end = period_start.replace(month=m, year=y)
    row = {"user_id": user_id, "plan": "free", "message_count": 0,
           "period_start": period_start.isoformat(), "period_end": period_end.isoformat(), "status": "active"}
    async with httpx.AsyncClient(timeout=5.0) as hx:
        await hx.post(_sb_url("/rest/v1/user_entitlements"),
                      headers={**_sb_headers(), "Prefer": "return=minimal"}, json=row)
    return row


async def reset_period_if_expired(ent: dict, user_id: str) -> dict:
    now = datetime.now(timezone.utc)
    period_end = datetime.fromisoformat(ent["period_end"].replace("Z", "+00:00"))
    if now < period_end:
        return ent
    new_start = period_end
    m, y = (new_start.month + 1, new_start.year) if new_start.month < 12 else (1, new_start.year + 1)
    new_end = new_start.replace(month=m, year=y)
    async with httpx.AsyncClient(timeout=5.0) as hx:
        await hx.patch(_sb_url("/rest/v1/user_entitlements"), headers=_sb_headers(),
                       params={"user_id": f"eq.{user_id}"},
                       json={"message_count": 0, "period_start": new_start.isoformat(),
                             "period_end": new_end.isoformat(), "updated_at": now.isoformat()})
    ent.update({"message_count": 0, "period_start": new_start.isoformat(), "period_end": new_end.isoformat()})
    return ent


async def check_and_increment(user_id: str) -> dict:
    ent = await get_or_create_entitlement(user_id)
    ent = await reset_period_if_expired(ent, user_id)
    plan = ent.get("plan", "free")
    cap = PLAN_CAPS.get(plan, 75)
    used = ent.get("message_count", 0)
    try:
        reset_dt = datetime.fromisoformat(ent["period_end"].replace("Z", "+00:00"))
        reset_date = reset_dt.strftime("%B %-d, %Y")
    except Exception:
        reset_date = "next month"
    if used >= cap:
        return {"allowed": False, "plan": plan, "used": used, "cap": cap, "remaining": 0, "warning": False, "reset_date": reset_date}
    async with httpx.AsyncClient(timeout=5.0) as hx:
        await hx.patch(_sb_url("/rest/v1/user_entitlements"), headers=_sb_headers(),
                       params={"user_id": f"eq.{user_id}"},
                       json={"message_count": used + 1, "updated_at": datetime.now(timezone.utc).isoformat()})
    remaining = cap - (used + 1)
    return {"allowed": True, "plan": plan, "used": used + 1, "cap": cap,
            "remaining": remaining, "warning": remaining <= (cap * 0.2), "reset_date": reset_date}


async def get_plan(user_id: str) -> str:
    """Return the user's current plan name."""
    ent = await get_or_create_entitlement(user_id)
    return ent.get("plan", "free")


def get_limits(plan: str) -> dict:
    """Return per-plan feature limits."""
    return {"max_facts": {"free": 50, "basic": 150, "premium": 500, "power": 2000}.get(plan, 50)}


async def _update_plan_internal(user_id: str, plan: str) -> dict:
    """Internal helper — no auth (server-side only)."""
    if plan not in PLAN_CAPS:
        return {"updated": False}
    async with httpx.AsyncClient(timeout=5.0) as hx:
        await hx.patch(
            _sb_url("/rest/v1/user_entitlements"),
            headers=_sb_headers(),
            params={"user_id": f"eq.{user_id}"},
            json={"plan": plan},
        )
    return {"updated": True, "plan": plan}


@router.get("/api/entitlements")
async def get_entitlement(token_user_id: str = Depends(verify_token)):
    user_id = token_user_id
    ent = await get_or_create_entitlement(user_id)
    ent = await reset_period_if_expired(ent, user_id)
    plan = ent.get("plan", "free")
    cap = PLAN_CAPS.get(plan, 75)
    used = ent.get("message_count", 0)
    try:
        reset_dt = datetime.fromisoformat(ent["period_end"].replace("Z", "+00:00"))
        reset_date = reset_dt.strftime("%B %-d, %Y")
    except Exception:
        reset_date = "next month"
    return {"plan": plan, "used": used, "cap": cap, "remaining": max(0, cap - used),
            "warning": (cap - used) <= (cap * 0.2), "reset_date": reset_date, "status": ent.get("status", "active")}


@router.patch("/api/entitlements/plan")
async def update_plan(plan: str, token_user_id: str = Depends(verify_token)):
    user_id = token_user_id
    if plan not in PLAN_CAPS:
        raise HTTPException(400, f"Invalid plan. Must be one of: {list(PLAN_CAPS.keys())}")
    async with httpx.AsyncClient(timeout=5.0) as hx:
        await hx.patch(_sb_url("/rest/v1/user_entitlements"), headers=_sb_headers(),
                       params={"user_id": f"eq.{user_id}"},
                       json={"plan": plan, "updated_at": datetime.now(timezone.utc).isoformat()})
    return {"updated": True, "plan": plan}


@router.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    import json
    body = await request.body()
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        # Fail closed: never accept unsigned webhooks that mutate plans.
        raise HTTPException(503, "Stripe webhook secret not configured")
    sig = request.headers.get("stripe-signature", "")
    try:
        import stripe as stripe_lib
        stripe_lib.Webhook.construct_event(body, sig, secret)
    except Exception as e:
        raise HTTPException(400, str(e))
    payload = json.loads(body)
    event_type = payload.get("type", "")
    data = payload.get("data", {}).get("object", {})
    customer_id = data.get("customer")
    status = data.get("status", "")
    items = data.get("items", {}).get("data", [])
    price_id = items[0].get("price", {}).get("id", "") if items else ""
    plan = STRIPE_PRICE_MAP.get(price_id, "free")
    if event_type in ("customer.subscription.created", "customer.subscription.updated") and status in ("active", "trialing"):
        async with httpx.AsyncClient(timeout=5.0) as hx:
            r = await hx.get(_sb_url("/rest/v1/user_entitlements"), headers=_sb_headers(),
                             params={"stripe_customer_id": f"eq.{customer_id}", "limit": "1"})
            if r.status_code == 200 and r.json():
                uid = r.json()[0]["user_id"]
                await hx.patch(_sb_url("/rest/v1/user_entitlements"), headers=_sb_headers(),
                                params={"user_id": f"eq.{uid}"},
                                json={"plan": plan, "status": "active", "updated_at": datetime.now(timezone.utc).isoformat()})
    elif event_type == "customer.subscription.deleted":
        async with httpx.AsyncClient(timeout=5.0) as hx:
            r = await hx.get(_sb_url("/rest/v1/user_entitlements"), headers=_sb_headers(),
                             params={"stripe_customer_id": f"eq.{customer_id}", "limit": "1"})
            if r.status_code == 200 and r.json():
                uid = r.json()[0]["user_id"]
                await hx.patch(_sb_url("/rest/v1/user_entitlements"), headers=_sb_headers(),
                                params={"user_id": f"eq.{uid}"},
                                json={"plan": "free", "status": "canceled", "updated_at": datetime.now(timezone.utc).isoformat()})
    return {"received": True}
