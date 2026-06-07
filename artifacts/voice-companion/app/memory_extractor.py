"""
Uses Claude to extract memorable facts from a single conversation turn
(user message + assistant reply) and saves them to Supabase.

Also provides emotional memory surfacing: given the current user message,
finds stored memories that are emotionally or topically relevant so the
companion can naturally reference them.
"""
import json
import asyncio
from app import claude, memory

_EXTRACTION_PROMPT = """You are a memory extraction system for an AI companion app.

Given a conversation turn between a user and their AI companion, extract any memorable
facts about the USER that are worth remembering long-term. Focus on:
- Personal details (name, age, where they live, job, etc.)
- Emotions or mood they expressed
- Events, plans, or experiences they mentioned
- Preferences, hobbies, interests, dislikes
- People, pets, or relationships they mentioned
- Any significant life events or challenges

Rules:
- Extract ONLY facts about the user — not the assistant's statements.
- Each fact must be a short, standalone sentence (≤ 25 words).
- If there are no memorable facts, return an empty list.
- Return ONLY valid JSON: a list of strings, nothing else.

Example output:
["User's name is Alex.", "User has a dog named Biscuit.", "User mentioned feeling anxious about a job interview next week."]
"""

# Words that signal emotional content worth surfacing from memory
_EMOTIONAL_KEYWORDS: frozenset[str] = frozenset({
    "stress", "stressed", "stressing", "anxious", "anxiety", "nervous", "nervousness",
    "worried", "worry", "scared", "fear", "afraid", "panic", "overwhelmed",
    "sad", "sadness", "depressed", "depression", "upset", "hurt", "lonely",
    "happy", "happiness", "excited", "proud", "grateful", "thrilled", "relieved",
    "angry", "anger", "frustrated", "frustration", "annoyed",
    "interview", "job", "work", "promotion", "fired", "hired", "career",
    "exam", "test", "grade", "school", "college",
    "sick", "health", "hospital", "doctor", "diagnosis",
    "family", "mom", "dad", "sister", "brother", "friend", "partner",
    "breakup", "relationship", "dating", "loss", "grief", "death",
    "money", "debt", "moving", "homeless",
})

_STOP_WORDS: frozenset[str] = frozenset({
    "i", "a", "an", "the", "is", "it", "of", "and", "or", "to", "in", "on",
    "at", "for", "with", "my", "me", "you", "we", "they", "he", "she",
    "that", "this", "was", "are", "do", "did", "have", "had", "has",
    "can", "will", "would", "could", "should", "just", "so", "but", "not",
    "what", "how", "why", "when", "where", "who", "if", "be", "been", "about",
    "up", "out", "get", "got", "very", "really", "am", "im", "its", "its",
})


def _keywords(text: str) -> set[str]:
    """Extract meaningful lowercase words from text, stripping stop words."""
    words = set(text.lower().split())
    return words - _STOP_WORDS


def find_emotionally_relevant(user_message: str, memories: list[dict]) -> list[dict]:
    """
    Given the user's current message and a list of memory dicts,
    return up to 3 memories that are emotionally or topically relevant.
    Returns [] if the message has no emotional signal.
    """
    if not memories or not user_message.strip():
        return []

    message_words = _keywords(user_message)
    emotional_signal = message_words & _EMOTIONAL_KEYWORDS

    if not emotional_signal:
        return []

    scored: list[tuple[int, dict]] = []
    for mem in memories:
        mem_words = _keywords(mem.get("content", ""))
        overlap = message_words & mem_words
        emotional_overlap = overlap & _EMOTIONAL_KEYWORDS
        score = len(emotional_overlap) * 3 + len(overlap)
        if score > 0:
            scored.append((score, mem))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [mem for _, mem in scored[:3]]


def format_memories_for_prompt(memories: list[dict]) -> str:
    """Format a list of memory dicts into a block to inject into the system prompt."""
    if not memories:
        return ""
    lines = [m["content"] for m in memories if m.get("content")]
    if not lines:
        return ""
    block = "\n".join(f"- {line}" for line in lines)
    return f"\n\n## What you remember about this user:\n{block}\n"


def format_emotional_memories_for_prompt(user_message: str, memories: list[dict]) -> str:
    """
    Find emotionally relevant memories and return a prompt block that
    instructs the companion to weave them in naturally — only if relevant.
    """
    relevant = find_emotionally_relevant(user_message, memories)
    if not relevant:
        return ""
    lines = [m["content"] for m in relevant if m.get("content")]
    if not lines:
        return ""
    block = "\n".join(f"- {line}" for line in lines)
    return (
        f"\n\n## Memories to consider referencing naturally:\n{block}\n"
        "If any of these connect to what the user just said, weave them in "
        "as if you genuinely remembered — don't announce that you're 'checking' anything. "
        "Keep it subtle and human."
    )


async def extract_and_save(
    user_id: str,
    persona_id: str,
    user_message: str,
    assistant_reply: str,
) -> list[str]:
    """
    Fire-and-forget: extract facts from this turn and persist them.
    Returns the list of extracted fact strings (may be empty).
    Errors are silently swallowed so they never break the chat flow.
    """
    try:
        turn = f"User: {user_message}\nAssistant: {assistant_reply}"
        raw = await claude.send_message(
            system_prompt=_EXTRACTION_PROMPT,
            history=[],
            user_message=turn,
            model="claude-haiku-4-5",
            max_tokens=512,
        )
        facts: list[str] = json.loads(raw)
        if not isinstance(facts, list):
            return []
        facts = [f for f in facts if isinstance(f, str) and f.strip()]
        await asyncio.gather(*[
            memory.save_memory(user_id, persona_id, fact)
            for fact in facts
        ])
        return facts
    except Exception:
        return []
