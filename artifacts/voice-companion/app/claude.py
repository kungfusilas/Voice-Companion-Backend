import os
import json
import anthropic
from typing import AsyncGenerator
from app.models import ChatMessage

_client: anthropic.Anthropic | None = None
_async_client: anthropic.AsyncAnthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set")
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def get_async_client() -> anthropic.AsyncAnthropic:
    global _async_client
    if _async_client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set")
        _async_client = anthropic.AsyncAnthropic(api_key=api_key)
    return _async_client


def _build_messages(history: list[ChatMessage], user_message: str) -> list[dict]:
    messages = [{"role": msg.role, "content": msg.content} for msg in history]
    messages.append({"role": "user", "content": user_message})
    return messages


async def send_message(
    system_prompt: str,
    history: list[ChatMessage],
    user_message: str,
    model: str = "claude-opus-4-5",
    max_tokens: int = 1024,
) -> str:
    client = get_client()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=_build_messages(history, user_message),
    )
    return response.content[0].text


async def stream_message(
    system_prompt: str,
    history: list[ChatMessage],
    user_message: str,
    model: str = "claude-opus-4-5",
    max_tokens: int = 1024,
) -> AsyncGenerator[str, None]:
    """
    Yields SSE-formatted strings.
    Each token:  data: {"type":"token","text":"..."}\n\n
    On finish:   data: {"type":"done","full_text":"..."}\n\n
    On error:    data: {"type":"error","message":"..."}\n\n
    """
    client = get_async_client()
    full_text = ""

    try:
        async with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=_build_messages(history, user_message),
        ) as stream:
            async for text in stream.text_stream:
                full_text += text
                payload = json.dumps({"type": "token", "text": text})
                yield f"data: {payload}\n\n"

        done_payload = json.dumps({"type": "done", "full_text": full_text})
        yield f"data: {done_payload}\n\n"

    except Exception as e:
        error_payload = json.dumps({"type": "error", "message": str(e)})
        yield f"data: {error_payload}\n\n"
