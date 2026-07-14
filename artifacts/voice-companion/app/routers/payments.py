"""
Stripe payments router.

  POST /api/create-checkout-session  — create Stripe Checkout session (auth required)
  POST /api/stripe-webhook           — handle Stripe webhook events (no auth)
  GET  /api/subscription-status      — return current user's subscription tier (auth required)
  POST /api/billing-portal           — create Stripe Customer Portal session (auth required)

Products and prices are created on-demand on the first checkout call and cached
in memory for the lifetime of the process.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DATABASE — run this SQL in Supabase SQL Editor (the `profiles` table must
exist before any checkout webhook or tier-gating can work):

  CREATE TABLE IF NOT EXISTS profiles (
    id                  uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    stripe_customer_id  text,
    subscription_tier   text        NOT NULL DEFAULT 'free',
    subscription_status text        NOT NULL DEFAULT 'inactive',
    billing_period      text        NOT NULL DEFAULT 'monthly',
    access_expires_at   timestamptz,
    subscribed_at       timestamptz,
    updated_at          timestamptz NOT NULL DEFAULT now()
  );

  ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;

  CREATE POLICY "Users can view own profile"
    ON profiles FOR SELECT
    USING (auth.uid() = id);

  CREATE POLICY "Users can insert own profile"
    ON profiles FOR INSERT
    WITH CHECK (auth.uid() = id);

  CREATE POLICY "Users can update own profile"
    ON profiles FOR UPDATE
    USING (auth.uid() = id);

The backend uses SUPABASE_SERVICE_KEY which bypasses RLS, so the policies
above are only needed for completeness / any future direct-from-client reads.
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
from app.usage_config import TOPUP_PACKS

router = APIRouter()
logger = logging.getLogger(__name__)

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")

# ── Plan definitions ──────────────────────────────────────────────────────────
# "interval": "month" | "year" | None   (None = one-time payment, not subscription)
# Prices in cents. Annual = monthly × 12 × 0.95. 5-year = monthly × 60 × 0.90.

PLANS: dict[str, dict] = {
    # ── Monthly ───────────────────────────────────────────────────────────────
    "basic":          {"name": "Companion Basic",   "amount": 1299,   "base": "basic",   "interval": "month"},
    "premium":        {"name": "Companion Premium", "amount": 3999,   "base": "premium", "interval": "month"},
    "power":          {"name": "Companion Power",   "amount": 8999,   "base": "power",   "interval": "month"},
    # ── Annual (5% off) ───────────────────────────────────────────────────────
    "basic_annual":   {"name": "Companion Basic",   "amount": 14809,  "base": "basic",   "interval": "year"},
    "premium_annual": {"name": "Companion Premium", "amount": 45589,  "base": "premium", "interval": "year"},
    "power_annual":   {"name": "Companion Power",   "amount": 102589, "base": "power",   "interval": "year"},
    # ── 5-Year one-time (10% off) ─────────────────────────────────────────────
    # Stripe does not support recurring intervals > 1 year, so these are
    # one-time payments (mode="payment"). Access expiry is tracked in our DB.
    "basic_5year":    {"name": "Companion Basic",   "amount": 70146,  "base": "basic",   "interval": None},
    "premium_5year":  {"name": "Companion Premium", "amount": 215946, "base": "premium", "interval": None},
    "power_5year":    {"name": "Companion Power",   "amount": 485946, "base": "power",   "interval": None},
    # ── Legacy (kept for backward compat) ────────────────────────────────────
    "elite":          {"name": "Companion Elite",   "amount": 14999,  "base": "elite",   "interval": "month"},
}

_price_ids: dict[str, str] = {}


# ── Stripe helpers (run in thread — stripe SDK is synchronous) ────────────────

def _sync_get_or_create_price(plan_key: str) -> str:
    if plan_key in _price_ids:
        return _price_ids[plan_key]

    plan = PLANS[plan_key]
    interval = plan.get("interval")  # "month", "year", or None (one-time)

    # Find or create the Product — shared across all billing periods for the same tier
    products = stripe.Product.list(active=True, limit=100)
    product = next(
        (p for p in products.auto_paging_iter() if p.name == plan["name"]),
        None,
    )
    if not product:
        product = stripe.Product.create(name=plan["name"])

    # Find or create the matching Price
    prices = stripe.Price.list(product=product.id, active=True, limit=100)

    if interval:
        # Recurring price (monthly or annual)
        price = next(
            (
                p for p in prices.auto_paging_iter()
                if p.unit_amount == plan["amount"]
                and p.recurring
                and p.recurring.interval == interval
            ),
            None,
        )
        if not price:
            price = stripe.Price.create(
                product=product.id,
                unit_amount=plan["amount"],
                currency="usd",
                recurring={"interval": interval},
            )
    else:
        # One-time price (5-year prepayment)
        price = next(
            (
                p for p in prices.auto_paging_iter()
                if p.unit_amount == plan["amount"]
                and not p.recurring
            ),
            None,
        )
        if not price:
            price = stripe.Price.create(
                product=product.id,
                unit_amount=plan["amount"],
                currency="usd",
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
    """Upsert a user's profile row.

    Raises on failure (network error or non-2xx) so the webhook can return 5xx and
    let Stripe retry. Safe to retry: this upsert is idempotent (keyed on user_id).
    """
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not url:
        raise RuntimeError("SUPABASE_URL not configured")
    payload = {
        "id": user_id,
        "updated_at": datetime.datetime.utcnow().isoformat(),
        **fields,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{url}/rest/v1/profiles",
            headers={
                **_supa_headers(),
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
            json=payload,
        )
    if resp.status_code >= 400:
        logger.error("Profile upsert failed user=%s status=%s body=%s", user_id, resp.status_code, resp.text[:200])
        raise RuntimeError(f"Profile upsert failed (status {resp.status_code})")


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


async def _tier_from_price_id(price_id: str | None) -> str | None:
    """
    Map a Stripe price_id to our internal tier string (e.g. 'basic', 'power').

    Fast path: check the in-memory _price_ids cache populated during checkout.
    Slow path: fetch the price from Stripe, resolve its product name, match to
    our PLANS table.  Runs Stripe SDK calls in a thread (sync SDK).

    Returns None if unresolvable — callers must fail open and leave the existing
    tier unchanged.
    """
    if not price_id:
        return None

    # Fast path — cache populated when checkout sessions are created
    reverse = {v: k for k, v in _price_ids.items()}
    plan_key = reverse.get(price_id)
    if plan_key and plan_key in PLANS:
        tier = PLANS[plan_key]["base"]
        logger.debug("_tier_from_price_id cache hit price=%s → tier=%s", price_id, tier)
        return tier

    # Slow path — ask Stripe (sync SDK wrapped in thread)
    try:
        price = await asyncio.to_thread(stripe.Price.retrieve, price_id)
        product_id = price.get("product") if isinstance(price, dict) else getattr(price, "product", None)
        if not product_id or not isinstance(product_id, str):
            logger.warning("_tier_from_price_id: no product on price=%s — failing open", price_id)
            return None
        product = await asyncio.to_thread(stripe.Product.retrieve, product_id)
        product_name = (
            product.get("name") if isinstance(product, dict) else getattr(product, "name", "")
        ) or ""
        for pk, plan in PLANS.items():
            if plan["name"] == product_name:
                _price_ids[pk] = price_id  # warm cache for future lookups
                logger.info(
                    "_tier_from_price_id resolved price=%s product='%s' → tier=%s",
                    price_id, product_name, plan["base"],
                )
                return plan["base"]
        logger.warning(
            "_tier_from_price_id: no PLANS match for product='%s' price=%s — failing open",
            product_name, price_id,
        )
    except Exception as exc:
        logger.warning(
            "_tier_from_price_id: error resolving price=%s err=%s — failing open",
            price_id, exc,
        )
    return None


async def _get_profile(user_id: str) -> dict | None:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not url:
        return None
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{url}/rest/v1/profiles",
            headers=_supa_headers(),
            params={"id": f"eq.{user_id}", "select": "*", "limit": "1"},
        )
    if resp.status_code == 200 and resp.json():
        return resp.json()[0]
    return None


def _sync_get_or_create_topup_price(pack_key: str) -> str:
    """Find or create a one-time Stripe Price for a top-up pack (thread-safe after first call)."""
    if pack_key in _price_ids:
        return _price_ids[pack_key]

    pack = TOPUP_PACKS[pack_key]
    products = stripe.Product.list(active=True, limit=100)
    product = next(
        (
            p for p in products.auto_paging_iter()
            if p.name == pack["name"] and (p.metadata or {}).get("type") == "topup"
        ),
        None,
    )
    if not product:
        product = stripe.Product.create(
            name=pack["name"],
            metadata={"type": "topup", "pack": pack_key},
        )

    prices = stripe.Price.list(product=product.id, active=True, limit=100)
    price = next(
        (p for p in prices.auto_paging_iter() if p.unit_amount == pack["amount"] and not p.recurring),
        None,
    )
    if not price:
        price = stripe.Price.create(product=product.id, unit_amount=pack["amount"], currency="usd")

    _price_ids[pack_key] = price.id
    return price.id


async def _apply_topup_credits(
    user_id: str,
    kind: str,
    credits: int,
    event_id: str,
) -> None:
    """
    Atomically add top-up credits via Supabase RPC.
    Idempotent: the DB function checks event_id to skip duplicate webhook events.
    """
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not url:
        raise RuntimeError("SUPABASE_URL not configured")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{url}/rest/v1/rpc/apply_topup_credits",
            headers=_supa_headers(),
            json={
                "p_user_id": user_id,
                "p_kind": kind,
                "p_credits": credits,
                "p_event_id": event_id,
            },
        )
    if resp.status_code not in (200, 204):
        logger.error(
            "apply_topup_credits failed user=%s kind=%s credits=%s status=%s: %s",
            user_id, kind, credits, resp.status_code, resp.text[:200],
        )
        raise RuntimeError(f"apply_topup_credits failed (status {resp.status_code})")


# ── Endpoints ─────────────────────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    plan: str


@router.post("/billing-portal")
async def billing_portal(user_id: str = Depends(verify_token)):
    if not stripe.api_key:
        raise HTTPException(503, "Payment system not configured — STRIPE_SECRET_KEY missing")

    profile = await _get_profile(user_id)
    customer_id = (profile or {}).get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(400, "No active subscription found. Upgrade to a paid plan to manage billing.")

    try:
        session = await asyncio.to_thread(
            stripe.billing_portal.Session.create,
            customer=customer_id,
            return_url=_app_base_url(),
        )
    except stripe.StripeError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.error("Billing portal error user=%s: %s", user_id, exc)
        raise HTTPException(503, "Billing portal unavailable — please try again") from exc

    return {"url": session.url}


@router.post("/create-checkout-session")
async def create_checkout_session(
    req: CheckoutRequest,
    user_id: str = Depends(verify_token),
):
    if req.plan not in PLANS and req.plan not in TOPUP_PACKS:
        raise HTTPException(400, f"Unknown plan or pack '{req.plan}'")

    if not stripe.api_key:
        raise HTTPException(503, "Payment system not configured — STRIPE_SECRET_KEY missing")

    base = _app_base_url()

    # ── Top-up pack (one-time credit purchase) ────────────────────────────────
    if req.plan in TOPUP_PACKS:
        try:
            price_id = await asyncio.to_thread(_sync_get_or_create_topup_price, req.plan)
            session = await asyncio.to_thread(
                stripe.checkout.Session.create,
                mode="payment",
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=f"{base}?checkout=topup_success&pack={req.plan}",
                cancel_url=f"{base}?checkout=cancelled",
                client_reference_id=user_id,
                metadata={"user_id": user_id, "pack": req.plan, "type": "topup"},
                customer_creation="if_required",
            )
        except stripe.StripeError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            logger.error("Topup checkout error pack=%s user=%s: %s", req.plan, user_id, exc)
            raise HTTPException(503, "Checkout unavailable — please try again") from exc
        return {"url": session.url}

    # ── Subscription plan ─────────────────────────────────────────────────────
    plan = PLANS[req.plan]
    is_one_time = plan.get("interval") is None

    try:
        price_id = await asyncio.to_thread(_sync_get_or_create_price, req.plan)

        if is_one_time:
            # 5-year one-time purchase — use payment mode
            session = await asyncio.to_thread(
                stripe.checkout.Session.create,
                mode="payment",
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=f"{base}?checkout=success&plan={req.plan}",
                cancel_url=f"{base}?checkout=cancelled",
                client_reference_id=user_id,
                metadata={"user_id": user_id, "plan": req.plan},
                customer_creation="always",  # ensure customer_id available for future upgrades
            )
        else:
            # Monthly or annual subscription
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
    except Exception as exc:
        logger.error("Unexpected checkout error plan=%s user=%s: %s", req.plan, user_id, exc)
        raise HTTPException(503, "Checkout unavailable — please try again") from exc

    return {"url": session.url}


@router.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    if not secret:
        logger.error("STRIPE_WEBHOOK_SECRET is not configured — refusing to process webhook")
        raise HTTPException(500, "Webhook secret not configured")

    try:
        event = await asyncio.to_thread(
            stripe.Webhook.construct_event, payload, sig, secret
        )
    except (stripe.SignatureVerificationError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc

    obj = event["data"]["object"]

    try:
        if event["type"] == "checkout.session.completed":
            user_id = obj.get("client_reference_id") or (obj.get("metadata") or {}).get("user_id")
            customer_id = obj.get("customer")
            metadata = obj.get("metadata") or {}

            # ── Top-up pack: apply credits and skip subscription logic ────────
            if metadata.get("type") == "topup":
                pack_key = metadata.get("pack", "")
                if user_id and pack_key and pack_key in TOPUP_PACKS:
                    pack_cfg = TOPUP_PACKS[pack_key]
                    await _apply_topup_credits(
                        user_id, pack_cfg["kind"], pack_cfg["credits"], obj.get("id", "")
                    )
                    logger.info(
                        "Topup applied user=%s pack=%s credits=%s",
                        user_id, pack_key, pack_cfg["credits"],
                    )
            else:
                # ── Subscription activation ───────────────────────────────────
                plan = metadata.get("plan", "basic")

                # Derive base tier and billing period from the plan key
                if plan.endswith("_5year"):
                    base_tier = plan[:-6]          # "basic_5year" → "basic"
                    billing_period = "5year"
                    access_expires_at: str | None = (
                        datetime.datetime.utcnow() + datetime.timedelta(days=5 * 365)
                    ).isoformat()
                elif plan.endswith("_annual"):
                    base_tier = plan[:-7]          # "basic_annual" → "basic"
                    billing_period = "annual"
                    access_expires_at = None
                else:
                    base_tier = plan
                    billing_period = "monthly"
                    access_expires_at = None

                if user_id:
                    update: dict[str, object] = {
                        "subscription_tier": base_tier,
                        "subscription_status": "active",
                        "billing_period": billing_period,
                        "subscribed_at": datetime.datetime.utcnow().isoformat(),
                    }
                    if customer_id:
                        update["stripe_customer_id"] = customer_id
                    if access_expires_at:
                        update["access_expires_at"] = access_expires_at
                    await _upsert_profile(user_id, **update)
                    logger.info(
                        "Subscription activated user=%s tier=%s period=%s",
                        user_id, base_tier, billing_period,
                    )

        elif event["type"] == "customer.subscription.deleted":
            # Only fires for recurring subscriptions (monthly/annual), not 5-year one-time.
            customer_id = obj.get("customer")
            if customer_id:
                user_id = await _user_id_by_customer(customer_id)
                if user_id:
                    await _upsert_profile(
                        user_id,
                        subscription_tier="free",
                        subscription_status="inactive",
                        billing_period="monthly",
                    )
                    logger.info("Subscription cancelled user=%s", user_id)

        elif event["type"] == "customer.subscription.updated":
            # Fires when a subscription's status changes (e.g. active → past_due,
            # past_due → active on successful retry, or plan upgrade/downgrade).
            customer_id = obj.get("customer")
            stripe_status = obj.get("status", "")
            if customer_id and stripe_status:
                user_id = await _user_id_by_customer(customer_id)
                if user_id:
                    # Map Stripe status to our internal subscription_status.
                    # "active" and "trialing" → active; anything else → past_due/inactive.
                    if stripe_status in ("active", "trialing"):
                        internal_status = "active"
                    elif stripe_status == "past_due":
                        internal_status = "past_due"
                    else:
                        internal_status = "inactive"

                    # Attempt to resolve the new tier from the subscription's
                    # price item. This handles mid-cycle plan switches made via
                    # the Stripe Customer Portal.  Fails open: if we can't
                    # resolve the price to a known tier we only update status
                    # and leave subscription_tier unchanged.
                    items_data = (obj.get("items") or {}).get("data") or []
                    price_id: str | None = None
                    if items_data:
                        price_id = ((items_data[0].get("price") or {})).get("id")
                    new_tier = await _tier_from_price_id(price_id)

                    update_fields: dict[str, object] = {
                        "subscription_status": internal_status
                    }
                    if new_tier:
                        update_fields["subscription_tier"] = new_tier
                        logger.info(
                            "Subscription updated user=%s stripe_status=%s internal=%s new_tier=%s",
                            user_id, stripe_status, internal_status, new_tier,
                        )
                    else:
                        # Could not resolve tier — keep existing tier, only update status.
                        # Billing guardrail: never silently downgrade on an ambiguous signal.
                        logger.info(
                            "Subscription updated user=%s stripe_status=%s internal=%s "
                            "tier_unchanged (price_id=%s not resolvable — keeping existing tier)",
                            user_id, stripe_status, internal_status, price_id,
                        )
                    await _upsert_profile(user_id, **update_fields)

        elif event["type"] == "invoice.payment_failed":
            # Fires when a renewal invoice cannot be collected.  Mark the user
            # past_due immediately so the paywall activates — Stripe will retry
            # and fire subscription.updated → active if payment eventually succeeds.
            customer_id = obj.get("customer")
            if customer_id:
                user_id = await _user_id_by_customer(customer_id)
                if user_id:
                    await _upsert_profile(user_id, subscription_status="past_due")
                    logger.warning("Invoice payment failed — user=%s marked past_due", user_id)

    except Exception as exc:
        # Fail closed: a handled event whose critical write failed returns 5xx so
        # Stripe retries with exponential backoff. Safe because processing is
        # idempotent — the profile upsert is keyed on user_id, and the topup RPC
        # dedupes on the Stripe event/session id — so a retry re-runs without
        # double-applying. Unhandled event types never enter a branch above, so
        # they skip this except and fall through to the 200 below.
        logger.error("Webhook handler error event=%s: %s — returning 500 so Stripe retries", event["type"], exc)
        raise HTTPException(status_code=500, detail="Webhook processing failed; Stripe will retry") from exc

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
            params={
                "id": f"eq.{user_id}",
                "select": "subscription_tier,subscription_status,subscribed_at,billing_period,access_expires_at",
                "limit": "1",
            },
        )

    if resp.status_code == 200 and resp.json():
        row = resp.json()[0]
        tier = row.get("subscription_tier", "free")
        status = row.get("subscription_status", "inactive")
        billing_period = row.get("billing_period") or "monthly"
        access_expires_at = row.get("access_expires_at")

        # 5-year users: treat as active until expiry date, then downgrade
        if billing_period == "5year" and status == "active" and access_expires_at:
            try:
                expires = datetime.datetime.fromisoformat(access_expires_at.replace("Z", "+00:00"))
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=datetime.timezone.utc)
                if expires < datetime.datetime.now(datetime.timezone.utc):
                    tier = "free"
                    status = "inactive"
            except (ValueError, AttributeError):
                pass

        return {
            "tier": tier,
            "status": status,
            "subscribed_at": row.get("subscribed_at"),
            "billing_period": billing_period,
            "access_expires_at": access_expires_at,
        }

    return {
        "tier": "free",
        "status": "inactive",
        "subscribed_at": None,
        "billing_period": "monthly",
        "access_expires_at": None,
    }
