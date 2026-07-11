---
name: Supabase schema drift (prod)
description: The app's real data lives in Supabase, NOT DATABASE_URL; docstring "migrations" were never applied to prod
---

# Supabase schema drift

**Two databases exist and they are different:**
- `DATABASE_URL` → Replit built-in Postgres (`helium` / `heliumdb`).
- The voice app's relationship/proactive/usage data → **Supabase** (`SUPABASE_URL` + `SUPABASE_SERVICE_KEY`, PostgREST). This is `kyeqlkqbhwaiwwnvjrtt.supabase.co`.

**Why this matters:** the `CREATE TABLE ... (already applied via migration)` docstrings in `app/relationship.py` and `app/proactive.py` are **not** trustworthy — several columns were never applied to the production Supabase tables. Verified by probing prod directly.

Columns found MISSING in prod (July 2026), fixed by `artifacts/voice-companion/migrations/0001_schema_drift_fix.sql`:
- `relationship_stats`: relationship_type, connection_score, drift_flag, drift_acknowledged_at, last_scored_at, last_activity_sent_at
- `proactive_messages`: activity_type, activity_data

**How to apply:** Supabase DDL cannot be run via the service key (PostgREST = data plane only) nor via `DATABASE_URL` (wrong DB). The user must paste the SQL into the Supabase SQL Editor. End the migration with `NOTIFY pgrst, 'reload schema';` or PGRST204 lingers.

**Silent failure mode to watch:** chat path reads `relationship_stats` with `.select("*")`, so a missing column does NOT error — it just defaults (e.g. connection_score → 50 forever, so score persistence is silently dead). Only queries that name the column explicitly (daily_checkin) surface a 42703. When a feature "does nothing" in prod but works locally, suspect drift, not code.

**To verify prod schema quickly:** probe `GET {SUPABASE_URL}/rest/v1/<table>?select=<col>&limit=1` with the service key — 400/42703 means the column is missing.
