---
name: Async event-loop fixes
description: scoring.py and relationship.py were using sync Anthropic/supabase-py inside async handlers — now fixed.
---

## Rule
Never use `anthropic.Anthropic` (sync) or bare supabase-py `.execute()` inside `async def` handlers.

## How it was fixed
- **scoring.py**: replaced `anthropic.Anthropic` singleton with `anthropic.AsyncAnthropic`; all `client.messages.create()` calls are now `await`ed.
- **relationship.py**: added `import asyncio`; all six `.execute()` call-chains are wrapped with `await asyncio.to_thread(lambda: ...)`.
- **legacy_chapters.py**: `_generate_chapter` replaced `anthropic.Anthropic(...)` + sync `create()` with `anthropic.AsyncAnthropic(...)` + `await create()`.

**Why:** supabase-py's `.execute()` and the sync Anthropic SDK both do blocking I/O. Calling them directly in `async def` stalls the entire uvicorn event loop, serializing all concurrent requests for the duration of the call (~500ms–40s).

**How to apply:** Any new Anthropic usage in async context → use `anthropic.AsyncAnthropic`. Any new supabase-py usage in async context → wrap the full chain in `asyncio.to_thread(lambda: ...)`.
