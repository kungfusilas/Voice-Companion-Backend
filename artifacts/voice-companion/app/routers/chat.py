import os
import json
import asyncio
import httpx
from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from app.models import ChatMessage, ChatRequest, ChatResponse
from app import store, claude, venice_client
from app import memory as mem_store
from app import memory_extractor
from app import bond_analyzer
from app import personality_extractor
from app import future_memory_extractor
from app import conversation_store
from app import relationship
from app import scoring
from app import language as lang_module
from app.companions import ROMANTIC_MODE_PROMPTS
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

async def _get_user_profile(user_id: str) -> tuple[str, str, str]:
    """Return (subscription_tier, subscription_status, preferred_language) for an authenticated user."""
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return ("free", "inactive", "en")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/profiles",
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
                params={
                    "id": f"eq.{user_id}",
                    "select": "subscription_tier,subscription_status,preferred_language",
                    "limit": "1",
                },
            )
        if resp.status_code == 200 and resp.json():
            row = resp.json()[0]
            return (
                row.get("subscription_tier", "free") or "free",
                row.get("subscription_status", "inactive") or "inactive",
                row.get("preferred_language", "en") or "en",
            )
    except Exception:
        pass
    return ("free", "inactive", "en")


# ── Language auto-update ──────────────────────────────────────────────────────

async def _maybe_update_language(user_id: str, user_message: str, current_lang: str) -> None:
    """
    Fire-and-forget: update preferred_language when a language switch is detected.

    Priority:
    1. Explicit request ("speak Spanish", "habla español") → always update.
    2. Auto-detect from script/stopwords → only update for non-English detections
       to avoid false positives from English loanwords in other languages.
    """
    # Explicit switch takes highest priority (including switching back to English)
    explicit = lang_module.detect_explicit_switch(user_message)
    if explicit and explicit != current_lang:
        await lang_module.set_preferred_language(user_id, explicit)
        return
    # Auto-detect: commit only for non-English to prevent false positives
    detected = lang_module.detect_language(user_message)
    if detected and detected != current_lang and detected != "en":
        await lang_module.set_preferred_language(user_id, detected)


def _inject_date(prompt: str) -> str:
    today = date.today().strftime("%B %d, %Y")
    return f"Today's date is {today}.\n\n{prompt}"


async def _build_system_prompt(
    persona,
    user_id: str,
    user_message: str,
    tier: str = "free",
    preferred_language: str = "en",
    romantic_mode: bool = False,
    onboarding_context: str | None = None,
    is_guest: bool = False,
) -> str:
    """
    Build the full system prompt.
    For guests, skip Supabase calls and just use the base persona prompt.
    For authenticated users, include memories, relationship context, and drift.
    Language-awareness block is injected for ALL tiers.
    Power users get the inline roleplay capability block.
    Paid users may receive a companion-initiated offer when an upcoming event
    is detected and the weekly cooldown has elapsed.
    """
    base_prompt = persona.build_system_prompt()

    if is_guest:
        prompt = _inject_date(base_prompt)
        if onboarding_context:
            prompt += f"\n\n{onboarding_context}"
        prompt += lang_module.build_language_instruction("en")
        return prompt

    try:
        memories, stats, needs_drift = await asyncio.gather(
            mem_store.retrieve_memories(user_id, persona.id, user_message, top_k=5),
            relationship.get_stats(user_id, persona.id),
            relationship.needs_drift_inject(user_id, persona.id),
        )

        message_count = stats.get("message_count", 0)

        memory_block = memory_extractor.format_memories_for_prompt(memories)
        rel_context = relationship.build_relationship_context(persona.id, message_count)

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
            asyncio.create_task(relationship.acknowledge_drift(user_id, persona.id))

        prompt = _inject_date(
            base_prompt + romantic_block + memory_block + rel_context + drift_block
        )
        if onboarding_context:
            prompt += f"\n\n{onboarding_context}"

        # ── Language awareness — all tiers ────────────────────────────────────
        prompt += lang_module.build_language_instruction(preferred_language)

        # ── Selfie / photo capability ─────────────────────────────────────────
        tier_rank = _TIER_RANK.get(tier, 0)
        if tier_rank >= _TIER_RANK["premium"]:
            prompt += _SELFIE_CAPABILITY_BLOCK
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
                        asyncio.create_task(_record_roleplay_offer(user_id))
        else:
            # Non-Power: never proactively sell or mention higher tiers.
            prompt += _ENGAGEMENT_OVER_UPSELL

        return prompt

    except Exception:
        return _inject_date(base_prompt)


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest, req: Request, user_id: str = Depends(verify_token_or_guest)):
    is_guest = user_id.startswith("guest_")
    if is_guest:
        tier, sub_status, preferred_language = "free", "guest", "en"
    else:
        tier, sub_status, preferred_language = await _get_user_profile(user_id)
    is_premium = _is_premium_or_above(tier)
    claude_model = _select_model(tier)

    # Paywall: authenticated users must have an active paid subscription
    if not is_guest and (tier == "free" or sub_status != "active"):
        raise HTTPException(status_code=402, detail="Subscription required")

    # Usage quota check (authenticated users only)
    if not is_guest:
        await check_message_quota(user_id, tier, req.headers.get("X-Session-Id") or None)

    persona = store.get_persona(request.persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail=f"Persona '{request.persona_id}' not found")
    history = store.get_or_create_session(request.session_id, request.persona_id)
    system_prompt = await _build_system_prompt(
        persona, user_id, request.message,
        tier=tier,
        preferred_language=preferred_language,
        romantic_mode=request.romantic_mode,
        onboarding_context=request.onboarding_context,
        is_guest=is_guest,
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
        )

    # Fire-and-forget: update preferred_language if user switched languages
    asyncio.create_task(_maybe_update_language(user_id, request.message, preferred_language))

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
            persona.name, persona.build_system_prompt(), new_stage_name, rel_type
        )

    if is_premium:
        asyncio.create_task(
            memory_extractor.extract_and_save(
                user_id, persona.id, request.message, reply, language=preferred_language
            )
        )
    asyncio.create_task(relationship.increment_message_count(user_id, persona.id))

    _hist = store.get_history(request.session_id)
    _user_msgs = [m.content for m in _hist if m.role == "user"]
    if len(_user_msgs) >= 3 and len(_user_msgs) % 3 == 0:
        asyncio.create_task(
            bond_analyzer.analyze_and_save(
                user_id, persona.id, request.session_id, _user_msgs[-10:], persona.name
            )
        )

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
    is_guest = user_id.startswith("guest_")
    if is_guest:
        tier, sub_status, preferred_language = "free", "guest", "en"
    else:
        tier, sub_status, preferred_language = await _get_user_profile(user_id)
    is_premium = _is_premium_or_above(tier)
    claude_model = _select_model(tier)

    # Paywall: authenticated users must have an active paid subscription
    if not is_guest and (tier == "free" or sub_status != "active"):
        raise HTTPException(status_code=402, detail="Subscription required")

    # Usage quota check (authenticated users only)
    if not is_guest:
        await check_message_quota(user_id, tier, req.headers.get("X-Session-Id") or None)

    persona = store.get_persona(request.persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail=f"Persona '{request.persona_id}' not found")

    # Preload recent conversation history into the in-memory store if this is a fresh
    # session (survives server restarts — history lives in Supabase via conversation_store).
    if not store.get_history(request.session_id) and not is_guest:
        _recent = await conversation_store.get_recent_messages(user_id, persona.id, limit=10)
        for _m in _recent:
            store.append_message(
                request.session_id,
                ChatMessage(role=_m["role"], content=_m["content"]),
            )

    history = store.get_or_create_session(request.session_id, request.persona_id)
    system_prompt = await _build_system_prompt(
        persona, user_id, request.message,
        tier=tier,
        preferred_language=preferred_language,
        romantic_mode=request.romantic_mode,
        onboarding_context=request.onboarding_context,
        is_guest=is_guest,
    )
    use_venice = _use_venice(persona.nsfw_mode, request.nsfw_mode)

    store.append_message(request.session_id, ChatMessage(role="user", content=request.message))

    user_message = request.message

    async def event_generator():
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

                    if is_guest:
                        # Guests: skip all Supabase ops
                        yield f"data: {json.dumps(payload)}\n\n"
                        return

                    # ── Scoring (all authenticated users) ────────────────────
                    stats = await relationship.get_stats(user_id, persona.id)
                    rel_type: str = stats.get("relationship_type") or "romance"
                    old_score: int = stats.get("connection_score") or 50

                    delta = await scoring.score_user_message(user_message, rel_type, persona.name)
                    new_score = await relationship.apply_score_delta(user_id, persona.id, delta)

                    old_stage_name, _, _ = scoring.get_stage(old_score, rel_type)
                    new_stage_name, stage_min, stage_max = scoring.get_stage(new_score, rel_type)

                    stage_up_text = ""
                    if old_stage_name != new_stage_name:
                        stage_up_text = await scoring.generate_stage_up_reaction(
                            persona.name, persona.build_system_prompt(), new_stage_name, rel_type
                        )

                    # ── Drift detection every 10 messages ────────────────────
                    msg_count_before: int = stats.get("message_count") or 0
                    if (msg_count_before + 1) % 10 == 0:
                        full_history = store.get_history(request.session_id)
                        user_msgs = [m.content for m in full_history if m.role == "user"]
                        if relationship.check_drift_condition(user_msgs):
                            asyncio.create_task(relationship.mark_drift(user_id, persona.id))

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

                    # ── Language auto-update (fire-and-forget) ───────────────
                    asyncio.create_task(
                        _maybe_update_language(user_id, user_message, preferred_language)
                    )

                    # ── Memory persistence (premium only) ───────────────────
                    if is_premium:
                        asyncio.create_task(
                            memory_extractor.extract_and_save(
                                user_id, persona.id, user_message, full_text,
                                language=preferred_language,
                            )
                        )
                        asyncio.create_task(
                            future_memory_extractor.extract_and_save(user_id, persona.id, user_message, full_text)
                        )
                        asyncio.create_task(
                            conversation_store.save_exchange(
                                user_id, persona.id, request.session_id, user_message, full_text
                            )
                        )

                    # ── Personality mapping (power tier only) ──────────────
                    if tier in ("power", "elite"):
                        asyncio.create_task(
                            personality_extractor.extract_and_update(
                                user_id, user_message, full_text, language=preferred_language
                            )
                        )

                    asyncio.create_task(
                        relationship.increment_message_count(user_id, persona.id)
                    )

                    # Bond Score: analyze every 3 user messages
                    _hist = store.get_history(request.session_id)
                    _user_msgs = [m.content for m in _hist if m.role == "user"]
                    if len(_user_msgs) >= 3 and len(_user_msgs) % 3 == 0:
                        asyncio.create_task(
                            bond_analyzer.analyze_and_save(
                                user_id, persona.id, request.session_id, _user_msgs[-10:], persona.name
                            )
                        )
                    return

            except Exception:
                pass

            yield chunk

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
