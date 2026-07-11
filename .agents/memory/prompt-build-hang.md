---
name: Prompt-build / turn-hang root cause
description: Why chat turns hang (and the record button sticks) as a relationship grows, and the rule that prevents it
---

# Chat turn hangs → stuck record button

**Symptom:** after several voice exchanges the record button sticks — the transcribed text shows under the button but never sends (mobile + web).

**Root cause chain (not a client bug):**
- Client `sendMessage` guards with `if (busyRef.current) return` and only clears `busyRef` in the `finally` *after* the SSE `for await` loop ends.
- If the server stream never terminates, that `finally` never runs → `busyRef` stays true → every later recording early-returns → "text shows, never sends."
- The stream stalled server-side in `_build_system_prompt`, which runs a many-way `asyncio.gather` of external dependencies (memory retrieval, relationship stats, personality map, core-facts Supabase query, **Neo4j/graphiti graph search**, memory-manager context) **every turn**. `gather` blocks on the slowest call. `graphiti search_graph` awaited the Neo4j query with **no timeout**, and that query slows as the knowledge graph grows → indefinite stall *before the first token streams*.
- A separate 45s stream deadline only masks it (turn ends in an error instead of hanging forever).

**Rule / how to apply:**
- Any external dependency awaited on the per-turn path (prompt build AND the stream `done` post-processing: scoring, stage-up reaction, personality-map read) MUST be individually time-boxed so one slow dependency degrades to a safe default instead of stalling the turn. Use the `_guard(coro, timeout, default)` helper in `chat.py`; give graph/Neo4j the tightest budget.
- Any query that returns "all rows for a user" (e.g. `user_core_facts`) must carry a `limit` — prompt blocks grow unbounded over a long relationship otherwise.
- **Why:** history was already capped at `[-40:]` and TTS uses single-message text, so neither was the growth source — the unbounded growth was memory/graph reads feeding the system prompt. Fixing the client reset alone would not help; the fix has to keep the stream terminating quickly.
