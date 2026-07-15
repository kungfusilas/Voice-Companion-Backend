"""Shadow ledger runner — maps a turn's extracted facts into the canonical ledger.

Invoked from the post-chat background task AFTER the legacy write. Invisible and
fail-open: it never raises into the caller, and a fact without a valid `canonical`
object (the case in production until the nested-prompt ships) is a no-op.
"""
from __future__ import annotations

import logging
from datetime import date

from app.canonical.mapper import map_canonical
from app.canonical.repository import (LedgerContext, apply_candidate_durably,
                                      ENGINE_VERSION)
from app import memory_settings

logger = logging.getLogger(__name__)

EXTRACTOR_VERSION = "core-facts-2026-07-14"


async def run(outcome, *, owner_user_id: str, exchange_id: str, executor,
              settings: dict, now: date | None = None) -> dict:
    summary = {"considered": 0, "applied": 0, "unmapped": 0, "gated": 0, "errors": 0}
    facts = getattr(outcome, "facts", None) or []
    for f in facts:
        summary["considered"] += 1
        try:
            canonical = f.get("canonical") if isinstance(f, dict) else None
            sensitivity = (f.get("sensitivity") if isinstance(f, dict) else None) or "none"
            candidate = map_canonical(canonical, sensitivity=sensitivity, now=now)
            if candidate is None:
                summary["unmapped"] += 1
                continue
            if not memory_settings.should_collect(settings, candidate.sensitivity):
                summary["gated"] += 1
                continue
            ctx = LedgerContext(owner_user_id=owner_user_id, source_exchange_id=exchange_id,
                                extractor_version=EXTRACTOR_VERSION,
                                sensitivity=candidate.sensitivity)
            await apply_candidate_durably(executor, candidate, ctx, now=now)
            summary["applied"] += 1
        except Exception as exc:  # fail-open: never propagate into the caller
            summary["errors"] += 1
            logger.warning("[shadow_ledger] apply failed exchange=%s: %r", exchange_id, exc)
    return summary
