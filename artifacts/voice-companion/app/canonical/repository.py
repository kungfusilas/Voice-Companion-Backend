"""Repository — persistence-backed application of engine candidates to the ledger.

Production talks to Supabase via PostgREST/httpx (PostgrestExecutor); tests use a
direct psycopg connection to a local Postgres (PsycopgExecutor). The retry loop
reloads and recomputes on a conflict — a stale-version CAS abort (SQLSTATE 40001)
or a real insert race (23505) — both surfaced as ConflictError.
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Protocol

from app.canonical.models import Fact
from app.canonical.engine import apply_candidate
from app.canonical.delta import compute_delta


ENGINE_VERSION = "engine-2026-07-14"
MAPPER_VERSION = "mapper-2026-07-14"
REGISTRY_VERSION = "registry-2026-07-14"


@dataclass
class LedgerContext:
    owner_user_id: str
    source_exchange_id: str
    extractor_version: str
    sensitivity: str = "none"


def _as_date(v):
    if isinstance(v, datetime):        # datetime subclasses date — normalize first
        return v.date()
    if v is None or isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return None


def row_to_fact(row: dict) -> Fact:
    return Fact(
        id=str(row["id"]),
        subject_type=row["subject_type"], subject_id=row["subject_id"],
        predicate=row["predicate"], value_json=row["value_json"],
        normalized_value=row["normalized_value"], status=row.get("status", "active"),
        scope=row.get("scope", "global"), companion_id=row.get("companion_id"),
        valid_from=_as_date(row.get("valid_from")), valid_until=_as_date(row.get("valid_until")),
        observed_at=_as_date(row.get("observed_at")),
        supersedes_fact_id=(str(row["supersedes_fact_id"]) if row.get("supersedes_fact_id") else None),
        confirmation_status=row.get("confirmation_status", "inferred"),
        sensitivity=row.get("sensitivity", "none"), sub_key=row.get("sub_key"),
        cardinality=row.get("cardinality", "single"), version=int(row.get("version", 1)),
    )


def _iso(d):
    if isinstance(d, datetime):
        d = d.date()
    return d.isoformat() if isinstance(d, date) else None


def fact_to_insert(f: Fact, ctx: LedgerContext) -> dict:
    return {
        "id": f.id, "owner_user_id": ctx.owner_user_id,
        "subject_type": f.subject_type, "subject_id": f.subject_id,
        "predicate": f.predicate, "cardinality": f.cardinality,
        "value_json": f.value_json, "normalized_value": f.normalized_value,
        "sub_key": f.sub_key, "status": f.status, "scope": f.scope,
        "companion_id": f.companion_id, "valid_from": _iso(f.valid_from),
        "valid_until": _iso(f.valid_until), "observed_at": _iso(f.observed_at),
        "supersedes_fact_id": f.supersedes_fact_id,
        "confirmation_status": f.confirmation_status, "sensitivity": f.sensitivity,
        "version": f.version, "extractor_version": ctx.extractor_version,
        "mapper_version": MAPPER_VERSION, "engine_version": ENGINE_VERSION,
        "registry_version": REGISTRY_VERSION, "source_exchange_id": ctx.source_exchange_id,
    }


def enrich_event(ev: dict, ctx: LedgerContext) -> dict:
    return {**ev, "owner_user_id": ctx.owner_user_id,
            "source_exchange_id": ctx.source_exchange_id,
            "extractor_version": ev.get("extractor_version", ctx.extractor_version),
            "mapper_version": ev.get("mapper_version", MAPPER_VERSION),
            "registry_version": ev.get("registry_version", REGISTRY_VERSION)}


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
    """Test/local executor over a sync psycopg connection (async via to_thread). Requires an AUTOCOMMIT connection; a single instance is NOT safe for concurrent (asyncio.gather) use — use one executor per coroutine."""

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


def _default_client_factory():
    import httpx
    return httpx.AsyncClient(timeout=15.0)


class PostgrestExecutor:
    """Production executor over Supabase PostgREST (mirrors app.conversation_store)."""

    def __init__(self, base_url: str | None = None, service_key: str | None = None,
                 client_factory=None):
        self._url = (base_url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self._key = service_key or os.environ.get("SUPABASE_SERVICE_KEY", "")
        if not self._url or not self._key:
            raise RuntimeError("PostgrestExecutor: SUPABASE_URL / SUPABASE_SERVICE_KEY not configured")
        self._client_factory = client_factory or _default_client_factory

    def _headers(self, prefer="return=representation"):
        return {"apikey": self._key, "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json", "Prefer": prefer}

    async def fetch_active_facts(self, owner_user_id, subject_type, subject_id,
                                 predicate, scope, companion_id):
        params = {"owner_user_id": f"eq.{owner_user_id}",
                  "subject_type": f"eq.{subject_type}", "subject_id": f"eq.{subject_id}",
                  "predicate": f"eq.{predicate}", "scope": f"eq.{scope}",
                  "status": "eq.active", "select": "*"}
        params["companion_id"] = f"eq.{companion_id}" if companion_id else "is.null"
        async with self._client_factory() as client:
            resp = await client.get(f"{self._url}/rest/v1/canonical_facts",
                                    headers=self._headers(prefer=""), params=params)
        if resp.status_code not in (200, 206):
            self._raise(resp)
        return resp.json()

    async def apply_delta(self, supersedes, updates, inserts, events):
        body = {"p_supersedes": supersedes, "p_updates": updates,
                "p_inserts": inserts, "p_events": events}
        async with self._client_factory() as client:
            resp = await client.post(f"{self._url}/rest/v1/rpc/apply_canonical_delta",
                                     headers=self._headers(), json=body)
        if resp.status_code not in (200, 201, 204):
            self._raise(resp)
        try:
            return resp.json()
        except Exception:
            return {"ok": True}

    def _raise(self, resp):
        code = None
        try:
            code = (resp.json() or {}).get("code")
        except Exception:
            pass
        if code in _CONFLICT_SQLSTATES:
            raise ConflictError(f"ledger conflict {code}")
        raise RuntimeError(f"ledger error HTTP {resp.status_code}: {resp.text[:300]}")


async def apply_candidate_durably(executor, candidate, ctx: LedgerContext,
                                  now: date | None = None, max_retries: int = 3) -> dict:
    """Load the candidate's active slot, run the engine, persist the delta.
    Reloads + recomputes on a ConflictError (CAS 40001 / race 23505)."""
    now = now or datetime.now(timezone.utc).date()
    last_exc: ConflictError | None = None
    for attempt in range(max_retries):
        rows = await executor.fetch_active_facts(
            ctx.owner_user_id, candidate.subject_type, candidate.subject_id,
            candidate.predicate, candidate.scope, candidate.companion_id)
        before = [row_to_fact(r) for r in rows]
        after = apply_candidate(before, candidate, now)
        delta = compute_delta(before, after, engine_version=ENGINE_VERSION,
                              candidate_id=ctx.source_exchange_id)
        if delta.is_empty():
            return {"ok": True, "changed": False}
        # Everything handed to the executor must be JSON-safe (no date objects):
        # fact_to_insert already ISO-encodes insert dates; supersede ops still carry
        # a raw date valid_until from compute_delta, so encode it here — otherwise
        # PostgrestExecutor's httpx json= would crash on a temporal supersession.
        supersedes = [{**op, "valid_until": _iso(op.get("valid_until"))}
                      for op in delta.supersedes]
        inserts = [fact_to_insert(f, ctx) for f in delta.inserts]
        events = [enrich_event(e, ctx) for e in delta.events]
        try:
            res = await executor.apply_delta(supersedes, delta.updates, inserts, events)
            return {"ok": True, "changed": True, "result": res}
        except ConflictError as exc:
            last_exc = exc
            await asyncio.sleep(0.05 * (attempt + 1))
            continue
    raise last_exc or ConflictError("retry exhausted")
