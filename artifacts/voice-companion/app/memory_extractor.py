"""
Memory extraction and prompt formatting.

extract_and_save  — fire-and-forget post-chat: Haiku decides what to save,
                    memory.save_memory embeds and stores it in pgvector.
format_memories   — formats retrieved vector memories for system prompt injection.
"""
from app import memory


async def extract_and_save(
    user_id: str,
    persona_id: str,
    user_message: str,
    assistant_reply: str,
) -> None:
    """
    Fire-and-forget: ask Haiku whether this exchange is worth remembering.
    If yes, embed the content and persist to pgvector.
    Errors are silently swallowed — never blocks or slows chat.
    """
    try:
        result = await memory.should_remember(user_message, assistant_reply)
        if result:
            await memory.save_memory(
                user_id=user_id,
                companion_id=persona_id,
                content=result["content"],
                memory_type=result.get("type", "fact"),
                importance=int(result.get("importance", 5)),
            )
    except Exception:
        pass


def format_memories_for_prompt(memories: list[dict]) -> str:
    """
    Format a list of memory dicts (from vector retrieval) into a system prompt block.
    Includes memory_type label so the companion knows the context.
    """
    if not memories:
        return ""
    lines = []
    for m in memories:
        content = m.get("content", "").strip()
        if not content:
            continue
        mtype = m.get("memory_type", "fact")
        lines.append(f"- [{mtype}] {content}")
    if not lines:
        return ""
    return (
        "\n\n## What you remember about this person:\n"
        + "\n".join(lines)
        + "\nUse these memories naturally — weave them into conversation when relevant, "
        "don't just list them. Never say 'I remember that...' robotically. "
        "Reference them the way a close friend would."
    )
