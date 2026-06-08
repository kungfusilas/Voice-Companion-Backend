"""
Bond Score analyzer — runs after every N chat messages.

analyze_and_save  — fire-and-forget: sends user messages to Claude Haiku,
                    scores 8 relationship skills, persists to Supabase,
                    and awards hearts for measurable improvement.
"""
import os
import json
import logging
import httpx
import anthropic

logger = logging.getLogger(__name__)

SKILLS = [
    "listening",
    "empathy",
    "curiosity",
    "emotional_regulation",
    "conflict_resolution",
    "follow_through",
    "humor",
    "confidence",
]

# Bond score milestones that award a bonus heart when crossed for the first time
_MILESTONES = {60, 70, 80, 90}

_SYSTEM = """You are a relationship communication analyst. Analyze the user's messages and score their relationship skills.

Return ONLY a valid JSON object with integer scores from 1 to 100 for each skill, nothing else:
{
  "listening": <1-100>,
  "empathy": <1-100>,
  "curiosity": <1-100>,
  "emotional_regulation": <1-100>,
  "conflict_resolution": <1-100>,
  "follow_through": <1-100>,
  "humor": <1-100>,
  "confidence": <1-100>
}

Scoring guide (score the USER's messages only, not the AI companion's):
- listening: Do they acknowledge what was said? Ask follow-up questions? Reference earlier points?
- empathy: Do they show care, validate feelings, show understanding?
- curiosity: Do they ask questions? Show genuine interest?
- emotional_regulation: Do they stay grounded? Handle tension without escalating?
- conflict_resolution: Do they address disagreements constructively? Seek understanding?
- follow_through: Do they reference previous topics? Show continuity and consistency?
- humor: Do they use appropriate wit or lightness? Is it natural?
- confidence: Do they express themselves clearly and directly without hedging?

If a skill genuinely cannot be assessed (e.g., no conflict occurred), score it 50.
Be calibrated — most people score 40-75. Reserve 85+ for genuinely strong examples."""


def _bond_score(scores: dict) -> int:
    """Equal-weight average of all 8 skills."""
    values = [scores.get(s, 50) for s in SKILLS]
    return round(sum(values) / len(values))


async def _call_claude(user_messages: list[str], persona_name: str) -> dict:
    client = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    convo_text = "\n".join(f"User: {m}" for m in user_messages)
    prompt = f"The user was talking with an AI companion named {persona_name}.\n\nUser messages:\n{convo_text}"
    msg = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()
    return json.loads(raw)


def _sb_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _sb_headers(prefer: str = "return=minimal") -> dict:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }


async def _get_previous_scores(user_id: str) -> dict | None:
    """Fetch the most recent bond_scores row for this user (before saving new one)."""
    fields = ",".join(["bond_score"] + SKILLS)
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_sb_url()}/rest/v1/bond_scores",
            headers=_sb_headers(prefer=""),
            params={
                "user_id": f"eq.{user_id}",
                "order": "created_at.desc",
                "limit": "1",
                "select": fields,
            },
        )
    if resp.status_code not in (200, 206):
        return None
    rows = resp.json()
    return rows[0] if rows else None


async def _save(user_id: str, persona_id: str, session_id: str, scores: dict, bs: int) -> None:
    row = {
        "user_id": user_id,
        "persona_id": persona_id,
        "session_id": session_id,
        "bond_score": bs,
        **{s: scores.get(s, 50) for s in SKILLS},
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{_sb_url()}/rest/v1/bond_scores",
            headers=_sb_headers(),
            json=row,
        )
    if resp.status_code not in (200, 201):
        logger.warning("bond_scores insert failed: %s %s", resp.status_code, resp.text)


async def _award_hearts(user_id: str, amount: int, reason: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            f"{_sb_url()}/rest/v1/user_hearts",
            headers=_sb_headers(),
            json={"user_id": user_id, "amount": amount, "reason": reason},
        )


def _hearts_for_improvement(
    new_scores: dict,
    new_bs: int,
    prev: dict | None,
) -> tuple[int, str]:
    """
    Returns (hearts_to_award, reason_string).

    Rules (max 3 hearts per analysis):
    1. Overall Bond Score improved → +1
    2. Any skill improved by ≥5 pts vs previous → +1 (max 1 from this)
    3. Bond Score crossed a milestone (60/70/80/90) → +1
    """
    if prev is None:
        return 0, ""

    prev_bs = int(prev.get("bond_score", new_bs))
    hearts = 0
    reasons: list[str] = []

    # Rule 1: overall improvement
    if new_bs > prev_bs:
        hearts += 1
        reasons.append(f"Bond Score improved {prev_bs}→{new_bs}")

    # Rule 2: any skill improved meaningfully
    for s in SKILLS:
        if int(new_scores.get(s, 50)) - int(prev.get(s, 50)) >= 5:
            hearts += 1
            reasons.append(f"{s} improved")
            break  # only 1 heart for skill improvement per analysis

    # Rule 3: milestone crossed
    for m in _MILESTONES:
        if prev_bs < m <= new_bs:
            hearts += 1
            reasons.append(f"milestone {m}")
            break  # only 1 milestone heart per analysis

    total = min(hearts, 3)
    return total, " · ".join(reasons)


async def analyze_and_save(
    user_id: str,
    persona_id: str,
    session_id: str,
    user_messages: list[str],
    persona_name: str,
) -> None:
    """
    Fire-and-forget: analyze the conversation, persist bond scores, award hearts.
    Errors are silently swallowed — never blocks or slows chat.
    """
    try:
        # Fetch previous scores BEFORE saving so we can compare
        prev = await _get_previous_scores(user_id)

        scores = await _call_claude(user_messages, persona_name)
        clamped = {s: max(1, min(100, int(scores.get(s, 50)))) for s in SKILLS}
        bs = _bond_score(clamped)

        await _save(user_id, persona_id, session_id, clamped, bs)
        logger.info("Bond score saved: user=%s score=%d", user_id[:8], bs)

        hearts, reason = _hearts_for_improvement(clamped, bs, prev)
        if hearts > 0:
            await _award_hearts(user_id, hearts, reason)
            logger.info("Hearts awarded: user=%s hearts=%d reason=%s", user_id[:8], hearts, reason)

    except Exception as exc:
        logger.debug("Bond analyzer error (non-fatal): %s", exc)
