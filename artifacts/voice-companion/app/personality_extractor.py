"""
Personality Mapping — Power tier.

Extracts personality signals from each conversation exchange and
incrementally builds a profile stored in profiles.personality_map (JSONB).

Signal format (v2): each signal is a stamped object {"text": "...", "ts": "<ISO>"}
instead of a plain string. Legacy plain-string signals are normalised on read and
preserved with ts=None until they are reinforced or pruned.

Aging rules:
  - Signals with a known ts older than _SIGNAL_MAX_AGE_DAYS are pruned before
    each extraction call (pure Python, no LLM needed).
  - Signals with ts=None (legacy / backfilled) are never pruned automatically —
    they survive until contradicted by Claude or rotated out by the 6-signal cap.

Supabase: run once in SQL editor if not already done:
    alter table profiles
      add column if not exists personality_map jsonb default '{}'::jsonb;
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import httpx

from app import claude

logger = logging.getLogger(__name__)

_HAIKU = "claude-haiku-4-5-20251001"
_SIGNAL_MAX_AGE_DAYS = 270  # ~9 months — timestamped signals older than this are pruned

_EMPTY_MAP = {
    "communication_style": {"label": None, "signals": []},
    "attachment_style":    {"label": None, "signals": []},
    "leadership_style":    {"label": None, "signals": []},
    "emotional_triggers":  {"positive": [], "negative": []},
    "conversation_count":  0,
    "last_updated":        None,
}


# ── Supabase helpers ──────────────────────────────────────────────────────────

def _supa_headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


async def _fetch_current_map(user_id: str) -> dict:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not url:
        return dict(_EMPTY_MAP)
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/profiles",
                headers=_supa_headers(),
                params={"id": f"eq.{user_id}", "select": "personality_map", "limit": "1"},
            )
        if resp.status_code == 200 and resp.json():
            raw = resp.json()[0].get("personality_map") or {}
            merged = dict(_EMPTY_MAP)
            merged.update(raw)
            return merged
    except Exception as e:
        logger.debug("Fetch personality_map failed: %s", e)
    return dict(_EMPTY_MAP)


async def _save_map(user_id: str, personality_map: dict) -> None:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            await client.patch(
                f"{url}/rest/v1/profiles",
                headers=_supa_headers(),
                params={"id": f"eq.{user_id}"},
                json={"personality_map": personality_map},
            )
    except Exception as e:
        logger.debug("Save personality_map failed: %s", e)


# ── Signal format helpers ─────────────────────────────────────────────────────

def _normalize_signal(s) -> dict:
    """Coerce a legacy plain-string or existing dict into stamped format."""
    if isinstance(s, dict):
        return {"text": str(s.get("text", "")), "ts": s.get("ts")}
    return {"text": str(s), "ts": None}


def _prune_signals(signals: list, now: datetime) -> list[dict]:
    """
    Normalise all signals then drop any whose ts is older than _SIGNAL_MAX_AGE_DAYS.
    Signals with ts=None (legacy / unknown age) are always preserved.
    """
    kept: list[dict] = []
    for raw in signals:
        s = _normalize_signal(raw)
        if not s["ts"]:
            kept.append(s)
            continue
        try:
            ts = datetime.fromisoformat(s["ts"])
            if (now - ts).days <= _SIGNAL_MAX_AGE_DAYS:
                kept.append(s)
        except Exception:
            kept.append(s)
    return kept


def _age_label(ts_str: str | None, now: datetime) -> str:
    """Return a human-readable age string for a signal timestamp."""
    if not ts_str:
        return "unknown age"
    try:
        ts = datetime.fromisoformat(ts_str)
        days = (now - ts).days
        if days == 0:
            return "today"
        if days == 1:
            return "1d ago"
        if days < 30:
            return f"{days}d ago"
        months = days // 30
        if months < 12:
            return f"{months}mo ago"
        return f"{months // 12}y ago"
    except Exception:
        return "unknown age"


def _signals_for_prompt(signals: list[dict], now: datetime) -> list[str]:
    """Render signals as 'text (age)' strings for the Claude prompt."""
    return [f"{s['text']} ({_age_label(s['ts'], now)})" for s in signals if s.get("text")]


def _reconcile_timestamps(
    returned_texts: list[str],
    old_signals: list[dict],
    now: datetime,
    cap: int = 6,
) -> list[dict]:
    """
    Merge Claude's returned plain-text signal list back into stamped dicts:
    - Exact text match with an old signal → keep the old timestamp (signal was reinforced).
    - New text → stamp with now (signal is fresh).
    Capped at `cap` items.
    """
    old_map = {s["text"]: s["ts"] for s in old_signals}
    now_str = now.isoformat()
    result: list[dict] = []
    for text in returned_texts:
        text = text.strip()
        if not text or len(result) >= cap:
            continue
        ts = old_map.get(text, now_str)
        result.append({"text": text, "ts": ts})
    return result


def _extract_texts(signals: list) -> list[str]:
    """Extract plain text strings from a list of signal dicts or legacy plain strings."""
    result: list[str] = []
    for s in signals:
        text = s.get("text", "") if isinstance(s, dict) else str(s)
        if text:
            result.append(text)
    return result


# ── Prompt formatting ─────────────────────────────────────────────────────────

def format_personality_for_prompt(pmap: dict) -> str:
    """
    Convert a personality_map dict into a compact plain-language block for
    injection into a Claude system prompt. Handles both legacy (plain-string)
    and new (stamped dict) signal formats.
    Only dimensions that have a label set are included.
    """
    if not pmap or not pmap.get("conversation_count"):
        return ""

    lines: list[str] = []

    cs = pmap.get("communication_style") or {}
    if cs.get("label"):
        sigs = _extract_texts(cs.get("signals") or [])
        detail = f" ({'; '.join(sigs[:3])})" if sigs else ""
        lines.append(f"- Communication style: {cs['label']}{detail}")

    att = pmap.get("attachment_style") or {}
    if att.get("label"):
        sigs = _extract_texts(att.get("signals") or [])
        detail = f" ({'; '.join(sigs[:3])})" if sigs else ""
        lines.append(f"- Attachment style: {att['label']}{detail}")

    lead = pmap.get("leadership_style") or {}
    if lead.get("label"):
        sigs = _extract_texts(lead.get("signals") or [])
        detail = f" ({'; '.join(sigs[:3])})" if sigs else ""
        lines.append(f"- Decisiveness/leadership: {lead['label']}{detail}")

    trig = pmap.get("emotional_triggers") or {}
    pos = _extract_texts(trig.get("positive") or [])
    neg = _extract_texts(trig.get("negative") or [])
    if pos:
        lines.append(f"- Energised by: {', '.join(pos[:4])}")
    if neg:
        lines.append(f"- Handle gently (tends to drain them): {', '.join(neg[:4])}")

    if not lines:
        return ""

    return (
        "\n\n## User Personality Profile\n"
        "Observed patterns built from your conversations so far — use these to adapt your tone:\n"
        + "\n".join(lines)
        + "\n"
        "Match your style to theirs and be especially gentle when emotionally draining topics arise."
    )


# ── Big Five drift → personality map revision ─────────────────────────────────

_TRAIT_TO_DIMENSIONS: dict[str, list[str]] = {
    "extraversion":      ["communication_style"],
    "openness":          ["communication_style", "leadership_style"],
    "conscientiousness": ["leadership_style"],
    "agreeableness":     ["attachment_style"],
    "neuroticism":       ["emotional_triggers"],
}

_DRIFT_REVISION_SYSTEM = (
    "You are a personality psychologist. "
    "You will receive a user's qualitative personality profile and a set of observed "
    "Big Five trait drifts measured from their recent conversations. "
    "Propose targeted, minimal revisions to the profile dimensions the drifted traits directly influence. "
    "Preserve signals that remain plausible; replace or remove those the drift contradicts. "
    "Do not revise dimensions unaffected by the drifted traits. "
    "Return ONLY valid JSON with exactly the same four top-level keys as the input profile "
    "(communication_style, attachment_style, leadership_style, emotional_triggers). "
    "Signals must be plain text strings — no timestamps, no ages. "
    "Return ONLY the JSON — no markdown, no explanation."
)


async def apply_drift_revision(user_id: str, drift: list[dict]) -> None:
    """
    Given Big Five drift entries from personality_tracker.get_personality_drift(),
    fetch the current personality_map, call Claude Haiku for targeted revisions to
    the affected dimensions, reconcile timestamps, and patch the profile.

    Fire-and-forget — all exceptions are suppressed.
    Reuses _fetch_current_map / _save_map so no Supabase calls are duplicated.
    """
    if not drift:
        return
    try:
        now = datetime.now(timezone.utc)
        current = await _fetch_current_map(user_id)

        # Which dimensions does this drift touch?
        affected_dims: set[str] = set()
        for entry in drift:
            for dim in _TRAIT_TO_DIMENSIONS.get(entry.get("trait", ""), []):
                affected_dims.add(dim)
        if not affected_dims:
            return

        # Human-readable drift summary
        drift_lines = [
            f"- {e['trait']}: {e['direction']} by {abs(e.get('delta', 0)):.1f} pts "
            f"({e.get('from', '?')} → {e.get('to', '?')})"
            for e in drift
        ]
        drift_summary = "\n".join(drift_lines)

        # Compact profile (plain text only for Claude's context)
        def _texts(lst: list) -> list[str]:
            return _extract_texts(lst or [])

        prompt_profile = {
            "communication_style": {
                "label": current["communication_style"].get("label"),
                "signals": _texts(current["communication_style"].get("signals", [])),
            },
            "attachment_style": {
                "label": current["attachment_style"].get("label"),
                "signals": _texts(current["attachment_style"].get("signals", [])),
            },
            "leadership_style": {
                "label": current["leadership_style"].get("label"),
                "signals": _texts(current["leadership_style"].get("signals", [])),
            },
            "emotional_triggers": {
                "positive": _texts(current["emotional_triggers"].get("positive", [])),
                "negative": _texts(current["emotional_triggers"].get("negative", [])),
            },
        }

        user_prompt = (
            f"Current personality profile:\n{json.dumps(prompt_profile, indent=2)}\n\n"
            f"Big Five drift observed since last measurement:\n{drift_summary}\n\n"
            f"Dimensions to revise (only these): {', '.join(sorted(affected_dims))}\n\n"
            "For each affected dimension:\n"
            "- Revise the label if drift evidence no longer supports it.\n"
            "- Replace signals contradicted by the drift; keep those that remain plausible.\n"
            "- Add at most 1-2 new signals per dimension where the drift suggests new patterns.\n"
            "For unaffected dimensions, return them exactly as provided.\n"
            "Return all four top-level keys in the JSON."
        )

        raw = await claude.send_message(
            system_prompt=_DRIFT_REVISION_SYSTEM,
            history=[],
            user_message=user_prompt,
            model=_HAIKU,
            max_tokens=600,
        )
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()
        revised = json.loads(cleaned)

        # Reconcile timestamps for affected dimensions
        def _old_sigs(dim_key: str) -> list[dict]:
            raw_list = current[dim_key].get("signals", []) if dim_key != "emotional_triggers" else []
            return [_normalize_signal(s) for s in raw_list]

        def _merge_dim(dim_key: str) -> dict:
            old_dim = current[dim_key]
            new_dim = revised.get(dim_key, old_dim)
            if dim_key not in affected_dims:
                return old_dim  # untouched — preserve existing stamped signals
            return {
                "label": new_dim.get("label") or old_dim.get("label"),
                "signals": _reconcile_timestamps(
                    new_dim.get("signals") or [], _old_sigs(dim_key), now
                ),
            }

        def _merge_triggers() -> dict:
            old_t = current["emotional_triggers"]
            new_t = revised.get("emotional_triggers", old_t)
            if "emotional_triggers" not in affected_dims:
                return old_t
            old_pos = [_normalize_signal(s) for s in (old_t.get("positive") or [])]
            old_neg = [_normalize_signal(s) for s in (old_t.get("negative") or [])]
            return {
                "positive": _reconcile_timestamps(
                    new_t.get("positive") or [], old_pos, now, cap=5
                ),
                "negative": _reconcile_timestamps(
                    new_t.get("negative") or [], old_neg, now, cap=5
                ),
            }

        updated = {
            "communication_style": _merge_dim("communication_style"),
            "attachment_style":    _merge_dim("attachment_style"),
            "leadership_style":    _merge_dim("leadership_style"),
            "emotional_triggers":  _merge_triggers(),
            "conversation_count":  current.get("conversation_count", 0),
            "last_updated":        now.isoformat(),
        }

        await _save_map(user_id, updated)
        logger.debug("apply_drift_revision: patched personality_map for user=%s dims=%s", user_id, affected_dims)

    except Exception as exc:
        logger.debug("apply_drift_revision failed for user=%s: %s", user_id, exc)


# ── Main extraction entry point ───────────────────────────────────────────────

async def extract_and_update(
    user_id: str,
    user_message: str,
    companion_reply: str,
) -> None:
    """
    Fire-and-forget: extract signals from one conversation exchange and merge
    them into the personality profile using Claude Haiku.

    Signal lifecycle:
    1. Existing signals are normalised to stamped dicts and aged-out signals pruned.
    2. Remaining signals are shown to Claude with human-readable ages.
    3. Claude classifies each new observation as reinforcing / contradicting-supersedes /
       unrelated-new and returns a plain-text signal list per dimension.
    4. Python reconciles timestamps: unchanged text → keep old ts; new text → stamp now.
    """
    try:
        now = datetime.now(timezone.utc)
        current = await _fetch_current_map(user_id)
        count = int(current.get("conversation_count") or 0)

        # Normalise + prune aged signals for each dimension
        cs_sigs   = _prune_signals(current["communication_style"].get("signals", []), now)
        att_sigs  = _prune_signals(current["attachment_style"].get("signals", []), now)
        lead_sigs = _prune_signals(current["leadership_style"].get("signals", []), now)
        pos_sigs  = _prune_signals(current["emotional_triggers"].get("positive", []), now)
        neg_sigs  = _prune_signals(current["emotional_triggers"].get("negative", []), now)

        # Build prompt representation with ages shown
        compact = {
            "communication_style": {
                "label": current["communication_style"].get("label"),
                "signals": _signals_for_prompt(cs_sigs, now),
            },
            "attachment_style": {
                "label": current["attachment_style"].get("label"),
                "signals": _signals_for_prompt(att_sigs, now),
            },
            "leadership_style": {
                "label": current["leadership_style"].get("label"),
                "signals": _signals_for_prompt(lead_sigs, now),
            },
            "emotional_triggers": {
                "positive": _signals_for_prompt(pos_sigs, now),
                "negative": _signals_for_prompt(neg_sigs, now),
            },
        }

        prompt = f"""You are updating a user's personality profile from a single conversation exchange.

New exchange:
User: "{user_message}"
Companion: "{companion_reply}"

Current profile (signals shown with how long ago they were observed):
{json.dumps(compact, indent=2)}

For each dimension, evaluate the new exchange against the existing signals:
- REINFORCE: if the exchange confirms an existing signal, include that signal text unchanged.
- CONTRADICT/SUPERSEDE: if the exchange clearly contradicts an existing signal, drop the old signal and add a revised one reflecting current reality. Do NOT keep contradicted signals alongside contradicting evidence.
- NEW: if you see a genuinely new pattern not covered by existing signals, add it (at most 1-2 per dimension).
- DROP: you may silently omit signals that seem stale or no longer representative — use sparingly.

Also revise the label if the accumulated signals no longer support the current description.
If the exchange shows no clear evidence for a field, return it unchanged.

Constraints:
- Max 6 signals per dimension; max 5 each for positive/negative triggers.
- Signal texts must be plain strings — no ages, no timestamps, no parenthetical dates.

Return ONLY valid JSON with exactly these four top-level keys:
{{
  "communication_style": {{"label": "3-6 word description or null", "signals": ["plain text", ...]}},
  "attachment_style":    {{"label": "3-6 word description or null", "signals": ["plain text", ...]}},
  "leadership_style":    {{"label": "3-6 word description or null", "signals": ["plain text", ...]}},
  "emotional_triggers":  {{"positive": ["energizer", ...], "negative": ["drainer", ...]}}
}}
Return ONLY the JSON."""

        raw = await claude.send_message(
            system_prompt="You are a personality analyst. Return ONLY valid JSON — no markdown, no explanation.",
            history=[],
            user_message=prompt,
            model=_HAIKU,
            max_tokens=600,
        )
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()
        updated_raw = json.loads(cleaned)

        # Reconcile timestamps: keep old ts for unchanged texts, stamp new ones with now
        final: dict = {
            "communication_style": {
                "label": updated_raw["communication_style"].get("label"),
                "signals": _reconcile_timestamps(
                    updated_raw["communication_style"].get("signals", []), cs_sigs, now
                ),
            },
            "attachment_style": {
                "label": updated_raw["attachment_style"].get("label"),
                "signals": _reconcile_timestamps(
                    updated_raw["attachment_style"].get("signals", []), att_sigs, now
                ),
            },
            "leadership_style": {
                "label": updated_raw["leadership_style"].get("label"),
                "signals": _reconcile_timestamps(
                    updated_raw["leadership_style"].get("signals", []), lead_sigs, now
                ),
            },
            "emotional_triggers": {
                "positive": _reconcile_timestamps(
                    updated_raw["emotional_triggers"].get("positive", []), pos_sigs, now, cap=5
                ),
                "negative": _reconcile_timestamps(
                    updated_raw["emotional_triggers"].get("negative", []), neg_sigs, now, cap=5
                ),
            },
            "conversation_count": count + 1,
            "last_updated": now.isoformat(),
        }

        await _save_map(user_id, final)

    except Exception as e:
        logger.debug("Personality extraction skipped: %s", e)
