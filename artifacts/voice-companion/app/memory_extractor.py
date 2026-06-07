"""
Uses Claude to extract memorable facts from a single conversation turn
(user message + assistant reply) and saves them to Supabase.

Extracted facts are things like:
  - User's name, age, location
  - Emotions or mood the user expressed
  - Events or plans the user mentioned
  - Preferences, hobbies, relationships
  - Any personally significant details worth remembering
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
        # Save all facts concurrently
        await asyncio.gather(*[
            memory.save_memory(user_id, persona_id, fact)
            for fact in facts
        ])
        return facts
    except Exception:
        return []


def format_memories_for_prompt(memories: list[dict]) -> str:
    """
    Format a list of memory dicts into a block to inject into the system prompt.
    """
    if not memories:
        return ""
    lines = [m["content"] for m in memories if m.get("content")]
    if not lines:
        return ""
    block = "\n".join(f"- {line}" for line in lines)
    return f"\n\n## What you remember about this user:\n{block}\n"
