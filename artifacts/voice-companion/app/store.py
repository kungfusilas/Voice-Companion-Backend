"""
In-memory store for personas and conversation sessions.
In production, replace with a database-backed store.
"""
from app.models import Persona, ChatMessage


_personas: dict[str, Persona] = {}
_sessions: dict[str, list[ChatMessage]] = {}
_session_persona: dict[str, str] = {}
_session_owner: dict[str, str] = {}  # session_id -> user_id


# --- Persona operations ---

def create_persona(persona: Persona) -> Persona:
    _personas[persona.id] = persona
    return persona


def get_persona(persona_id: str) -> Persona | None:
    return _personas.get(persona_id)


def list_personas() -> list[Persona]:
    return list(_personas.values())


def delete_persona(persona_id: str) -> bool:
    if persona_id in _personas:
        del _personas[persona_id]
        return True
    return False


# --- Session / conversation history operations ---

def get_or_create_session(session_id: str, persona_id: str) -> list[ChatMessage]:
    if session_id not in _sessions:
        _sessions[session_id] = []
        _session_persona[session_id] = persona_id
    return _sessions[session_id]


def set_session_owner(session_id: str, user_id: str) -> None:
    """Record the authenticated user who owns this session (first caller wins)."""
    _session_owner.setdefault(session_id, user_id)


def get_session_owner(session_id: str) -> str | None:
    return _session_owner.get(session_id)


def append_message(session_id: str, message: ChatMessage) -> None:
    if session_id not in _sessions:
        _sessions[session_id] = []
    _sessions[session_id].append(message)


def get_history(session_id: str) -> list[ChatMessage]:
    return _sessions.get(session_id, [])


def get_session_persona_id(session_id: str) -> str | None:
    return _session_persona.get(session_id)


def clear_session(session_id: str) -> bool:
    if session_id in _sessions:
        _sessions[session_id] = []
        return True
    return False


def list_sessions() -> list[dict]:
    return [
        {
            "session_id": sid,
            "persona_id": _session_persona.get(sid, ""),
            "message_count": len(msgs),
        }
        for sid, msgs in _sessions.items()
    ]


def list_sessions_for_user(user_id: str) -> list[dict]:
    """Return only sessions owned by the given authenticated user."""
    return [
        {
            "session_id": sid,
            "persona_id": _session_persona.get(sid, ""),
            "message_count": len(msgs),
        }
        for sid, msgs in _sessions.items()
        if _session_owner.get(sid) == user_id
    ]
