---
name: Entitlements cap enforcement
description: Session/message/fact cap system design decisions and Supabase DDL convention.
---

## Supabase DDL convention
- The app has NO way to run DDL on Supabase (only REST + service key; DATABASE_URL points to the local Replit Postgres, not Supabase). All tables are created manually via the Supabase SQL Editor; each module documents its required SQL in its docstring.
- **How to apply:** never attempt to auto-create Supabase tables; put the SQL in the module docstring and hand it to the user to paste.

## Cap enforcement design (entitlements.py)
- All checks fail OPEN (missing table, HTTP errors, unparseable dates) per the billing guardrails rule.
- Message cap allows exactly `limit` messages: block on `new_count > limit`, not `>=`.
- Counter increments use PostgREST RPCs (`entitlements_start_session`, `entitlements_increment_message`) for atomicity, with a non-atomic read-then-write fallback only when the RPC returns non-2xx (not installed). Any 2xx RPC response is authoritative — never run the fallback after it.
- RPC SQL must REVOKE EXECUTE from anon/authenticated/public AND GRANT to service_role (revoke alone breaks the backend's own calls).
- New-session detection: durable check via `conversation_store.get_session_info(session_id)` with ownership check (`user_id` match), cached in an in-process set guarded by a per-user asyncio.Lock. Single-process only — if the app ever runs multi-worker, move idempotency to a DB session registry.
- `elite` tier mirrors `power` limits (spec only defined free/basic/premium/power).

## Reference-code adaptation rule
- User-pasted reference code using sync supabase-py clients inside async FastAPI handlers must be reimplemented with async httpx REST (this app's pattern) — sync calls block the event loop (previously caused real incidents here).
