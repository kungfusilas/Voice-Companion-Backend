"""
Proactive messaging system.

Checks for user+companion pairs that have been inactive for 20+ hours and
sends them a short in-character message — saved to Supabase and emailed via Resend.

SQL to run once in Supabase:

    -- Add last_active_at to relationship_stats (if not done yet)
    ALTER TABLE relationship_stats
        ADD COLUMN IF NOT EXISTS last_active_at timestamptz;

    -- Proactive messages table
    CREATE TABLE IF NOT EXISTS proactive_messages (
        id          uuid primary key default gen_random_uuid(),
        user_id     text not null,
        companion_id text not null,
        message     text not null,
        sent_at     timestamptz not null default now(),
        email_sent  bool not null default false,
        read        bool not null default false
    );

    CREATE INDEX IF NOT EXISTS proactive_messages_lookup
        ON proactive_messages (user_id, companion_id, read, sent_at DESC);
"""
import os
import logging
from datetime import datetime, timezone, timedelta

import httpx
from supabase import create_client, Client

from app import claude
from app.companions import COMPANION_MAP, build_system_prompt

logger = logging.getLogger(__name__)

_RESEND_URL = "https://api.resend.com/emails"
_PLACEHOLDER_EMAIL = "shsteroids@gmail.com"
_FROM_EMAIL = "companion@yourvoiceapp.com"

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_KEY")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        _client = create_client(url, key)
    return _client


def _parse_ts(ts_str: str | None) -> datetime | None:
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return None


def _build_email_html(companion_name: str, companion_id: str, message: str) -> str:
    domain = os.environ.get("REPLIT_DOMAINS", "").split(",")[0].strip()
    slug = companion_id.replace("companion-", "")
    avatar_url = f"https://{domain}/companion/avatars/{slug}.jpg" if domain else ""
    app_url = f"https://{domain}/companion/" if domain else "#"

    img_tag = (
        f'<img src="{avatar_url}" alt="{companion_name}" '
        f'style="width:100%;height:220px;object-fit:cover;object-position:center top;" />'
        if avatar_url else ""
    )

    return f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:32px 16px;background:#0a0a0f;font-family:-apple-system,sans-serif;">
  <div style="max-width:480px;margin:auto;background:#13131a;border-radius:16px;
              overflow:hidden;border:1px solid rgba(255,255,255,0.08);">
    {img_tag}
    <div style="padding:24px;">
      <h2 style="margin:0 0 4px;color:#c084fc;font-size:20px;">{companion_name}</h2>
      <p style="color:rgba(255,255,255,0.45);font-size:12px;margin:0 0 20px;letter-spacing:0.02em;">
        was thinking about you 💭
      </p>
      <p style="font-size:15px;line-height:1.7;color:#f0f0f5;
                background:rgba(255,255,255,0.05);padding:16px 18px;
                border-radius:12px;border-left:3px solid #c084fc;margin:0 0 20px;">
        {message}
      </p>
      <a href="{app_url}"
         style="display:block;text-align:center;background:#7c3aed;color:#fff;
                text-decoration:none;padding:13px 24px;border-radius:10px;
                font-size:14px;font-weight:600;">
        Reply to {companion_name} →
      </a>
    </div>
  </div>
</body>
</html>"""


async def _send_email(companion_name: str, companion_id: str, message: str) -> bool:
    resend_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not resend_key:
        logger.info("RESEND_API_KEY not set — skipping email for %s", companion_id)
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.post(
                _RESEND_URL,
                headers={
                    "Authorization": f"Bearer {resend_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": _FROM_EMAIL,
                    "to": [_PLACEHOLDER_EMAIL],
                    "subject": f"{companion_name} is thinking about you 💭",
                    "html": _build_email_html(companion_name, companion_id, message),
                },
            )
        if resp.status_code in (200, 201):
            return True
        logger.warning("Resend returned %s: %s", resp.status_code, resp.text[:200])
        return False
    except Exception as exc:
        logger.exception("Email send failed: %s", exc)
        return False


async def _generate_message(companion_id: str) -> str | None:
    companion = COMPANION_MAP.get(companion_id)
    if not companion:
        return None
    base_prompt = build_system_prompt(companion)
    system = (
        f"{base_prompt}\n\n"
        "The user hasn't been online for a while. Write a short proactive check-in message "
        "(1–3 sentences) fully in character — warm but not desperate, like a genuine thought "
        "that crossed your mind while they were away. Do NOT use quotation marks around the "
        "message. Just write the message itself, nothing else."
    )
    try:
        return await claude.send_message(
            system_prompt=system,
            history=[],
            user_message="[generate a proactive check-in message for this user who has been away]",
            model="claude-haiku-4-5",
            max_tokens=120,
        )
    except Exception as exc:
        logger.exception("Message generation failed for %s: %s", companion_id, exc)
        return None


async def check_and_send_proactive_messages() -> None:
    """
    Main scheduler job. Finds inactive user+companion pairs and sends them
    a proactive in-character message (Supabase + email).
    """
    logger.info("Proactive message check starting")
    try:
        db = _get_client()
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=20)
        since_24h = (now - timedelta(hours=24)).isoformat()

        # Fetch all relationship_stats rows
        stats_result = (
            db.table("relationship_stats")
            .select("user_id, companion_id, last_active_at, updated_at")
            .execute()
        )
        rows = stats_result.data or []

        for row in rows:
            user_id = row["user_id"]
            companion_id = row["companion_id"]

            # Determine last activity time
            last_active = _parse_ts(row.get("last_active_at")) or _parse_ts(row.get("updated_at"))
            if last_active is None or last_active > cutoff:
                continue  # Still active

            # Skip if we already sent a proactive message in the last 24h
            recent = (
                db.table("proactive_messages")
                .select("id")
                .eq("user_id", user_id)
                .eq("companion_id", companion_id)
                .gte("sent_at", since_24h)
                .limit(1)
                .execute()
            )
            if recent.data:
                continue

            # Generate message
            message = await _generate_message(companion_id)
            if not message:
                continue

            message = message.strip().strip('"').strip("'")

            # Save to DB
            db.table("proactive_messages").insert({
                "user_id": user_id,
                "companion_id": companion_id,
                "message": message,
                "email_sent": False,
                "read": False,
            }).execute()

            # Send email
            companion = COMPANION_MAP.get(companion_id)
            companion_name = companion.name if companion else companion_id
            email_sent = await _send_email(companion_name, companion_id, message)

            if email_sent:
                # Mark email_sent in the row we just inserted
                db.table("proactive_messages").update({"email_sent": True}).eq(
                    "user_id", user_id
                ).eq("companion_id", companion_id).eq("read", False).execute()

            logger.info(
                "Proactive message sent — user=%s companion=%s email=%s",
                user_id, companion_id, email_sent,
            )

    except Exception as exc:
        logger.exception("Proactive check failed: %s", exc)


async def get_unread_messages(user_id: str, companion_id: str) -> list[dict]:
    """Return all unread proactive messages for a user+companion pair."""
    try:
        db = _get_client()
        result = (
            db.table("proactive_messages")
            .select("id, message, sent_at")
            .eq("user_id", user_id)
            .eq("companion_id", companion_id)
            .eq("read", False)
            .order("sent_at", desc=False)
            .execute()
        )
        return result.data or []
    except Exception:
        return []


async def mark_messages_read(user_id: str, companion_id: str) -> None:
    """Mark all unread messages for this pair as read."""
    try:
        db = _get_client()
        (
            db.table("proactive_messages")
            .update({"read": True})
            .eq("user_id", user_id)
            .eq("companion_id", companion_id)
            .eq("read", False)
            .execute()
        )
    except Exception:
        pass
