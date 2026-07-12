---
name: Billing guardrails
description: Rules for 5-year plan expiry enforcement and Stripe tier resolution. Fail open on ambiguity.
---

## Core rule
**Fail open on any ambiguous billing signal. Only downgrade on an explicit, unambiguous expired/canceled state.**

## 5-year plan expiry (C3)
- `_get_user_profile` in `chat.py` now fetches `billing_period` and `access_expires_at` in addition to `subscription_tier`/`subscription_status`.
- If `billing_period == "5year"` and `access_expires_at` is parseable and in the past → downgrade to `("free", "inactive")` with an `INFO` log.
- If the date is unparseable → **fail open**, keep existing tier, log `WARNING`.
- If the DB call fails entirely → return `("free", "inactive")` (pre-existing safe default; not changed).
- **Why:** Stripe never fires `subscription.deleted` for one-time payments; without this check 5-year users keep access forever after expiry.

## Stripe tier update on plan change (H3)
- `_tier_from_price_id(price_id)` in `payments.py` maps a Stripe price ID → our tier string.
  - Fast path: reverse-lookup in the in-memory `_price_ids` cache.
  - Slow path: `stripe.Price.retrieve` → `stripe.Product.retrieve` → match `product.name` to `PLANS[*]["name"]`.
  - Returns `None` on any error or no match.
- `customer.subscription.updated` webhook: always updates `subscription_status`; only updates `subscription_tier` if `_tier_from_price_id` returns a non-None value.
- If price unresolvable → log INFO with `tier_unchanged` note, keep existing tier.
- **Why:** Portal plan switches fire `subscription.updated` but not a new `checkout.session.completed`, so the old code left the DB tier stale after upgrades/downgrades.

## Misleading tier-check helper names
- In `chat.py`, `_is_premium_or_above(tier)` is misnamed — it actually returns True for `basic` too (checks `rank >= basic`). `_is_power_or_above` is correctly named.
- Any feature gated to "premium and above only" (excluding basic) must NOT reuse `_is_premium_or_above`; add/verify a helper that compares against `_TIER_RANK["premium"]` directly (e.g. `_voice_available_for_tier`).
- **Why:** blindly reusing `_is_premium_or_above` for a premium-gated feature (e.g. TTS voice output) silently leaks it to basic-tier users.

## CORS (C2)
- `main.py` no longer uses `allow_origins=["*"]`. Explicit list: `legacybond.ai`, `www.legacybond.ai`, `voice-companion-backend.replit.app`, plus `REPLIT_DEV_DOMAIN` at startup.
- **Why:** `allow_origins=*` + `allow_credentials=True` is invalid per Fetch spec; browsers block credentialed cross-origin requests from wildcard origins.

## Monthly cap plan sync (entitlements)
- `user_entitlements.plan` (monthly caps) is a *derived copy* of the profile tier; `_check_monthly_cap` in `chat.py` syncs it unconditionally on every message — including downgrades to `free`.
- Sync must be bidirectional: syncing only upgrades leaves downgraded users with a stale higher cap.
- `elite` profile tier maps to `power` caps (elite is not a monthly-cap plan).
- The entitlements Stripe webhook (`/api/stripe/webhook`, distinct from payments' `/api/stripe-webhook`) fails **closed** when `STRIPE_WEBHOOK_SECRET` is unset — plan mutations must never accept unsigned payloads (exception to the general fail-open rule, which applies to reads/checks, not writes).
- `STRIPE_PRICE_MAP` must filter out empty env-derived keys, or an unset price env var maps `""` to a paid tier.
