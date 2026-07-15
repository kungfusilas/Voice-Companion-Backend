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
    cardinality         text NOT NULL CHECK (cardinality IN ('single','multi','unknown')),
    value_json          jsonb NOT NULL,
    normalized_value    text NOT NULL,
    sub_key             text,
    status              text NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active','superseded','deleted','expired','unconfirmed')),
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
   COALESCE(companion_id, ''), COALESCE(sub_key, ''))
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

CREATE OR REPLACE FUNCTION apply_canonical_delta(
    p_supersedes jsonb DEFAULT '[]',
    p_updates    jsonb DEFAULT '[]',
    p_inserts    jsonb DEFAULT '[]',
    p_events     jsonb DEFAULT '[]'
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    ins jsonb;
    ev  jsonb;
    inserted integer := 0;
    n integer;
BEGIN
    -- (Task 4 will add supersede/update handling BEFORE this insert block.)

    -- Inserts: idempotent on the candidate identity; the partial unique indexes
    -- enforce one active row per slot.
    FOR ins IN SELECT * FROM jsonb_array_elements(p_inserts) LOOP
        INSERT INTO canonical_facts (
            id, owner_user_id, subject_type, subject_id, predicate, cardinality,
            value_json, normalized_value, sub_key, status, scope, companion_id,
            valid_from, valid_until, observed_at, supersedes_fact_id,
            confirmation_status, sensitivity, version, extractor_version,
            mapper_version, engine_version, registry_version, decision_reason,
            source_exchange_id)
        VALUES (
            COALESCE(NULLIF(ins->>'id','')::uuid, gen_random_uuid()),
            ins->>'owner_user_id',
            COALESCE(ins->>'subject_type','user'),
            COALESCE(ins->>'subject_id','self'),
            ins->>'predicate', ins->>'cardinality',
            ins->'value_json', ins->>'normalized_value', ins->>'sub_key',
            COALESCE(ins->>'status','active'), COALESCE(ins->>'scope','global'),
            ins->>'companion_id',
            NULLIF(ins->>'valid_from','')::date,
            NULLIF(ins->>'valid_until','')::date,
            NULLIF(ins->>'observed_at','')::date,
            NULLIF(ins->>'supersedes_fact_id','')::uuid,
            COALESCE(ins->>'confirmation_status','inferred'),
            COALESCE(ins->>'sensitivity','none'),
            COALESCE((ins->>'version')::int, 1),
            ins->>'extractor_version', ins->>'mapper_version', ins->>'engine_version',
            ins->>'registry_version', ins->>'decision_reason', ins->>'source_exchange_id')
        ON CONFLICT (owner_user_id, source_exchange_id, predicate, scope,
                     COALESCE(companion_id, ''), normalized_value, extractor_version)
        DO NOTHING;
        GET DIAGNOSTICS n = ROW_COUNT;
        inserted := inserted + n;
    END LOOP;

    -- Events: appended in the SAME transaction as the delta.
    FOR ev IN SELECT * FROM jsonb_array_elements(p_events) LOOP
        INSERT INTO canonical_fact_events (
            owner_user_id, source_exchange_id, candidate_id, event_type, fact_id,
            related_fact_id, predicate, engine_version, mapper_version,
            extractor_version, registry_version, decision_reason, payload_json)
        VALUES (
            ev->>'owner_user_id', ev->>'source_exchange_id', ev->>'candidate_id',
            ev->>'event_type', NULLIF(ev->>'fact_id','')::uuid,
            NULLIF(ev->>'related_fact_id','')::uuid, ev->>'predicate',
            ev->>'engine_version', ev->>'mapper_version', ev->>'extractor_version',
            ev->>'registry_version', ev->>'decision_reason',
            COALESCE(ev->'payload', ev->'payload_json', '{}'::jsonb));
    END LOOP;

    RETURN jsonb_build_object('ok', true, 'inserted', inserted);
END;
$$;
