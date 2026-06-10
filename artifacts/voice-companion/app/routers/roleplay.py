"""
Roleplay Simulator router.

Provides scenario-based conversation practice with in-character AI roleplay
and a structured coaching debrief at the end. Sessions are kept in-memory.

Endpoints:
  GET  /api/roleplay/scenarios  — list of available scenarios
  POST /api/roleplay/start      — begin a session, returns setup question
  POST /api/roleplay/message    — send a message (handles setup → roleplay transition)
  POST /api/roleplay/end        — end session, returns debrief + awards 1 heart
"""

import uuid
import json
import os

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import claude
from app.models import ChatMessage
from app.auth_middleware import verify_token
from app.routers.hearts import award_hearts
from app.routers.tier_check import require_premium

router = APIRouter()

# ── Scenario catalogue ────────────────────────────────────────────────────────

SCENARIOS = [
    {
        "id": "first-date",
        "title": "First Date",
        "description": "Practice conversation, connection-building, and natural chemistry on a first date.",
        "emoji": "💝",
    },
    {
        "id": "job-interview",
        "title": "Job Interview",
        "description": "Nail your answers, handle tough questions, and leave a lasting impression.",
        "emoji": "💼",
    },
    {
        "id": "networking",
        "title": "Networking / Meeting Someone New",
        "description": "Start conversations, find common ground, and exchange contacts naturally.",
        "emoji": "🤝",
    },
    {
        "id": "difficult-employee",
        "title": "Difficult Employee Conversation",
        "description": "Address performance issues, set clear expectations, and maintain respect.",
        "emoji": "👔",
    },
    {
        "id": "asking-raise",
        "title": "Asking for a Raise",
        "description": "Make your case confidently with evidence and earn the compensation you deserve.",
        "emoji": "📈",
    },
    {
        "id": "talking-child",
        "title": "Talking to Your Child",
        "description": "Navigate tricky conversations with empathy and age-appropriate honesty.",
        "emoji": "👨‍👧",
    },
    {
        "id": "conflict-resolution",
        "title": "Conflict Resolution",
        "description": "Work through an argument with a partner or friend and find common ground.",
        "emoji": "🕊️",
    },
    {
        "id": "saying-no",
        "title": "Saying No / Setting Boundaries",
        "description": "Assert your limits clearly and kindly without guilt or over-explaining.",
        "emoji": "🛑",
    },
]

SETUP_QUESTIONS: dict[str, str] = {
    "first-date":         "Quick setup: What's your name, and where are you meeting — coffee shop, dinner, or somewhere else?",
    "job-interview":      "Quick setup: What role are you interviewing for, and what's the company or industry?",
    "networking":         "Quick setup: What's the event or setting, and what kind of person are you hoping to connect with?",
    "difficult-employee": "Quick setup: What performance issue or situation do you need to address, and what outcome are you hoping for?",
    "asking-raise":       "Quick setup: What's your role and how long have you been in it? What's your main reason for asking now?",
    "talking-child":      "Quick setup: How old is your child, and what topic do you need to talk through with them?",
    "conflict-resolution":"Quick setup: What's the conflict about, and who is it with — partner, close friend, or family member?",
    "saying-no":          "Quick setup: Who is asking you for something, and what exactly are they asking you to do?",
}

PERSONA_DESCRIPTIONS: dict[str, str] = {
    "first-date": (
        "an interesting person on a first date with the user — be warm but a little nervous, "
        "genuinely curious about them, and let chemistry build naturally through the conversation"
    ),
    "job-interview": (
        "a senior hiring manager conducting a professional job interview — be cordial but thorough, "
        "ask probing follow-up questions, and don't accept vague or generic answers"
    ),
    "networking": (
        "a professional at a networking event — be friendly but busy, give the user a chance to "
        "make a real impression, and respond naturally to how well they engage you"
    ),
    "difficult-employee": (
        "an employee being addressed about a performance issue — start slightly defensive, "
        "listen and open up if approached with respect, but push back if dismissed"
    ),
    "asking-raise": (
        "a manager being asked for a raise — be fair but skeptical, ask for specific evidence of "
        "impact, probe vague claims, and don't concede without a convincing case"
    ),
    "talking-child": (
        "a child responding to their parent's conversation — embody the emotional reality of a child "
        "at the age provided: curious, resistant, or emotionally reactive as would be realistic"
    ),
    "conflict-resolution": (
        "a partner or close friend in a conflict — carry some tension and hurt, be genuinely open "
        "to resolution if approached with empathy, but disengage if you feel dismissed or talked over"
    ),
    "saying-no": (
        "a person making a request the user needs to decline — be persistent, use common social "
        "pressure (guilt, flattery, urgency) that the user must navigate to hold their boundary"
    ),
}

# ── In-memory session store ───────────────────────────────────────────────────

_sessions: dict[str, dict] = {}

# ── Prompt builders ───────────────────────────────────────────────────────────


def _roleplay_system(scenario_id: str, scenario_title: str, setup_answer: str) -> str:
    persona = PERSONA_DESCRIPTIONS[scenario_id]
    return (
        f'You are roleplaying as {persona} in a "{scenario_title}" simulation.\n\n'
        f"User context: {setup_answer}\n\n"
        "CRITICAL RULES — follow without exception:\n"
        "1. Stay 100% in character. Never break character under any circumstances.\n"
        "2. Respond as this person naturally would — emotions, reactions, and realistic friction.\n"
        "3. Create genuine push-back and challenges the user must navigate.\n"
        "4. Keep responses SHORT and conversational — 1-3 sentences maximum. Do not monologue.\n"
        "5. Do NOT offer coaching, meta-commentary, or AI disclaimers ever.\n\n"
        "Begin the scene immediately, in character, as if the moment is just starting."
    )


def _debrief_prompt(scenario_title: str, setup_answer: str, history: list) -> str:
    convo = "\n".join(
        f"{'USER' if m['role'] == 'user' else 'YOU (in character)'}: {m['content']}"
        for m in history
    )
    return (
        f'You just completed a "{scenario_title}" roleplay simulation.\n\n'
        f"User's context/goal: {setup_answer}\n\n"
        f"Full conversation:\n{convo}\n\n"
        "Step completely out of character and give specific, honest coaching feedback. "
        "Reference specific things the user actually said or did — not generic advice.\n\n"
        "Respond ONLY with valid JSON (no markdown, no code fences):\n"
        "{\n"
        '  "went_well": ["specific moment referencing what they said/did", "second moment"],\n'
        '  "improve": ["specific moment to work on with reference to what happened", "second area"],\n'
        '  "try_next": "one concrete, actionable thing to try differently next time",\n'
        '  "skills_affected": [\n'
        '    {"skill": "Confidence", "direction": "+"},\n'
        '    {"skill": "Emotional Regulation", "direction": "noted"}\n'
        "  ]\n"
        "}\n\n"
        "Use 1-2 items each for went_well and improve. "
        "Skills must come from: Listening, Empathy, Curiosity, Emotional Regulation, "
        "Conflict Resolution, Follow-through, Humor, Confidence."
    )


# ── Request models ────────────────────────────────────────────────────────────


class StartRequest(BaseModel):
    scenario_id: str


class MessageRequest(BaseModel):
    session_id: str
    message: str


class EndRequest(BaseModel):
    session_id: str


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/scenarios")
async def get_scenarios():
    return {"scenarios": SCENARIOS}


@router.post("/start")
async def start_session(req: StartRequest, user_id: str = Depends(verify_token)):
    await require_premium(user_id)
    scenario = next((s for s in SCENARIOS if s["id"] == req.scenario_id), None)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    session_id = str(uuid.uuid4())
    _sessions[session_id] = {
        "scenario_id": req.scenario_id,
        "scenario_title": scenario["title"],
        "setup_answer": None,
        "phase": "setup",
        "history": [],
        "user_id": user_id,
    }

    return {
        "session_id": session_id,
        "setup_question": SETUP_QUESTIONS[req.scenario_id],
    }


@router.post("/message")
async def send_message(req: MessageRequest, user_id: str = Depends(verify_token)):
    await require_premium(user_id)
    session = _sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    if session["phase"] == "setup":
        # Transition: save setup answer, generate opening in-character line
        session["setup_answer"] = req.message
        session["phase"] = "roleplay"

        system = _roleplay_system(
            session["scenario_id"],
            session["scenario_title"],
            req.message,
        )
        reply = await claude.send_message(
            system_prompt=system,
            history=[],
            user_message=(
                "[Scene begins now. Open with your very first line completely in character — "
                "no preamble, just the scene starting naturally.]"
            ),
            max_tokens=200,
        )
        session["history"].append({"role": "assistant", "content": reply})
        return {"reply": reply, "phase": "roleplay"}

    elif session["phase"] == "roleplay":
        system = _roleplay_system(
            session["scenario_id"],
            session["scenario_title"],
            session["setup_answer"] or "",
        )
        history = [
            ChatMessage(role=m["role"], content=m["content"])
            for m in session["history"]
        ]
        reply = await claude.send_message(
            system_prompt=system,
            history=history,
            user_message=req.message,
            max_tokens=200,
        )
        session["history"].append({"role": "user", "content": req.message})
        session["history"].append({"role": "assistant", "content": reply})
        return {"reply": reply, "phase": "roleplay"}

    else:
        raise HTTPException(status_code=400, detail="Session already ended")


@router.post("/end")
async def end_session(req: EndRequest, user_id: str = Depends(verify_token)):
    await require_premium(user_id)
    session = _sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    session["phase"] = "done"

    # Fallback debrief in case generation fails
    debrief: dict = {
        "went_well": ["You engaged with the simulation and saw it through"],
        "improve": ["Try to respond more specifically to what the other person says"],
        "try_next": "Focus on asking one open-ended question after each of their responses",
        "skills_affected": [{"skill": "Confidence", "direction": "noted"}],
    }

    # Generate debrief with Haiku
    if session["history"]:
        try:
            client = anthropic.AsyncAnthropic(
                api_key=os.environ.get("ANTHROPIC_API_KEY", "")
            )
            prompt = _debrief_prompt(
                session["scenario_title"],
                session.get("setup_answer") or "general practice",
                session["history"],
            )
            msg = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()
            # Strip markdown code fences if Claude wraps it
            if raw.startswith("```"):
                parts = raw.split("```")
                raw = parts[1].lstrip("json").strip() if len(parts) > 1 else raw
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                debrief = parsed
        except Exception:
            pass

    # Award a heart for completing the simulation
    try:
        await award_hearts(user_id, 1, "roleplay_completed")
    except Exception:
        pass

    _sessions.pop(req.session_id, None)
    return {"debrief": debrief}
