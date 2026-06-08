"""
Bond Score analyzer — runs after every N chat messages.

analyze_and_save  — fire-and-forget: sends user messages to Claude Haiku,
                    scores 8 relationship skills, persists to Supabase.
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
        model="claude-haiku-4-5",
        max_tokens=256,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()
    return json.loads(raw)


def _sb_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _sb_headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


async def _save(user_id: str, persona_id: str, session_id: str, scores: dict, bond_score: int) -> None:
    row = {
        "user_id": user_id,
        "persona_id": persona_id,
        "session_id": session_id,
        "bond_score": bond_score,
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


async def analyze_and_save(
    user_id: str,
    persona_id: str,
    session_id: str,
    user_messages: list[str],
    persona_name: str,
) -> None:
    """
    Fire-and-forget: analyze the conversation and persist bond scores.
    Errors are silently swallowed — never blocks or slows chat.
    """
    try:
        scores = await _call_claude(user_messages, persona_name)
        # Clamp all scores to 1-100
        clamped = {s: max(1, min(100, int(scores.get(s, 50)))) for s in SKILLS}
        bs = _bond_score(clamped)
        await _save(user_id, persona_id, session_id, clamped, bs)
        logger.info("Bond score saved: user=%s score=%d", user_id[:8], bs)
    except Exception as exc:
        logger.debug("Bond analyzer error (non-fatal): %s", exc)
