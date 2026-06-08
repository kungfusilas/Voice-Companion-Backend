import json
import asyncio
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from app.models import ChatMessage, ChatRequest, ChatResponse
from app import store, claude, venice_client
from app import memory as mem_store
from app import memory_extractor
from app import bond_analyzer
from app import future_memory_extractor
from app import conversation_store
from app import relationship
from app import scoring
from app.companions import ROMANTIC_MODE_PROMPTS
from app.auth_middleware import verify_token

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


def _inject_date(prompt: str) -> str:
    today = date.today().strftime("%B %d, %Y")
    return f"Today's date is {today}.\n\n{prompt}"


async def _build_system_prompt(
    persona, user_id: str, user_message: str, romantic_mode: bool = False
) -> str:
    """
    Build the full system prompt:
    1. Base persona prompt
    2. Romantic Mode overlay (if enabled)
    3. Semantically relevant long-term memories (vector search, top-5)
    4. Relationship level context
    5. One-time drift notice (if triggered)
    """
    base_prompt = persona.build_system_prompt()
    try:
        memories, stats, needs_drift = await asyncio.gather(
            mem_store.retrieve_memories(user_id, persona.id, user_message, top_k=5),
            relationship.get_stats(user_id, persona.id),
            relationship.needs_drift_inject(user_id, persona.id),
        )

        message_count = stats.get("message_count", 0)
        # romantic_mode comes from request (client-owned state via localStorage)

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

        return _inject_date(
            base_prompt + romantic_block + memory_block + rel_context + drift_block
        )

    except Exception:
        return _inject_date(base_prompt)


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest, user_id: str = Depends(verify_token)):
    persona = store.get_persona(request.persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail=f"Persona '{request.persona_id}' not found")
    history = store.get_or_create_session(request.session_id, request.persona_id)
    system_prompt = await _build_system_prompt(persona, user_id, request.message, request.romantic_mode)
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
        )

    store.append_message(request.session_id, ChatMessage(role="user", content=request.message))
    store.append_message(request.session_id, ChatMessage(role="assistant", content=reply))

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

    asyncio.create_task(
        memory_extractor.extract_and_save(user_id, persona.id, request.message, reply)
    )
    asyncio.create_task(relationship.increment_message_count(user_id, persona.id))

    # Bond Score: analyze every 3 user messages
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
async def chat_stream(request: ChatRequest, user_id: str = Depends(verify_token)):
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
    persona = store.get_persona(request.persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail=f"Persona '{request.persona_id}' not found")
    history = store.get_or_create_session(request.session_id, request.persona_id)
    system_prompt = await _build_system_prompt(persona, user_id, request.message, request.romantic_mode)
    use_venice = _use_venice(persona.nsfw_mode, request.nsfw_mode)

    store.append_message(request.session_id, ChatMessage(role="user", content=request.message))

    stream_fn = venice_client.stream_message if use_venice else claude.stream_message
    user_message = request.message

    async def event_generator():
        async for chunk in stream_fn(
            system_prompt=system_prompt,
            history=history,
            user_message=user_message,
        ):
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

                    # ── Scoring ──────────────────────────────────────────────
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

                    asyncio.create_task(
                        memory_extractor.extract_and_save(user_id, persona.id, user_message, full_text)
                    )
                    asyncio.create_task(
                        future_memory_extractor.extract_and_save(user_id, persona.id, user_message, full_text)
                    )
                    asyncio.create_task(
                        conversation_store.save_exchange(
                            user_id, persona.id, request.session_id, user_message, full_text
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
