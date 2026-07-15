"""Repository — persistence-backed application of engine candidates to the ledger.

Production talks to Supabase via PostgREST/httpx (PostgrestExecutor); tests use a
direct psycopg connection to a local Postgres (PsycopgExecutor). The retry loop
reloads and recomputes on a conflict — a stale-version CAS abort (SQLSTATE 40001)
or a real insert race (23505) — both surfaced as ConflictError.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timezone
from typing import Any, Protocol


class ConflictError(Exception):
    """The ledger signalled a retryable conflict (CAS 40001 or unique-violation 23505)."""


_CONFLICT_SQLSTATES = {"40001", "23505"}


class LedgerExecutor(Protocol):
    async def fetch_active_facts(self, owner_user_id: str, subject_type: str,
                                 subject_id: str, predicate: str, scope: str,
                                 companion_id: str | None) -> list[dict]: ...

    async def apply_delta(self, supersedes: list[dict], updates: list[dict],
                          inserts: list[dict], events: list[dict]) -> dict: ...


def _json(value: Any) -> str:
    """date-aware JSON encoder (the engine/delta emit Python date objects)."""
    def default(o):
        if isinstance(o, date):
            return o.isoformat()
        raise TypeError(f"not JSON-serializable: {type(o)}")
    return json.dumps(value, default=default)


class PsycopgExecutor:
    """Test/local executor over a sync psycopg connection (async via to_thread)."""

    _COLS = ("id", "owner_user_id", "subject_type", "subject_id", "predicate",
             "cardinality", "value_json", "normalized_value", "sub_key", "status",
             "scope", "companion_id", "valid_from", "valid_until", "observed_at",
             "supersedes_fact_id", "confirmation_status", "sensitivity", "version",
             "extractor_version", "mapper_version", "engine_version",
             "registry_version", "decision_reason", "source_exchange_id")

    def __init__(self, conn):
        self._conn = conn

    async def fetch_active_facts(self, owner_user_id, subject_type, subject_id,
                                 predicate, scope, companion_id):
        return await asyncio.to_thread(self._fetch, owner_user_id, subject_type,
                                       subject_id, predicate, scope, companion_id)

    def _fetch(self, owner_user_id, subject_type, subject_id, predicate, scope, companion_id):
        sql = (f"SELECT {', '.join(self._COLS)} FROM canonical_facts "
               "WHERE owner_user_id=%s AND subject_type=%s AND subject_id=%s "
               "AND predicate=%s AND scope=%s AND status='active' "
               "AND companion_id IS NOT DISTINCT FROM %s")
        cur = self._conn.execute(sql, [owner_user_id, subject_type, subject_id,
                                       predicate, scope, companion_id])
        return [dict(zip(self._COLS, r)) for r in cur.fetchall()]

    async def apply_delta(self, supersedes, updates, inserts, events):
        return await asyncio.to_thread(self._apply, supersedes, updates, inserts, events)

    def _apply(self, supersedes, updates, inserts, events):
        import psycopg
        try:
            row = self._conn.execute(
                "SELECT apply_canonical_delta(%s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb)",
                [_json(supersedes), _json(updates), _json(inserts), _json(events)],
            ).fetchone()[0]
            return row
        except psycopg.Error as exc:
            if getattr(exc, "sqlstate", None) in _CONFLICT_SQLSTATES:
                raise ConflictError(str(exc)) from exc
            raise
