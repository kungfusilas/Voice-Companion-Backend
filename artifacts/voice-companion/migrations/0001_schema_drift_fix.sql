-- Fix production Supabase schema drift.
--
-- The CREATE TABLE docstrings in app/relationship.py and app/proactive.py claim
-- these columns were "already applied via migration", but a direct probe of the
-- production Supabase database (kyeqlkqbhwaiwwnvjrtt) showed they were NEVER
-- applied. This caused the recurring production errors:
--   - PGRST204 / 42703: proactive_messages.activity_data missing (hourly job)
--   - 42703: relationship_stats.connection_score missing (daily check-in)
-- and silently broke relationship-score persistence (chat uses select("*"),
-- so a missing connection_score just defaulted to 50 forever).
--
-- Run this once in the Supabase SQL Editor (Dashboard -> SQL Editor). It is
-- additive and idempotent — safe to re-run. NOTE: DATABASE_URL points at the
-- Replit "helium" Postgres, NOT Supabase, so this cannot be applied via that
-- connection.

-- relationship_stats: 6 missing columns
ALTER TABLE relationship_stats ADD COLUMN IF NOT EXISTS relationship_type     text;
ALTER TABLE relationship_stats ADD COLUMN IF NOT EXISTS connection_score      integer default 50;
ALTER TABLE relationship_stats ADD COLUMN IF NOT EXISTS drift_flag            boolean default false;
ALTER TABLE relationship_stats ADD COLUMN IF NOT EXISTS drift_acknowledged_at timestamptz;
ALTER TABLE relationship_stats ADD COLUMN IF NOT EXISTS last_scored_at        timestamptz;
ALTER TABLE relationship_stats ADD COLUMN IF NOT EXISTS last_activity_sent_at timestamptz;

-- relationship_stats: upsert(on_conflict=user_id,companion_id) needs this unique key
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'relationship_stats'::regclass
          AND contype = 'u'
          AND conname = 'relationship_stats_user_companion_key'
    ) THEN
        ALTER TABLE relationship_stats
            ADD CONSTRAINT relationship_stats_user_companion_key
            UNIQUE (user_id, companion_id);
    END IF;
END $$;

-- proactive_messages: 2 missing columns
ALTER TABLE proactive_messages ADD COLUMN IF NOT EXISTS activity_type text;
ALTER TABLE proactive_messages ADD COLUMN IF NOT EXISTS activity_data jsonb;

-- Force PostgREST to reload its schema cache so the new columns are visible
-- immediately (otherwise PGRST204 can linger for a bit).
NOTIFY pgrst, 'reload schema';
