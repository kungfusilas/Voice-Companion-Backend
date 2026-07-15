-- Canonical ledger — shadow-mode persistence (Stage 2).
--
-- Run ONCE in the Supabase SQL Editor (Dashboard -> SQL Editor). Additive and
-- idempotent — safe to re-run. NOTE: DATABASE_URL points at the Replit Postgres,
-- NOT Supabase, so this cannot be applied via that connection.
--
-- Creates the versioned fact ledger + its append-only event log, the three
-- per-cardinality partial unique indexes (the DB mirror of the predicate
-- registry), and the apply_canonical_delta RPC (a dumb, race-safe applicator of
-- a precomputed engine delta). No user-facing reads in this phase.

CREATE TABLE IF NOT EXISTS canonical_facts (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id       text NOT NULL,
    subject_type        text NOT NULL DEFAULT 'user',
    subject_id          text NOT NULL DEFAULT 'self',
    predicate           text NOT NULL,
    cardinality         text NOT NULL,              -- single | multi | unknown (snapshotted)
    value_json          jsonb NOT NULL,
    normalized_value    text NOT NULL,
    sub_key             text,
    status              text NOT NULL DEFAULT 'active',   -- active|superseded|deleted|expired|unconfirmed
    scope               text NOT NULL DEFAULT 'global',
    companion_id        text,
    valid_from          date,
    valid_until         date,
    observed_at         date,
    supersedes_fact_id  uuid,
    confirmation_status text NOT NULL DEFAULT 'inferred',
    sensitivity         text NOT NULL DEFAULT 'none',
    version             integer NOT NULL DEFAULT 1,
    extractor_version   text,
    mapper_version      text,
    engine_version      text,
    registry_version    text,
    decision_reason     text,
    source_exchange_id  text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

-- Three partial unique indexes — the DB mirror of predicate cardinality.
CREATE UNIQUE INDEX IF NOT EXISTS one_active_single ON canonical_facts
  (owner_user_id, subject_type, subject_id, predicate, scope,
   COALESCE(companion_id, ''), COALESCE(sub_key, ''))
  WHERE status = 'active' AND cardinality = 'single';

CREATE UNIQUE INDEX IF NOT EXISTS one_active_multi ON canonical_facts
  (owner_user_id, subject_type, subject_id, predicate, scope,
   COALESCE(companion_id, ''), sub_key)
  WHERE status = 'active' AND cardinality = 'multi';

CREATE UNIQUE INDEX IF NOT EXISTS one_active_unknown ON canonical_facts
  (owner_user_id, subject_type, subject_id, predicate, scope,
   COALESCE(companion_id, ''), normalized_value)
  WHERE status = 'active' AND cardinality = 'unknown';

-- Slot-load index.
CREATE INDEX IF NOT EXISTS canonical_facts_load_idx ON canonical_facts
  (owner_user_id, subject_type, subject_id, predicate, scope, companion_id, status);

-- Idempotency: the same candidate from the same turn cannot be double-inserted.
CREATE UNIQUE INDEX IF NOT EXISTS canonical_facts_idempotency_key ON canonical_facts
  (owner_user_id, source_exchange_id, predicate, scope,
   COALESCE(companion_id, ''), normalized_value, extractor_version);

CREATE INDEX IF NOT EXISTS canonical_facts_supersedes_idx ON canonical_facts (supersedes_fact_id);

CREATE TABLE IF NOT EXISTS canonical_fact_events (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id      text,
    source_exchange_id text,
    candidate_id       text,
    event_type         text NOT NULL,
    fact_id            uuid,
    related_fact_id    uuid,
    predicate          text,
    engine_version     text,
    mapper_version     text,
    extractor_version  text,
    registry_version   text,
    decision_reason    text,
    payload_json       jsonb NOT NULL DEFAULT '{}',
    created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS canonical_fact_events_exchange_idx
  ON canonical_fact_events (owner_user_id, source_exchange_id);
