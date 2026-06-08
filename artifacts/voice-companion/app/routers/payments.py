"""
Stripe payments router.

  POST /api/create-checkout-session  — create Stripe Checkout session (auth required)
  POST /api/stripe-webhook           — handle Stripe webhook events (no auth)
  GET  /api/subscription-status      — return current user's subscription tier (auth required)

Products and prices are created on-demand on the first checkout call and cached
in memory for the lifetime of the process.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DATABASE — run this SQL in Supabase SQL Editor before using payments:

  CREATE TABLE IF NOT EXISTS profiles (
    id                  uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    stripe_customer_id  text,
    subscription_tier   text        DEFAULT 'free',
    subscription_status text        DEFAULT 'inactive',
    subscribed_at       timestamptz,
    updated_at          timestamptz DEFAULT now()
  );

If the table already exists, add the missing columns:

  ALTER TABLE profiles
    ADD COLUMN IF NOT EXISTS subscription_tier   text DEFAULT 'free',
    ADD COLUMN IF NOT EXISTS stripe_customer_id  text,
    ADD COLUMN IF NOT EXISTS subscription_status text DEFAULT 'inactive';

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import asyncio
import datetime
import json
import logging
import os

import httpx
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.auth_middleware import verify_token

router = APIRouter()
logger = logging.getLogger(__name__)

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")

# ── Plan definitions ──────────────────────────────────────────────────────────

PLANS: dict[str, dict] = {
    "basic":   {"name": "Companion Basic",   "amount": 1299,  "label": "Basic"},
    "premium": {"name": "Companion Premium", "amount": 3999,  "label": "Premium"},
    "power":   {"name": "Companion Power",   "amount": 8999,  "label": "Power"},
    "elite":   {"name": "Companion Elite",   "amount": 14999, "label": "Elite"},
}

_price_ids: dict[str, str] = {}


# ── Stripe helpers (run in thread — stripe SDK is synchronous) ────────────────

def _sync_get_or_create_price(plan_key: str) -> str:
    if plan_key in _price_ids:
        return _price_ids[plan_key]

    plan = PLANS[plan_key]

    products = stripe.Product.list(active=True, limit=100)
    product = next(
        (p for p in products.auto_paging_iter() if p.name == plan["name"]),
        None,
    )
    if not product:
        product = stripe.Product.create(name=plan["name"])

    prices = stripe.Price.list(product=product.id, active=True, limit=100)
    price = next(
        (
            p for p in prices.auto_paging_iter()
            if p.unit_amount == plan["amount"]
            and p.recurring
            and p.recurring.interval == "month"
        ),
        None,
    )
    if not price:
        price = stripe.Price.create(
            product=product.id,
            unit_amount=plan["amount"],
            currency="usd",
            recurring={"interval": "month"},
        )

    _price_ids[plan_key] = price.id
    return price.id


def _app_base_url() -> str:
    domains = os.environ.get("REPLIT_DOMAINS", "")
    domain = domains.split(",")[0].strip() if domains else ""
    if not domain:
        domain = os.environ.get("REPLIT_DEV_DOMAIN", "")
    return f"https://{domain}/companion/" if domain else "http://localhost/companion/"


# ── Supabase helpers ──────────────────────────────────────────────────────────

def _supa_headers() -> dict[str, str]:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


async def _upsert_profile(user_id: str, **fields: object) -> None:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not url:
        return
    payload = {
        "id": user_id,
        "updated_at": datetime.datetime.utcnow().isoformat(),
        **fields,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(
            f"{url}/rest/v1/profiles",
            headers={
                **_supa_headers(),
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
            json=payload,
        )


async def _user_id_by_customer(customer_id: str) -> str | None:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not url:
        return None
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{url}/rest/v1/profiles",
            headers=_supa_headers(),
            params={
                "stripe_customer_id": f"eq.{customer_id}",
                "select": "id",
                "limit": "1",
            },
        )
    if resp.status_code == 200 and resp.json():
        return resp.json()[0]["id"]
    return None


# ── Endpoints ─────────────────────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    plan: str


@router.post("/create-checkout-session")
async def create_checkout_session(
    req: CheckoutRequest,
    user_id: str = Depends(verify_token),
):
    if req.plan not in PLANS:
        raise HTTPException(400, f"Unknown plan '{req.plan}'. Choose: {list(PLANS)}")

    try:
        price_id = await asyncio.to_thread(_sync_get_or_create_price, req.plan)
        base = _app_base_url()
        session = await asyncio.to_thread(
            stripe.checkout.Session.create,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{base}?checkout=success&plan={req.plan}",
            cancel_url=f"{base}?checkout=cancelled",
            client_reference_id=user_id,
            metadata={"user_id": user_id, "plan": req.plan},
        )
    except stripe.StripeError as exc:
        raise HTTPException(400, str(exc)) from exc

    return {"url": session.url}


@router.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    try:
        if secret:
            event = await asyncio.to_thread(
                stripe.Webhook.construct_event, payload, sig, secret
            )
        else:
            logger.warning("STRIPE_WEBHOOK_SECRET not set — skipping signature verification")
            event = stripe.Event.construct_from(
                json.loads(payload), stripe.api_key
            )
    except (stripe.SignatureVerificationError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc

    obj = event["data"]["object"]

    if event["type"] == "checkout.session.completed":
        user_id = obj.get("client_reference_id") or (obj.get("metadata") or {}).get("user_id")
        customer_id = obj.get("customer")
        plan = (obj.get("metadata") or {}).get("plan", "basic")
        if user_id:
            await _upsert_profile(
                user_id,
                stripe_customer_id=customer_id,
                subscription_tier=plan,
                subscription_status="active",
                subscribed_at=datetime.datetime.utcnow().isoformat(),
            )
            logger.info("Subscription activated user=%s plan=%s", user_id, plan)

    elif event["type"] == "customer.subscription.deleted":
        customer_id = obj.get("customer")
        if customer_id:
            user_id = await _user_id_by_customer(customer_id)
            if user_id:
                await _upsert_profile(user_id, subscription_tier="free", subscription_status="inactive")
                logger.info("Subscription cancelled user=%s", user_id)

    return {"received": True}


@router.get("/subscription-status")
async def subscription_status(user_id: str = Depends(verify_token)):
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return {"tier": "free"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{url}/rest/v1/profiles",
            headers=_supa_headers(),
            params={"id": f"eq.{user_id}", "select": "subscription_tier,subscription_status,subscribed_at", "limit": "1"},
        )

    if resp.status_code == 200 and resp.json():
        row = resp.json()[0]
        return {
            "tier": row.get("subscription_tier", "free"),
            "status": row.get("subscription_status", "inactive"),
            "subscribed_at": row.get("subscribed_at"),
        }
    return {"tier": "free", "status": "inactive", "subscribed_at": None}
