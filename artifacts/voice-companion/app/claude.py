import os
import anthropic
from app.models import ChatMessage

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set")
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


async def send_message(
    system_prompt: str,
    history: list[ChatMessage],
    user_message: str,
    model: str = "claude-opus-4-5",
    max_tokens: int = 1024,
) -> str:
    client = get_client()

    messages = [
        {"role": msg.role, "content": msg.content}
        for msg in history
    ]
    messages.append({"role": "user", "content": user_message})

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=messages,
    )

    return response.content[0].text
