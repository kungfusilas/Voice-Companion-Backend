---
name: Tiered memory context injection
description: How the ~2000-token tiered memory block for the chat system prompt is built and kept resilient to missing tables.
---

The companion's chat system prompt includes a tiered memory context block (personality, core facts, onboarding answers, then session debriefs, upcoming events, weekly insight if budget allows) built from several Supabase tables in parallel.

**Why:** Not all referenced tables are guaranteed to exist yet (e.g. `onboarding_answers` was referenced in the spec but has no created table/DDL anywhere in the codebase). If one table read fails, it must not break system prompt construction or the entire chat request.

**How to apply:** Any new Supabase-backed memory section must go through a best-effort fetch helper that swallows HTTP/network errors per-table and returns an empty result on failure, never propagating exceptions up into prompt building. Keep the ~4 chars/token budget heuristic in mind if adding new sections — tier 2 sections should be dropped/truncated first when the token budget is tight, not tier 1.

Related: post-session distillation (`memory_distillation.py`) writes into `user_core_facts` and `future_memories` after every authenticated conversation turn, deduping facts against existing rows by (category, fact-text-lowercased) rather than blind inserts.
