"""
Push notification sender.

Usage:
    from app.push_sender import send_push_to_user, send_push_to_subscription

Both functions are async-safe and swallow errors — a failed push should never
crash any calling flow.
"""
import json
import logging
import os
from typing import Any

import httpx
from pywebpush import webpush, WebPushException

logger = logging.getLogger(__name__)


# ── VAPID config ─────────────────────────────────────────────────────────────

def _vapid_ready() -> bool:
    return bool(
        os.environ.get("VAPID_PRIVATE_KEY")
        and os.environ.get("VAPID_PUBLIC_KEY")
        and os.environ.get("VAPID_CLAIM_EMAIL")
    )


def _vapid_claims() -> dict:
    return {"sub": f"mailto:{os.environ.get('VAPID_CLAIM_EMAIL', '')}"}


# ── low-level send ────────────────────────────────────────────────────────────

async def send_push_to_subscription(
    endpoint: str,
    p256dh: str,
    auth: str,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
    icon: str = "/icon-192.png",
    badge: str = "/favicon-32.png",
) -> bool:
    """Send one push notification to a single subscription. Returns True on success."""
    if not _vapid_ready():
        logger.warning("VAPID keys not configured — skipping push")
        return False

    payload = json.dumps({
        "title": title,
        "body": body,
        "icon": icon,
        "badge": badge,
        "data": data or {},
    })

    subscription_info = {
        "endpoint": endpoint,
        "keys": {"p256dh": p256dh, "auth": auth},
    }

    try:
        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=os.environ["VAPID_PRIVATE_KEY"],
                vapid_claims=_vapid_claims(),
            ),
        )
        return True
    except WebPushException as exc:
        status = getattr(exc.response, "status_code", None) if exc.response else None
        if status == 410:
            logger.info("push subscription expired/gone endpoint=%s", endpoint[:40])
        else:
            logger.warning("WebPushException status=%s endpoint=%s", status, endpoint[:40])
        return False
    except Exception as exc:
        logger.warning("push send error: %s", exc)
        return False


# ── high-level: send to all subscriptions for a user ─────────────────────────

def _supabase_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _supabase_headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


async def send_push_to_user(
    user_id: str,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
    icon: str = "/icon-192.png",
    badge: str = "/favicon-32.png",
) -> int:
    """
    Fetch all push subscriptions for user_id and send a notification to each.
    Returns number of successful deliveries.
    Dead subscriptions (410 Gone) are pruned automatically.
    """
    if not _vapid_ready():
        logger.warning("VAPID keys not configured — skipping push for user=%s", user_id)
        return 0

    url = _supabase_url()
    if not url:
        return 0

    # Fetch subscriptions
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/push_subscriptions",
                params={"user_id": f"eq.{user_id}", "select": "endpoint,p256dh,auth"},
                headers=_supabase_headers(),
            )
        if resp.status_code != 200:
            logger.warning("push fetch subs failed %s", resp.status_code)
            return 0
        subs = resp.json()
    except Exception as exc:
        logger.warning("push fetch subs error: %s", exc)
        return 0

    if not subs:
        return 0

    sent = 0
    dead_endpoints: list[str] = []

    for sub in subs:
        ok = await send_push_to_subscription(
            endpoint=sub["endpoint"],
            p256dh=sub["p256dh"],
            auth=sub["auth"],
            title=title,
            body=body,
            data=data,
            icon=icon,
            badge=badge,
        )
        if ok:
            sent += 1
        else:
            dead_endpoints.append(sub["endpoint"])

    # Prune dead subscriptions
    if dead_endpoints:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                for ep in dead_endpoints:
                    await client.delete(
                        f"{url}/rest/v1/push_subscriptions",
                        params={"user_id": f"eq.{user_id}", "endpoint": f"eq.{ep}"},
                        headers=_supabase_headers(),
                    )
        except Exception as exc:
            logger.warning("push prune error: %s", exc)

    logger.info("push sent=%d dead=%d user=%s", sent, len(dead_endpoints), user_id)
    return sent
