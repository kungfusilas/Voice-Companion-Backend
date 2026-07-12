---
name: Exact-content spec tasks
description: Gotchas when the user supplies "create file with this exact content" task specs for the voice companion app.
---

## Check for collisions before creating spec-named files
- Spec file names can collide with existing modules (e.g. a spec's `relationship.py` collided with the existing per-companion relationship-type router). Create under a distinct name (`relationship_profile.py`), register separately, and flag the deviation.
- **Why:** blindly writing the spec file clobbers shipped features; routes may still coexist fine under the same path prefix if the paths differ.
- **How to apply:** before STEP 1 of any exact-content task, grep `app/routers/` and `main.py` for the target module/route names.

## Standing accepted deviations (re-apply, always flag)
- Spec's `ChatPage.tsx` = actual `src/pages/Chat.tsx`.
- Sync `anthropic.Anthropic` in async endpoints → use `AsyncAnthropic` (event-loop convention).
- Chat-path additions go in BOTH the non-stream and SSE stream endpoints (frontend uses stream).
- Wrap chat-path external lookups in fail-open try/except per billing-guardrails conventions.
- Spec code sometimes has broken string literals (literal newlines inside quotes) — fix to `"\n"` escapes.
