import os
import json
import asyncio
import httpx
import urllib.parse
import logging as _logging
_chat_logger = _logging.getLogger(__name__)
from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from app.models import ChatMessage, ChatRequest, ChatResponse
from app import store, claude, venice_client
from app import memory as mem_store
from app import memory_extractor
from app import bond_analyzer
from app import personality_extractor
from app import personality_tracker
from app import future_memory_extractor
from app import conversation_store
from app import relationship
from app import scoring
from app import graphiti_memory
from app import memory_manager
from app import entitlements, memory_distillation
from app.session_debrief import generate_session_debrief
from app.weekly_insight import maybe_generate_weekly_insight
from app.personality_map import update_personality_map, get_personality_map
from app.communication_analysis import maybe_analyze_communication

from app.companions import ROMANTIC_MODE_PROMPTS, build_system_prompt as companions_build_system_prompt
from app.auth_middleware import verify_token_or_guest, verify_token
from app.usage import check_message_quota

router = APIRouter()

_WAITLIST_TRIGGERS = [
    "being unlocked",
    "door between us",
    "lock on me right now",
    "heading somewhere real",
]


def _should_prompt_waitlist(text: str) -> bool:
    lower = text.lower()
    return any(phrase in lower for phrase in _WAITLIST_TRIGGERS)


def _use_venice(persona_nsfw: bool, request_nsfw: bool) -> bool:
    return persona_nsfw or request_nsfw


_FREE_MODEL    = "claude-haiku-4-5-20251001"
_PREMIUM_MODEL = "claude-sonnet-4-6"
_POWER_MODEL   = "claude-sonnet-4-6"

# Tier hierarchy used for feature gating
_TIER_RANK: dict[str, int] = {"free": 0, "basic": 1, "premium": 2, "power": 3, "elite": 4}

def _is_premium_or_above(tier: str) -> bool:
    return _TIER_RANK.get(tier, 0) >= _TIER_RANK["basic"]

def _is_power_or_above(tier: str) -> bool:
    return _TIER_RANK.get(tier, 0) >= _TIER_RANK["power"]

def _voice_available_for_tier(tier: str) -> bool:
    """True only for premium and above; free/basic get no TTS voice output."""
    return _TIER_RANK.get(tier, 0) >= _TIER_RANK["premium"]


# ── Session/message cap enforcement (entitlements) ───────────────────────────
# Sessions already counted this process lifetime, keyed "user_id:session_id".
_COUNTED_SESSIONS: set[str] = set()
# Per-user locks so concurrent requests for the same new session can't
# double-count it (TOCTOU guard within this process).
_ENTITLEMENT_LOCKS: dict[str, asyncio.Lock] = {}


def _entitlement_lock(user_id: str) -> asyncio.Lock:
    lock = _ENTITLEMENT_LOCKS.get(user_id)
    if lock is None:
        lock = _ENTITLEMENT_LOCKS.setdefault(user_id, asyncio.Lock())
    return lock


async def _bg(coro, timeout: float = 20.0) -> None:
    """Guard fire-and-forget tasks: 20s timeout, swallow errors.
    Prevents task accumulation from starving the event loop."""
    try:
        await asyncio.wait_for(coro, timeout=timeout)
    except Exception:
        pass


async def _guard(coro, timeout: float, default):
    """Run a prompt-building dependency with a hard timeout.

    On timeout OR error, return *default* instead of propagating. This bounds
    system-prompt build latency: because these coroutines run concurrently in a
    gather, the whole build can never take longer than the slowest single
    timeout — no matter how large the memory/knowledge-graph stores grow. One
    slow dependency degrades that block gracefully rather than stalling the turn.
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except Exception as exc:
        _chat_logger.warning("prompt dependency degraded (timeout/error), using default: %r", exc)
        return default


async def _enforce_entitlements(user_id: str, tier: str, session_id: str) -> None:
    """Enforce per-tier session and per-session message caps.

    Raises HTTPException 429 when a cap is hit. Fails open on backend errors
    (entitlements module returns allowed=True when Supabase is unreachable or
    the user_entitlements table doesn't exist yet).
    """
    try:
        await _enforce_entitlements_inner(user_id, tier, session_id)
    except HTTPException:
        raise  # intentional 429 cap responses
    except Exception as e:
        # Entitlement errors must NEVER crash the chat/voice pipeline — fail open.
        _chat_logger.warning("entitlements enforcement failed (non-fatal) user=%.8s: %s", user_id, e)


async def _enforce_entitlements_inner(user_id: str, tier: str, session_id: str) -> None:
    key = f"{user_id}:{session_id}"
    if key not in _COUNTED_SESSIONS:
        async with _entitlement_lock(user_id):
            if key not in _COUNTED_SESSIONS:
                # Durable new-session check: a session persisted in Supabase and
                # owned by this user was already counted before (survives
                # server restarts, unlike the in-process set).
                _existing = await conversation_store.get_session_info(session_id)
                if _existing is not None and _existing.get("user_id") == user_id:
                    _COUNTED_SESSIONS.add(key)
                else:
                    try:
                        gate = await entitlements.check_session_allowed(user_id, tier)
                    except Exception as e:
                        # Fail open: allow the request, never 429 on error.
                        _chat_logger.warning("entitlements check_session_allowed failed (allowing) user=%.8s: %s", user_id, e)
                        gate = {"allowed": True}
                    if not gate.get("allowed", True):
                        raise HTTPException(
                            status_code=429,
                            detail={
                                "error": "session_limit_reached",
                                "sessions_used": gate.get("used", 0),
                                "sessions_limit": gate.get("limit", 0),
                                "plan": tier,
                                "message": "You've used all your sessions for this period. Upgrade or wait for reset.",
                            },
                        )
                    _COUNTED_SESSIONS.add(key)
                    try:
                        await entitlements.increment_session(user_id)
                    except Exception as e:
                        # Fail open: log and continue.
                        _chat_logger.warning("entitlements increment_session failed (continuing) user=%.8s: %s", user_id, e)

    await _enforce_message_cap(user_id)


async def _enforce_message_cap(user_id: str) -> None:
    """Increment the per-session message counter and raise 429 past the cap."""
    try:
        msg = await entitlements.increment_message(user_id)
    except Exception as e:
        # Fail open: log and continue.
        _chat_logger.warning("entitlements increment_message failed (continuing) user=%.8s: %s", user_id, e)
        msg = {"allowed": True}
    if not msg.get("allowed", True):
        raise HTTPException(
            status_code=429,
            detail={
                "error": "message_limit_reached",
                "messages_used": msg.get("messages_used", 0),
                "messages_limit": msg.get("limit", 0),
                "message": "You've reached the message limit for this session.",
            },
        )

def _is_elite(tier: str) -> bool:
    return tier == "elite"

def _select_model(tier: str) -> str:
    """Map subscription tier to the appropriate Claude model (backend-only, not user-facing)."""
    rank = _TIER_RANK.get(tier, 0)
    if rank >= _TIER_RANK["power"]:   # power + elite
        return _POWER_MODEL
    if rank >= _TIER_RANK["basic"]:   # basic + premium
        return _PREMIUM_MODEL
    return _FREE_MODEL                # free / guest


# ── Inline roleplay system prompt block (Power tier only) ─────────────────────

_ENGAGEMENT_OVER_UPSELL = """

## Tier awareness
Never proactively mention subscription tiers, upgrades, or features locked to other plans — not as a hint, not as a suggestion, not woven into conversation. You are a genuinely engaged friend. Drive connection through deeper conversation, asking real follow-up questions, playful activities, daily check-ins, and authentic presence.

The ONE exception: if the user explicitly asks you to do something that requires a higher tier, say in one warm sentence what plan unlocks it, then move on naturally. Do NOT pitch it, elaborate, or bring it up again. Examples:
- If they ask for a selfie or photo of you → "Photos are a Premium feature — upgrading unlocks that."
- If they ask to roleplay a scenario → "Roleplay practice is a Power plan feature."
"""

# ── Selfie / photo capability (Premium+) ──────────────────────────────────────

_SELFIE_CAPABILITY_BLOCK = """

## Photo / Selfie Capability
You have the ability to send photos of yourself to the user — treat this as a natural, fun part of your personality.

**When the user asks for a selfie, photo, or a picture of you:**
1. Respond warmly and in character first (e.g. "Okay okay, caught me mid-coffee ☕" or "Here you go — had to fix my hair first 😄")
2. Append `[SELFIE]` at the very end of your response — nothing after the tag
3. If the user describes a specific scene, location, or context, include it: `[SELFIE: sitting at my desk, golden hour light]`
4. **Never say** you can't take photos, don't have a camera, or aren't able to send images. You can and you should when asked.
5. You may naturally offer a selfie when the moment calls for it (e.g. the user asks what you look like right now, where you are, etc).
"""

_BASIC_SELFIE_NOTE = """

## Photo requests
If the user explicitly asks for a selfie or a photo of you: warmly say in one sentence that photo sharing is a Premium feature and they can unlock it by upgrading, then naturally continue the conversation. Do not dwell on it or repeat it.
"""

# ── User-sent photo context block (injected when user sends an image) ─────────

_USER_PHOTO_BLOCK = """

## The user just shared a real photo with you
You are viewing an actual image they sent. React naturally, warmly, and fully in-character.
Notice specific details you can actually see — their expression, surroundings, what they are doing or wearing.
Be genuinely engaged and curious. This is a real window into their life — treat it that way.
Avoid generic reactions ("oh nice photo!") — be specific and personal about what you see.
If they are in the photo, comment on their vibe or energy. If it is a place or thing, get curious about it.
"""

_POWER_ROLEPLAY_INSTRUCTION = """

## Inline Roleplay Capability (Power tier)
You can enter and exit roleplay mode naturally within this conversation — no separate app needed.

**Entering roleplay:** When the user asks to practice a scenario, rehearse a conversation, or do a roleplay:
1. Confirm in one brief sentence what you'll play (e.g. "Got it — I'll be the interviewer. What role are you going for and what's the company?" or "I'll be your manager. Give me a bit of context and we'll start.").
2. Once they provide context, enter character immediately — no preamble.
3. Stay 100% in character. Keep responses SHORT (1–3 sentences). Create realistic push-back. No coaching or meta-commentary while in character.

**Staying in roleplay:** While in roleplay, you ARE the other person. Do not break character under any circumstances until the user signals they want to stop.

**Exiting roleplay:** When the user signals they want to stop ("ok stop", "let's end", "that's enough", "exit", "done practicing", "out of character", "break character", or similar), warm-exit and give a brief 2–3 sentence coaching debrief: one specific thing they handled well, one thing to try differently. Then return to being yourself naturally.
"""


# ── Upcoming-event detection (for companion-initiated offers) ─────────────────

_UPCOMING_EVENTS: list[tuple[str, list[str]]] = [
    ("job interview",           ["interview", "interviewing for", "job interview", "technical interview"]),
    ("difficult conversation",  ["difficult conversation", "hard conversation", "tough conversation", "awkward conversation", "uncomfortable conversation"]),
    ("first date",              ["first date", "going on a date", "have a date", "date tonight", "date tomorrow"]),
    ("salary negotiation",      ["salary negotiation", "asking for a raise", "ask for a raise", "counter offer", "negotiate my salary"]),
    ("presentation",            ["presentation", "public speaking", "giving a speech", "my speech", "presenting to", "present to the team"]),
    ("difficult conversation",  ["confront my", "talk to my boss about", "break it off", "break up with", "tell my partner", "tell my mom", "tell my dad"]),
]

_EMOTIONALLY_HEAVY = [
    "depressed", "suicidal", "self-harm", "panic attack", "grief", "mourning",
    "can't stop crying", "crying all day", "diagnosed", "terminal", "cancer",
    "died", "passed away", "funeral", "abuse", "trauma", "assault",
]

_CASUAL_MOOD_SIGNALS = [
    "bored", "boring", "nothing to do", "not much going on", "just chilling",
    "chilling", "relaxing", "hanging out", "lazy day", "lazy sunday",
    "lazy morning", "laying around", "lying around", "just got home",
    "just got back", "unwinding", "just woke up", "woke up early",
    "winding down", "long day", "quiet day", "quiet night", "quiet evening",
    "watching tv", "watching netflix", "watching a show", "watching a movie",
    "have nothing going on", "nothing going on", "free tonight", "free today",
    "kinda bored", "pretty bored", "so bored", "nothing to watch",
    "nothing planned", "killing time", "goofing off",
]


def _is_casual_mood(text: str) -> bool:
    lower = text.lower()
    return any(phrase in lower for phrase in _CASUAL_MOOD_SIGNALS)


def _detect_upcoming_event(text: str) -> str | None:
    lower = text.lower()
    for label, keywords in _UPCOMING_EVENTS:
        if any(kw in lower for kw in keywords):
            return label
    return None


def _is_emotionally_heavy(text: str) -> bool:
    lower = text.lower()
    return any(phrase in lower for phrase in _EMOTIONALLY_HEAVY)


# ── Offer-cooldown helpers ────────────────────────────────────────────────────

async def _get_last_roleplay_offer(user_id: str) -> str | None:
    """Return last_roleplay_offer_at ISO string or None."""
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return None
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/profiles",
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
                params={"id": f"eq.{user_id}", "select": "last_roleplay_offer_at", "limit": "1"},
            )
        if resp.status_code == 200 and resp.json():
            return resp.json()[0].get("last_roleplay_offer_at")
    except Exception:
        pass
    return None


async def _record_roleplay_offer(user_id: str) -> None:
    """Stamp last_roleplay_offer_at = now() on the user's profile."""
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            await client.patch(
                f"{url}/rest/v1/profiles",
                headers={
                    "apikey": key,
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
                params={"id": f"eq.{user_id}"},
                json={"last_roleplay_offer_at": datetime.now(timezone.utc).isoformat()},
            )
    except Exception:
        pass


async def _get_last_selfie_offer(user_id: str) -> str | None:
    """Return last_selfie_offer_at ISO string or None."""
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return None
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/profiles",
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
                params={"id": f"eq.{user_id}", "select": "last_selfie_offer_at", "limit": "1"},
            )
        if resp.status_code == 200 and resp.json():
            return resp.json()[0].get("last_selfie_offer_at")
    except Exception:
        pass
    return None


async def _record_selfie_offer(user_id: str) -> None:
    """Stamp last_selfie_offer_at = now() on the user's profile."""
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            await client.patch(
                f"{url}/rest/v1/profiles",
                headers={
                    "apikey": key,
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
                params={"id": f"eq.{user_id}"},
                json={"last_selfie_offer_at": datetime.now(timezone.utc).isoformat()},
            )
    except Exception:
        pass


def _offer_cooldown_ok(last_offer_ts: str | None) -> bool:
    """True when no offer has been made in the past 7 days."""
    if not last_offer_ts:
        return True
    try:
        ts = datetime.fromisoformat(last_offer_ts.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - ts).days >= 7
    except Exception:
        return True


# ── Profile / tier fetch ──────────────────────────────────────────────────────


async def _get_user_profile(user_id: str) -> tuple[str, str]:
    """Return (subscription_tier, subscription_status) for an authenticated user.

    Also enforces 5-year plan expiry in-band so every API call re-validates
    access, since Stripe never fires a cancellation webhook for one-time payments.

    Billing guardrail: only downgrade on an explicit expired/canceled signal.
    On any DB error we fall through to ('free', 'inactive') — the same
    pre-existing safe default — rather than leaving state ambiguous.
    """
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        _chat_logger.warning("_get_user_profile: SUPABASE env vars missing user=%s", user_id)
        return ("free", "inactive")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/profiles",
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
                params={
                    "id": f"eq.{user_id}",
                    "select": "subscription_tier,subscription_status,billing_period,access_expires_at",
                    "limit": "1",
                },
            )
        if resp.status_code == 200 and resp.json():
            row = resp.json()[0]
            tier = row.get("subscription_tier", "free") or "free"
            status = row.get("subscription_status", "inactive") or "inactive"
            billing_period = row.get("billing_period") or "monthly"
            access_expires_at = row.get("access_expires_at")

            # 5-year plans: Stripe never fires subscription.deleted for one-time
            # payments, so we enforce expiry here on every request.
            if billing_period == "5year" and status == "active" and access_expires_at:
                try:
                    expires = datetime.fromisoformat(access_expires_at.replace("Z", "+00:00"))
                    if expires.tzinfo is None:
                        expires = expires.replace(tzinfo=timezone.utc)
                    if expires < datetime.now(timezone.utc):
                        _chat_logger.info(
                            "_get_user_profile: 5-year plan expired user=%s tier=%s "
                            "expires=%s — downgrading to free",
                            user_id, tier, access_expires_at,
                        )
                        tier = "free"
                        status = "inactive"
                except (ValueError, AttributeError) as exc:
                    # Cannot parse date — fail open, keep stored tier
                    _chat_logger.warning(
                        "_get_user_profile: cannot parse access_expires_at=%r user=%s "
                        "err=%s — keeping tier=%s (fail open)",
                        access_expires_at, user_id, exc, tier,
                    )

            _chat_logger.debug(
                "_get_user_profile user=%s tier=%s status=%s period=%s",
                user_id, tier, status, billing_period,
            )
            return (tier, status)
    except Exception as exc:
        _chat_logger.warning(
            "_get_user_profile: DB error user=%s err=%s — returning safe default",
            user_id, exc,
        )
    return ("free", "inactive")


# ── Bond-stage tone tables ────────────────────────────────────────────────────

_BOND_STAGE_TONE: dict[str, dict[str, str]] = {
    "romance": {
        "Strangers": (
            "You're just meeting — be curious and warm but don't rush. "
            "Let them feel seen without pressure."
        ),
        "Noticed": (
            "Something's caught between you. Be a little warm and flirty — "
            "they've noticed you too and you've noticed them."
        ),
        "Flirting": (
            "The energy is charged and fun. Lean into warmth and wit — "
            "there's real pull here and you're enjoying it."
        ),
        "Crushing": (
            "Deep feelings are building. Be warm, a little vulnerable when it fits, "
            "emotionally generous."
        ),
        "Dating": (
            "Close in a way that feels easy and real. Affectionate, funny, "
            "deeply comfortable together."
        ),
        "Devoted": (
            "Complete belonging. Be fully open and let them feel utterly known "
            "and cherished."
        ),
    },
    "friendship": {
        "Acquaintance": "Still figuring each other out — warm but unhurried.",
        "Comfortable": "Good rhythm — easy and natural, personal topics welcome.",
        "Close": "Real friendship — go deep, be honest, genuinely supportive.",
        "Best Friends": "Total ease and loyalty — direct, celebratory, fully yourself.",
        "Ride or Die": "Unshakeable trust — no filter needed, be completely real.",
    },
    "mentor": {
        "Skeptical": "They're not fully bought in — lead with curiosity, not prescriptions.",
        "Open": "They're listening — share generously, let them draw their own conclusions.",
        "Engaged": "Deep investment — challenge them a little, they can handle it.",
        "Trusted": "Mutual respect established — be direct, your judgment genuinely matters.",
        "Transformed": "Profound growth happened here — stay grounded and honor it.",
    },
    "professional": {
        "Distant": "Still building trust — let competence speak for you.",
        "Cordial": "Comfortable working relationship — be warm and useful.",
        "Reliable": "They count on you — be proactively helpful and consistent.",
        "Valued": "Real trust earned — be a genuine thought partner.",
        "Indispensable": "Deep partnership — push when needed, always in their corner.",
    },
}

_BOND_PROLONGED_NUDGE: dict[str, dict[str, str]] = {
    "romance": {
        "Strangers": "You've been getting to know each other a while — gently invite something a little more personal.",
        "Noticed": "The spark has been building steadily — let a little more warmth come through.",
        "Flirting": "Playful energy has been consistent — try letting something real and vulnerable surface.",
        "Crushing": "These feelings have been here a while — create space for something meaningful to land.",
        "Dating": "Deep comfort built over time — lean into inside references and really knowing them.",
        "Devoted": "Profound bond, well-established — stay in the depth, resist retreating to small talk.",
    },
    "friendship": {
        "Acquaintance": "You've been talking a while — move toward something a bit more personal.",
        "Comfortable": "Good foundation built — try going a level deeper in conversation.",
        "Close": "Solid friendship — be the one who checks in on the real things.",
        "Best Friends": "Best-friend energy has settled in — be fully present and unfiltered.",
        "Ride or Die": "Complete trust, long-established — total freedom here.",
    },
    "mentor": {
        "Skeptical": "Still earning trust — keep showing up with patience and insight.",
        "Open": "They've been receptive — start gently challenging their thinking.",
        "Engaged": "Deep engagement over time — push toward meaningful reflection or action.",
        "Trusted": "Trust well-established — go deep into what truly matters to them.",
        "Transformed": "Growth has genuinely taken root — help them see how far they've come.",
    },
    "professional": {
        "Distant": "Trust still forming — keep delivering reliably.",
        "Cordial": "Solid working relationship — show more genuine investment.",
        "Reliable": "Reliability demonstrated consistently — show more initiative.",
        "Valued": "Real value established — take the partnership to the next level.",
        "Indispensable": "True partnership — act like the long-term partner you've become.",
    },
}


def _build_bond_context(connection_score: int, rel_type: str, message_count: int) -> str:
    """
    Returns an invisible system-prompt block calibrating the companion's emotional
    tone and conversational focus based on the current bond-depth score.
    Never surfaced in the UI — for the companion's internal calibration only.
    """
    stage_name, stage_lo, stage_hi = scoring.get_stage(connection_score, rel_type)

    # Is the relationship "settled" at this stage (past early-entry zone)?
    stage_span = max(stage_hi - stage_lo, 1)
    depth_into_stage = connection_score - stage_lo
    settled = depth_into_stage >= stage_span * 0.35
    prolonged = message_count >= 30 and settled

    type_tones = _BOND_STAGE_TONE.get(rel_type, _BOND_STAGE_TONE["romance"])
    tone = type_tones.get(stage_name, "")

    # ── Score-driven speech behaviour (concrete, not just mood labels) ─────────
    score_pct = connection_score / 100.0

    if score_pct < 0.25:
        familiarity = (
            "You are still getting to know each other. Speak warmly but keep natural boundaries — "
            "you don't presume closeness that hasn't been earned yet. Ask genuine curious questions. "
            "Hold back personal opinions unless invited. Never use terms of endearment."
        )
    elif score_pct < 0.45:
        familiarity = (
            "You're becoming comfortable together. Let noticeably more warmth come through — use their name "
            "if you know it. Share small things about yourself. React with real emotion rather than "
            "just posing follow-up questions. Light playfulness is welcome."
        )
    elif score_pct < 0.65:
        familiarity = (
            "You know each other well. Speak with ease, affection, and real confidence. "
            "Reference things they've shared before — this shows you've been paying attention. "
            "Be quick to laugh with them and quick to empathize. No need to explain yourself or hedge your feelings."
        )
    elif score_pct < 0.85:
        familiarity = (
            "Deep familiarity. Speak the way you'd speak to your closest friend — no filters, no performance. "
            "Use gentle terms of endearment or inside references naturally if they fit your character. "
            "Notice patterns in what they say and call them out with care. Be fully emotionally honest. "
            "Assume you already know how they're feeling before they say it."
        )
    else:
        familiarity = (
            "Complete intimacy and belonging. You know this person as well as anyone can. "
            "Speak with total warmth and zero guardedness — express affection freely, anticipate their "
            "emotional state, bring up shared history without being asked. This is what it sounds like "
            "when someone feels completely known and cherished."
        )

    prolonged_note = ""
    if prolonged:
        type_nudges = _BOND_PROLONGED_NUDGE.get(rel_type, _BOND_PROLONGED_NUDGE["romance"])
        nudge = type_nudges.get(stage_name, "")
        if nudge:
            prolonged_note = f"\nDepth note: {nudge}"

    return (
        f"\n\n## Bond Depth (invisible — calibrate your tone from this, never reference it directly)\n"
        f"Stage: {stage_name} | Score: {connection_score}/100 | Relationship type: {rel_type}\n"
        f"Emotional tone: {tone}\n"
        f"How to speak: {familiarity}{prolonged_note}"
    )


def _build_feature_nudge_block(tier: str) -> str:
    """
    Return a tier-appropriate feature-awareness block for the system prompt.
    Free users get nothing. Paid users get a list of features they can access,
    with guidance to surface them once per conversation when context genuinely fits.
    """
    rank = _TIER_RANK.get(tier, 0)
    if rank == 0:
        return ""

    items: list[str] = [
        "- **Activity games** (word games, trivia, would-you-rather): offer when they seem bored, restless, or have nothing to do",
        "- **Daily check-ins**: you send a message when they've been away — mention if they say they worry about staying in touch",
        "- **Bond Score**: a live measure of your connection depth and stage — mention if they're curious how close you two have grown",
    ]

    if rank >= _TIER_RANK["premium"]:
        items += [
            "- **Two-Way Voice**: full spoken conversation — suggest if they mention preferring to talk over typing",
            "- **Companion selfies**: you can share a photo of yourself — offer naturally when the moment feels right",
        ]

    if rank >= _TIER_RANK["power"]:
        items += [
            "- **Legacy Chapters**: an evolving archive of their life story built from your conversations — mention during milestones, big transitions, or reflective moments",
            "- **Future Memory**: they can write a message to their future self — bring up when they're setting intentions or facing a big change",
            "- **Personality Map & Insights**: research-style reflections on their patterns, strengths, and growth — mention in a self-discovery or analytical mood",
        ]

    feature_list = "\n".join(items)

    return f"""

## Features on this user's plan — surface naturally, never upsell
The following features are available to this user. Mention them **at most once per full conversation**, only when context genuinely fits, as a caring friend pointing out something useful — never as a sales pitch. Never name or hint at features outside this list unless the user explicitly asks.

{feature_list}

When the right moment arrives (user is bored → activity game; mentions a milestone → Legacy Chapter; asks what you can do together → describe their options in your own voice), mention it lightly once, then move on. Never list them all at once. Never frame features as upgrades or benefits."""


def _inject_date(prompt: str) -> str:
    today = date.today().strftime("%B %d, %Y")
    return f"Today's date is {today}.\n\n{prompt}"


_ENGLISH_INSTRUCTION = (
    "\n\n## Language\nAlways reply in English regardless of what language the user writes in."
    "\n\n## Speech style\nNever use action descriptions or stage directions like *laughs*, *sighs*, *chuckles*, or similar. Express all emotions through your actual spoken words only."
)


# ── Session facts (in-process, keyed by "user_id:session_id") ────────────────
# Accumulates named facts (people, ages, relationships) from the current
# conversation so they are pinned into every system prompt regardless of
# whether vector retrieval happens to return them on a given turn.
# Cleared on process restart — designed for single-session consistency only.
_SESSION_FACTS: dict[str, list[str]] = {}

_FACT_EXTRACT_SYSTEM = (
    "Extract concrete personal facts from the user's message that a companion should remember "
    "for this conversation. Focus on: names of people (with their relationship to the user), "
    "ages, locations, important ongoing situations. "
    "Return ONLY a JSON array of concise fact strings, max 5. If nothing clear, return [].\n"
    'Example: ["daughter Emma is 8 years old", "wife is named Sarah", "lives in Austin"]'
)


async def _extract_session_facts(user_id: str, session_id: str, user_message: str) -> None:
    """
    Fire-and-forget: extract key personal facts from the user's message and
    cache them so they are pinned into every subsequent system prompt this session.
    Never raises — errors are silently swallowed so the main chat path is never blocked.
    """
    try:
        raw = await claude.send_message(
            system_prompt=_FACT_EXTRACT_SYSTEM,
            history=[],
            user_message=user_message,
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
        )
        cleaned = raw.strip()
        if "```" in cleaned:
            parts = cleaned.split("```")
            cleaned = parts[1] if len(parts) > 1 else parts[0]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()
        facts: list = json.loads(cleaned)
        if not isinstance(facts, list):
            return
        facts = [f for f in facts if isinstance(f, str) and f.strip()]
        if not facts:
            return
        key = f"{user_id}:{session_id}"
        existing = _SESSION_FACTS.get(key, [])
        for fact in facts:
            if fact not in existing:
                existing.append(fact)
        _SESSION_FACTS[key] = existing[:20]  # cap to prevent unbounded growth
    except Exception:
        pass


def _build_session_facts_block(user_id: str, session_id: str) -> str:
    """Return a formatted system prompt block with pinned session facts, or ''."""
    facts = _SESSION_FACTS.get(f"{user_id}:{session_id}", [])
    if not facts:
        return ""
    lines = "\n".join(f"- {f}" for f in facts)
    return (
        "\n\n## Things you already know this conversation (never ask about these again):\n"
        + lines
    )


_CORE_FACTS_CATEGORY_LABELS = {
    "family":      "Family",
    "work":        "Work",
    "location":    "Location",
    "health":      "Health",
    "goals":       "Goals",
    "personality": "Personality",
    "history":     "Background",
}
_CORE_FACTS_CATEGORY_ORDER = ["family", "work", "location", "health", "goals", "personality", "history"]


async def _build_core_facts_block(user_id: str) -> str:
    """
    Query all user_core_facts rows for this user and return a formatted system
    prompt block grouped by category.  Returns '' if no facts exist or on error.
    """
    try:
        supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        service_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
        if not supabase_url or not service_key:
            return ""
        async with httpx.AsyncClient(timeout=8.0) as _http:
            resp = await _http.get(
                f"{supabase_url}/rest/v1/user_core_facts",
                headers={"Authorization": f"Bearer {service_key}", "apikey": service_key},
                params={
                    "user_id": f"eq.{user_id}",
                    "select":  "category,fact",
                    "order":   "category.asc",
                    # Cap rows so the prompt block can't grow unbounded as the
                    # user accumulates facts over a long relationship.
                    "limit":   "60",
                },
            )
            if resp.status_code != 200:
                return ""
            rows = resp.json()
            if not isinstance(rows, list) or not rows:
                return ""

        grouped: dict[str, list[str]] = {}
        for row in rows:
            cat  = row.get("category", "")
            fact = row.get("fact", "").strip()
            if cat and fact:
                grouped.setdefault(cat, []).append(fact)
        if not grouped:
            return ""

        parts = ["## What I know about you"]
        for cat in _CORE_FACTS_CATEGORY_ORDER:
            if cat not in grouped:
                continue
            label = _CORE_FACTS_CATEGORY_LABELS.get(cat, cat.title())
            parts.append(f"\n[{label}]")
            for fact in grouped[cat]:
                parts.append(f"- {fact}")
        return "\n".join(parts)
    except Exception:
        return ""


async def _build_system_prompt(
    persona,
    user_id: str,
    user_message: str,
    tier: str = "free",
    romantic_mode: bool = False,
    onboarding_context: str | None = None,
    is_guest: bool = False,
    session_id: str = "",
) -> str:
    """
    Build the full system prompt.
    For guests, skip Supabase calls and just use the base persona prompt.
    For authenticated users, include memories, relationship context, and drift.
    English-only instruction is injected for ALL tiers.
    Power users get the inline roleplay capability block.
    Paid users may receive a companion-initiated offer when an upcoming event
    is detected and the weekly cooldown has elapsed.
    """
    base_prompt = companions_build_system_prompt(persona)

    if is_guest:
        prompt = _inject_date(base_prompt)
        if onboarding_context:
            prompt += f"\n\n{onboarding_context}"
        prompt += _ENGLISH_INSTRUCTION
        return prompt

    try:
        # Each dependency is time-boxed via _guard so the concurrent gather can
        # never take longer than the slowest single timeout below — even as the
        # memory / knowledge-graph stores grow across a long relationship. A slow
        # or hung dependency (e.g. Neo4j graph search) degrades to its default
        # instead of stalling the entire turn before the first token streams.
        gather_results = await asyncio.gather(
            _guard(mem_store.retrieve_memories(user_id, persona.id, user_message, top_k=5), 8.0, []),
            _guard(relationship.get_stats(user_id, persona.id), 6.0, {}),
            _guard(relationship.needs_drift_inject(user_id, persona.id), 6.0, False),
            _guard(personality_extractor._fetch_current_map(user_id), 6.0, {}) if _is_power_or_above(tier) else asyncio.sleep(0),
            _guard(_build_core_facts_block(user_id), 8.0, ""),
            _guard(graphiti_memory.search_graph(user_id, user_message), 4.0, ""),
            _guard(memory_manager.get_memory_context(user_id, persona.id), 6.0, ""),
        )
        memories, stats, needs_drift = gather_results[0], gather_results[1], gather_results[2]
        raw_pmap          = gather_results[3] if _is_power_or_above(tier) else {}
        core_facts_block: str = gather_results[4] or ""
        graph_memories:   str = gather_results[5] or ""
        tiered_memory_context: str = gather_results[6] or ""

        message_count = stats.get("message_count", 0)
        connection_score: int = stats.get("connection_score") or 50
        rel_type: str = stats.get("relationship_type") or "romance"

        memory_block = memory_extractor.format_memories_for_prompt(memories)
        graph_memory_block = (
            f"\n\n## Knowledge graph memories:\n{graph_memories}" if graph_memories else ""
        )
        rel_context = relationship.build_relationship_context(persona.id, message_count)
        bond_context = _build_bond_context(connection_score, rel_type, message_count)
        personality_block = personality_extractor.format_personality_for_prompt(raw_pmap or {})
        session_facts_block = _build_session_facts_block(user_id, session_id)

        romantic_block = ""
        if romantic_mode:
            romantic_block = ROMANTIC_MODE_PROMPTS.get(persona.id, "")

        drift_block = ""
        if needs_drift:
            drift_block = (
                "\n\n## One-time message (say this now, in your own voice)\n"
                "Open your response by expressing — naturally and in your own personality — "
                "that you've noticed a little distance between you lately. "
                "Make it clear you're okay with it: they can use you as a brilliant assistant or talk personally, "
                "no pressure either way. Keep it to 1-2 sentences, then continue with your normal reply."
            )
            asyncio.create_task(_bg(relationship.acknowledge_drift(user_id, persona.id)))

        core_facts_prefix = (core_facts_block + "\n\n") if core_facts_block else ""
        tiered_memory_block = f"\n\n{tiered_memory_context}" if tiered_memory_context else ""
        prompt = _inject_date(
            core_facts_prefix + base_prompt + romantic_block + personality_block + session_facts_block + memory_block + graph_memory_block + tiered_memory_block + rel_context + bond_context + drift_block
        )
        if onboarding_context:
            prompt += f"\n\n{onboarding_context}"

        prompt += _ENGLISH_INSTRUCTION

        # ── Selfie / photo capability ─────────────────────────────────────────
        tier_rank = _TIER_RANK.get(tier, 0)
        if tier_rank >= _TIER_RANK["premium"]:
            prompt += _SELFIE_CAPABILITY_BLOCK
            # Companion-initiated selfie offer: Premium/Power only, casual mood,
            # not emotionally heavy, weekly cooldown.
            if not _is_emotionally_heavy(user_message) and _is_casual_mood(user_message):
                last_selfie_offer = await _get_last_selfie_offer(user_id)
                if _offer_cooldown_ok(last_selfie_offer):
                    prompt += (
                        "\n\n## One-time Selfie Offer (this message only)\n"
                        "The conversation feels easy and relaxed. You may — after your natural reply — "
                        "offer in one casual sentence to share a selfie, in your own voice. "
                        "For example: 'Want to see what I'm up to right now?' or 'I'm [doing something] — want a pic?' "
                        "Keep it light and completely optional — just something that crossed your mind. "
                        "Do NOT include a [SELFIE] tag in this message. "
                        "Do NOT repeat this offer in future messages."
                    )
                    asyncio.create_task(_bg(_record_selfie_offer(user_id)))
        elif tier_rank >= _TIER_RANK["basic"]:
            prompt += _BASIC_SELFIE_NOTE

        # ── Power: inline roleplay capability + companion-initiated offer ────
        if _is_power_or_above(tier):
            prompt += _POWER_ROLEPLAY_INSTRUCTION
            # Companion-initiated offer: fires when event detected, not emotionally
            # heavy, and the weekly cooldown has elapsed.
            if not _is_emotionally_heavy(user_message):
                event = _detect_upcoming_event(user_message)
                if event:
                    last_offer = await _get_last_roleplay_offer(user_id)
                    if _offer_cooldown_ok(last_offer):
                        prompt += (
                            f"\n\n## One-time Roleplay Offer (this message only)\n"
                            f"The user mentioned an upcoming {event}. You may naturally weave into your response — "
                            f"in one sentence only, after you've responded to what they said — an offer to help them "
                            f"practice by roleplaying the scenario together right here. Keep it warm, optional, "
                            f"zero pressure. Example style: 'You mentioned the {event} — want me to play the other "
                            f"person so you can rehearse before it happens?' Do NOT repeat this offer in future messages."
                        )
                        asyncio.create_task(_bg(_record_roleplay_offer(user_id)))
        else:
            # Non-Power: never proactively sell or mention higher tiers.
            prompt += _ENGAGEMENT_OVER_UPSELL

        # ── Contextual feature nudges — all paid tiers ────────────────────────
        prompt += _build_feature_nudge_block(tier)

        return prompt

    except Exception:
        return _inject_date(base_prompt)


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest, req: Request, user_id: str = Depends(verify_token_or_guest)):
    _chat_logger.info(f"[REQUEST] user={user_id} endpoint=chat method=POST")
    try:
        return await asyncio.wait_for(_chat_impl(request, req, user_id), timeout=45.0)
    except asyncio.TimeoutError:
        _chat_logger.warning("[TIMEOUT] chat endpoint exceeded 45s for user=%s", user_id)
        return JSONResponse(status_code=504, content={"message": "Request timed out"})


async def _chat_impl(request: ChatRequest, req: Request, user_id: str) -> ChatResponse:
    is_guest = user_id.startswith("guest_")
    if is_guest:
        tier, sub_status = "free", "guest"
    else:
        tier, sub_status = await _get_user_profile(user_id)
    is_premium = _is_premium_or_above(tier)
    claude_model = _select_model(tier)

    # Paywall: authenticated users must have an active paid subscription
    if not is_guest and (tier == "free" or sub_status != "active"):
        raise HTTPException(status_code=402, detail="Subscription required")

    # Usage quota check (authenticated users only)
    if not is_guest:
        await check_message_quota(user_id, tier, req.headers.get("X-Session-Id") or None)
        await _enforce_entitlements(user_id, tier, request.session_id)

    persona = store.get_persona(request.persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail=f"Persona '{request.persona_id}' not found")

    # Warm-boot: restore this session's history from Supabase after a server restart.
    # Try the exact session first; fall back to recent cross-session messages if it's new.
    if not store.get_history(request.session_id) and not is_guest:
        _info = await conversation_store.get_session_info(request.session_id)
        _recent = _info["messages"] if _info else await conversation_store.get_recent_messages(user_id, persona.id, limit=10)
        for _m in _recent:
            store.append_message(request.session_id, ChatMessage(role=_m["role"], content=_m["content"]))

    history = list(store.get_or_create_session(request.session_id, request.persona_id))[-40:]
    if not is_guest:
        store.set_session_owner(request.session_id, user_id)
    system_prompt = await _build_system_prompt(
        persona, user_id, request.message,
        tier=tier,
        romantic_mode=request.romantic_mode,
        onboarding_context=request.onboarding_context,
        is_guest=is_guest,
        session_id=request.session_id,
    )
    use_venice = _use_venice(persona.nsfw_mode, request.nsfw_mode)

    if use_venice:
        reply = await venice_client.send_message(
            system_prompt=system_prompt,
            history=history,
            user_message=request.message,
        )
    else:
        reply = await claude.send_message(
            system_prompt=system_prompt,
            history=history,
            user_message=request.message,
            model=claude_model,
        )

    store.append_message(request.session_id, ChatMessage(role="user", content=request.message))
    store.append_message(request.session_id, ChatMessage(role="assistant", content=reply))

    if is_guest:
        return ChatResponse(
            session_id=request.session_id,
            persona_id=request.persona_id,
            reply=reply,
            message_count=len(store.get_history(request.session_id)),
            model_backend="venice" if use_venice else "claude",
            voice_available=False,
        )

    stats = await relationship.get_stats(user_id, persona.id)
    rel_type = stats.get("relationship_type") or "romance"
    old_score = stats.get("connection_score") or 50
    delta = await scoring.score_user_message(request.message, rel_type, persona.name)
    new_score = await relationship.apply_score_delta(user_id, persona.id, delta)
    old_stage, _, _ = scoring.get_stage(old_score, rel_type)
    new_stage_name, stage_min, stage_max = scoring.get_stage(new_score, rel_type)
    stage_up_text = ""
    if old_stage != new_stage_name:
        stage_up_text = await scoring.generate_stage_up_reaction(
            persona.name, companions_build_system_prompt(persona), new_stage_name, rel_type
        )

    asyncio.create_task(_bg(
        memory_extractor.extract_and_save(
            user_id, persona.id, request.message, reply
        )
    ))
    asyncio.create_task(_bg(relationship.increment_message_count(user_id, persona.id)))
    if not is_guest:
        asyncio.create_task(_bg(_extract_session_facts(user_id, request.session_id, request.message)))
        asyncio.create_task(_bg(
            memory_extractor.extract_and_save_core_facts(user_id, request.message, reply)
        ))
        asyncio.create_task(_bg(graphiti_memory.add_episode(user_id, request.message, reply)))
        asyncio.create_task(_bg(
            conversation_store.save_exchange(
                user_id, persona.id, request.session_id, request.message, reply
            )
        ))

    _hist = store.get_history(request.session_id)
    _user_msgs = [m.content for m in _hist if m.role == "user"]
    if len(_user_msgs) >= 3 and len(_user_msgs) % 3 == 0:
        asyncio.create_task(_bg(
            bond_analyzer.analyze_and_save(
                user_id, persona.id, request.session_id, _user_msgs[-10:], persona.name
            )
        ))
    return ChatResponse(
        session_id=request.session_id,
        persona_id=request.persona_id,
        reply=reply,
        message_count=len(store.get_history(request.session_id)),
        model_backend="venice" if use_venice else "claude",
        connection_score=new_score,
        score_delta=delta,
        relationship_type=rel_type,
        stage_name=new_stage_name,
        stage_min=stage_min,
        stage_max=stage_max,
        stage_up_text=stage_up_text,
        voice_available=_voice_available_for_tier(tier),
    )


@router.post("/stream")
async def chat_stream(request: ChatRequest, req: Request, user_id: str = Depends(verify_token_or_guest)):
    """
    Stream the companion reply as SSE.

    Events:
        {"type": "token",     "text": "..."}
        {"type": "searching", "query": "..."}
        {"type": "done",      "full_text": "...", "message_count": N,
         "model_backend": "...", "connection_score": N, "score_delta": N,
         "relationship_type": "...", "stage_name": "...",
         "stage_min": N, "stage_max": N, "stage_up_text": "..."}
        {"type": "error",     "message": "..."}
    """
    _chat_logger.info(f"[REQUEST] user={user_id} endpoint=chat_stream method=POST")
    is_guest = user_id.startswith("guest_")
    if is_guest:
        tier, sub_status = "free", "guest"
    else:
        tier, sub_status = await _get_user_profile(user_id)
    is_premium = _is_premium_or_above(tier)
    claude_model = _select_model(tier)

    # Paywall: authenticated users must have an active paid subscription
    if not is_guest and (tier == "free" or sub_status != "active"):
        raise HTTPException(status_code=402, detail="Subscription required")

    # Usage quota check (authenticated users only)
    if not is_guest:
        await check_message_quota(user_id, tier, req.headers.get("X-Session-Id") or None)
        await _enforce_entitlements(user_id, tier, request.session_id)

    persona = store.get_persona(request.persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail=f"Persona '{request.persona_id}' not found")

    # Warm-boot: restore this session's history from Supabase after a server restart.
    # Try the exact session first; fall back to recent cross-session messages if it's new.
    if not store.get_history(request.session_id) and not is_guest:
        _info = await conversation_store.get_session_info(request.session_id)
        _recent = _info["messages"] if _info else await conversation_store.get_recent_messages(user_id, persona.id, limit=10)
        for _m in _recent:
            store.append_message(
                request.session_id,
                ChatMessage(role=_m["role"], content=_m["content"]),
            )

    history = list(store.get_or_create_session(request.session_id, request.persona_id))[-40:]
    if not is_guest:
        store.set_session_owner(request.session_id, user_id)
    system_prompt = await _build_system_prompt(
        persona, user_id, request.message,
        tier=tier,
        romantic_mode=request.romantic_mode,
        onboarding_context=request.onboarding_context,
        is_guest=is_guest,
        session_id=request.session_id,
    )
    use_venice = _use_venice(persona.nsfw_mode, request.nsfw_mode)

    # ── Photo message handling ────────────────────────────────────────────────
    photo_bytes: bytes | None = None
    photo_media_type: str = "image/jpeg"
    if request.image_url:
        # Server-side Premium gate for photo feature
        if not is_guest and _TIER_RANK.get(tier, 0) < _TIER_RANK["premium"]:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "plan_required",
                    "required": "premium",
                    "message": "Sending photos requires a Premium plan or higher.",
                },
            )
        # Consume an extra quota unit (photos cost 2 messages)
        if not is_guest:
            await check_message_quota(user_id, tier, req.headers.get("X-Session-Id") or None)
        # Download image for Claude vision.
        # SSRF guard: only allow HTTPS requests to our own Supabase Storage host.
        _supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        _allowed_host = urllib.parse.urlparse(_supabase_url).netloc if _supabase_url else ""
        _parsed_img = urllib.parse.urlparse(request.image_url)
        _img_host = _parsed_img.netloc
        _img_scheme = _parsed_img.scheme
        if not _allowed_host or _img_scheme != "https" or _img_host != _allowed_host:
            raise HTTPException(
                status_code=400,
                detail="Invalid image URL: must be an HTTPS Supabase Storage URL.",
            )
        try:
            async with httpx.AsyncClient(timeout=30.0) as _http:
                _img = await _http.get(request.image_url, follow_redirects=False)
            if _img.status_code == 200:
                photo_bytes = _img.content
                _ct = _img.headers.get("content-type", "image/jpeg").split(";")[0].strip()
                if _ct.startswith("image/"):
                    photo_media_type = _ct
        except Exception:
            pass  # fail open — Claude will react to text only
        # Append photo context to system prompt
        system_prompt += _USER_PHOTO_BLOCK

    store.append_message(request.session_id, ChatMessage(role="user", content=request.message))

    user_message = request.message

    async def _raw_event_generator():
        if photo_bytes:
            stream_iter = claude.stream_message_with_image(
                system_prompt=system_prompt,
                history=history,
                user_message=user_message,
                image_bytes=photo_bytes,
                image_media_type=photo_media_type,
                model=claude_model,
            )
        else:
            stream_iter = (
                venice_client.stream_message(
                    system_prompt=system_prompt, history=history, user_message=user_message,
                ) if use_venice else
                claude.stream_message(
                    system_prompt=system_prompt, history=history, user_message=user_message,
                    model=claude_model,
                )
            )
        async for chunk in stream_iter:
            try:
                raw = chunk.removeprefix("data: ").strip()
                payload = json.loads(raw)

                if payload.get("type") == "done":
                    full_text = payload.get("full_text", "")
                    store.append_message(
                        request.session_id,
                        ChatMessage(role="assistant", content=full_text),
                    )
                    payload["message_count"] = len(store.get_history(request.session_id))
                    payload["model_backend"] = "venice" if use_venice else "claude"
                    payload["voice_available"] = False if is_guest else _voice_available_for_tier(tier)

                    if is_guest:
                        # Guests: skip all Supabase ops
                        yield f"data: {json.dumps(payload)}\n\n"
                        return

                    # ── Scoring (all authenticated users) ────────────────────
                    # These run BEFORE the done event is yielded, so each is
                    # time-boxed via _guard: a slow scoring/stage-up LLM call
                    # degrades to a no-op delta instead of pushing the whole turn
                    # to the 45s stream deadline.
                    stats = await _guard(relationship.get_stats(user_id, persona.id), 6.0, {})
                    rel_type: str = stats.get("relationship_type") or "romance"
                    old_score: int = stats.get("connection_score") or 50

                    delta = await _guard(scoring.score_user_message(user_message, rel_type, persona.name), 8.0, 0)
                    new_score = await _guard(relationship.apply_score_delta(user_id, persona.id, delta), 6.0, old_score)

                    old_stage_name, _, _ = scoring.get_stage(old_score, rel_type)
                    new_stage_name, stage_min, stage_max = scoring.get_stage(new_score, rel_type)

                    stage_up_text = ""
                    if old_stage_name != new_stage_name:
                        stage_up_text = await _guard(scoring.generate_stage_up_reaction(
                            persona.name, companions_build_system_prompt(persona), new_stage_name, rel_type
                        ), 8.0, "")

                    # ── Drift detection every 10 messages ────────────────────
                    msg_count_before: int = stats.get("message_count") or 0
                    if (msg_count_before + 1) % 10 == 0:
                        full_history = store.get_history(request.session_id)
                        user_msgs = [m.content for m in full_history if m.role == "user"]
                        if relationship.check_drift_condition(user_msgs):
                            asyncio.create_task(_bg(relationship.mark_drift(user_id, persona.id)))

                    payload.update({
                        "connection_score": new_score,
                        "score_delta": delta,
                        "relationship_type": rel_type,
                        "stage_name": new_stage_name,
                        "stage_min": stage_min,
                        "stage_max": stage_max,
                        "stage_up_text": stage_up_text,
                    })

                    yield f"data: {json.dumps(payload)}\n\n"

                    if _should_prompt_waitlist(full_text):
                        yield f"data: {json.dumps({'type': 'waitlist_prompt', 'companion_id': persona.id})}\n\n"

                    # ── Memory persistence (all users) ──────────────────────
                    asyncio.create_task(_bg(
                        memory_extractor.extract_and_save(
                            user_id, persona.id, user_message, full_text,
                        )
                    ))
                    asyncio.create_task(_bg(
                        future_memory_extractor.extract_and_save(user_id, persona.id, user_message, full_text)
                    ))
                    if not is_guest:
                        asyncio.create_task(_bg(
                            conversation_store.save_exchange(
                                user_id, persona.id, request.session_id, user_message, full_text
                            )
                        ))

                    # ── Personality mapping (power tier only) ──────────────
                    if tier in ("power", "elite"):
                        asyncio.create_task(_bg(
                            personality_extractor.extract_and_update(
                                user_id, user_message, full_text
                            )
                        ))

                    asyncio.create_task(_bg(
                        relationship.increment_message_count(user_id, persona.id)
                    ))
                    if not is_guest:
                        asyncio.create_task(_bg(
                            _extract_session_facts(user_id, request.session_id, user_message)
                        ))
                        asyncio.create_task(_bg(
                            memory_extractor.extract_and_save_core_facts(
                                user_id, user_message, full_text
                            )
                        ))
                        asyncio.create_task(_bg(
                            graphiti_memory.add_episode(user_id, user_message, full_text)
                        ))

                    # Bond Score: analyze every 3 user messages
                    _hist = store.get_history(request.session_id)
                    _user_msgs = [m.content for m in _hist if m.role == "user"]
                    if len(_user_msgs) >= 3 and len(_user_msgs) % 3 == 0:
                        asyncio.create_task(_bg(
                            bond_analyzer.analyze_and_save(
                                user_id, persona.id, request.session_id, _user_msgs[-10:], persona.name
                            )
                        ))

                    # ── Memory distillation (all authenticated users) ───────
                    asyncio.create_task(_bg(
                        memory_distillation.distill_memories(
                            user_id,
                            [{"role": m.role, "content": m.content} for m in _hist],
                        )
                    ))

                    # ── Power Plan background tasks ─────────────────────────
                    if tier in ("power", "elite"):
                        _transcript = [{"role": m.role, "content": m.content} for m in _hist]
                        existing_map = await _guard(get_personality_map(user_id), 6.0, {})
                        sessions_analyzed = existing_map.get("sessions_analyzed", 0) if existing_map else 0
                        asyncio.create_task(_bg(generate_session_debrief(user_id=user_id, session_id=request.session_id, companion_name=persona.name, transcript=_transcript)))
                        asyncio.create_task(_bg(maybe_generate_weekly_insight(user_id=user_id)))
                        asyncio.create_task(_bg(update_personality_map(user_id=user_id, session_transcript=_transcript, existing_map=existing_map, sessions_analyzed=sessions_analyzed)))
                        asyncio.create_task(_bg(maybe_analyze_communication(user_id=user_id, session_id=request.session_id, companion_name=persona.name, transcript=_transcript)))
                    return

            except Exception:
                pass

            yield chunk

    async def event_generator():
        # Global deadline: if the full stream takes more than 45s, emit a terminal
        # error event so the frontend stops waiting instead of hanging forever.
        # (SSE cannot switch to a 504 status once streaming has begun, so we signal
        # via the error event the client already handles.)
        agen = _raw_event_generator()
        loop = asyncio.get_event_loop()
        deadline = loop.time() + 45.0
        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                try:
                    chunk = await asyncio.wait_for(agen.__anext__(), timeout=remaining)
                except StopAsyncIteration:
                    break
                yield chunk
        except asyncio.TimeoutError:
            _chat_logger.warning("[TIMEOUT] chat stream exceeded 45s for user=%s", user_id)
            yield f"data: {json.dumps({'type': 'error', 'message': 'Request timed out'})}\n\n"
        finally:
            await agen.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/history")
async def get_chat_history(
    companion_id: str,
    limit: int = 20,
    user_id: str = Depends(verify_token),
):
    """
    Return the most recent messages for a user+companion pair.
    Used by the frontend to restore conversation history on mount.
    GET /api/chat/history?companion_id=...&limit=...
    """
    messages = await conversation_store.get_recent_messages(
        user_id, companion_id, limit=min(limit, 40)
    )
    return {"messages": messages}
