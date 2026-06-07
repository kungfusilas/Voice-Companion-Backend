import os
import json
from typing import AsyncGenerator
from openai import AsyncOpenAI
from openai import APIError as OpenAIAPIError

# Venice.ai is OpenAI-compatible — just swap the base URL
VENICE_BASE_URL = "https://api.venice.ai/api/v1"
DEFAULT_VENICE_MODEL = os.environ.get("VENICE_MODEL", "llama-3.3-70b")

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        api_key = os.environ.get("VENICE_API_KEY")
        if not api_key:
            raise RuntimeError("VENICE_API_KEY environment variable is not set")
        _client = AsyncOpenAI(api_key=api_key, base_url=VENICE_BASE_URL)
    return _client


class VeniceError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _build_messages(system_prompt: str, history: list, user_message: str) -> list[dict]:
    msgs = [{"role": "system", "content": system_prompt}]
    msgs += [{"role": m.role, "content": m.content} for m in history]
    msgs.append({"role": "user", "content": user_message})
    return msgs


async def send_message(
    system_prompt: str,
    history: list,
    user_message: str,
    model: str = DEFAULT_VENICE_MODEL,
    max_tokens: int = 1024,
) -> str:
    client = get_client()
    try:
        response = await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=_build_messages(system_prompt, history, user_message),
        )
        return response.choices[0].message.content or ""
    except OpenAIAPIError as e:
        raise VeniceError(str(e), getattr(e, "status_code", 502))


async def stream_message(
    system_prompt: str,
    history: list,
    user_message: str,
    model: str = DEFAULT_VENICE_MODEL,
    max_tokens: int = 1024,
) -> AsyncGenerator[str, None]:
    """Yields SSE-formatted strings matching the claude.py stream format."""
    client = get_client()
    full_text = ""
    try:
        stream = await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=_build_messages(system_prompt, history, user_message),
            stream=True,
        )
        async for chunk in stream:
            text = chunk.choices[0].delta.content or ""
            if text:
                full_text += text
                yield f"data: {json.dumps({'type': 'token', 'text': text})}\n\n"

        yield f"data: {json.dumps({'type': 'done', 'full_text': full_text})}\n\n"
    except OpenAIAPIError as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
