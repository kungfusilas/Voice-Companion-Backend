import os
import json
import anthropic
from typing import AsyncGenerator
from app.models import ChatMessage
from app import search as web_search

_client: anthropic.Anthropic | None = None
_async_client: anthropic.AsyncAnthropic | None = None

SEARCH_TOOL = {
    "name": "search_web",
    "description": (
        "Search the internet for current news, real-time information, sports scores, "
        "weather, stock prices, or anything that might have changed recently. "
        "Use this whenever the user asks about something time-sensitive or current events."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query"}
        },
        "required": ["query"],
    },
}


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


def _serialize_content(content_blocks) -> list[dict]:
    """Convert Anthropic SDK content blocks to plain dicts for the messages list."""
    result = []
    for block in content_blocks:
        if block.type == "text":
            result.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            result.append({
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })
    return result


async def send_message(
    system_prompt: str,
    history: list[ChatMessage],
    user_message: str,
    model: str = "claude-opus-4-5",
    max_tokens: int = 1024,
) -> str:
    """Send a message with agentic tool-use loop (web search)."""
    client = get_client()
    messages = _build_messages(history, user_message)

    while True:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,
            tools=[SEARCH_TOOL],
        )

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    query = block.input.get("query", "")
                    result = await web_search.search(query)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "assistant", "content": _serialize_content(response.content)})
            messages.append({"role": "user", "content": tool_results})
        else:
            for block in response.content:
                if block.type == "text":
                    return block.text
            return ""


async def stream_message(
    system_prompt: str,
    history: list[ChatMessage],
    user_message: str,
    model: str = "claude-opus-4-5",
    max_tokens: int = 1024,
) -> AsyncGenerator[str, None]:
    """
    Stream the companion's reply with tool-use support.

    SSE event types:
      {"type": "token",     "text": "..."}
      {"type": "searching", "query": "..."}   — emitted when a web search starts
      {"type": "done",      "full_text": "..."}
      {"type": "error",     "message": "..."}
    """
    client = get_async_client()
    messages = _build_messages(history, user_message)
    full_text = ""

    while True:
        final_message = None

        try:
            async with client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=messages,
                tools=[SEARCH_TOOL],
            ) as stream:
                async for text in stream.text_stream:
                    full_text += text
                    yield f"data: {json.dumps({'type': 'token', 'text': text})}\n\n"

                final_message = await stream.get_final_message()

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return

        if final_message.stop_reason != "tool_use":
            break

        # Process tool calls, emit "searching" events to the client
        tool_results = []
        for block in final_message.content:
            if block.type == "tool_use":
                query = block.input.get("query", "")
                yield f"data: {json.dumps({'type': 'searching', 'query': query})}\n\n"
                result = await web_search.search(query)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        messages.append({"role": "assistant", "content": _serialize_content(final_message.content)})
        messages.append({"role": "user", "content": tool_results})

    yield f"data: {json.dumps({'type': 'done', 'full_text': full_text})}\n\n"
