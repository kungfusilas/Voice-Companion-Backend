"""
Per-message relationship scoring and stage name resolution.
Uses Claude Haiku for fast/cheap scoring and stage-up reactions.
"""
import json
import logging
import os
import anthropic

logger = logging.getLogger(__name__)

_async_client: anthropic.AsyncAnthropic | None = None

# (lo, hi, stage_name) inclusive ranges
STAGE_THRESHOLDS: dict[str, list[tuple[int, int, str]]] = {
    "romance": [
        (0, 20, "Strangers"),
        (21, 40, "Noticed"),
        (41, 60, "Flirting"),
        (61, 80, "Crushing"),
        (81, 95, "Dating"),
        (96, 100, "Devoted"),
    ],
    "mentor": [
        (0, 20, "Skeptical"),
        (21, 40, "Open"),
        (41, 60, "Engaged"),
        (61, 80, "Trusted"),
        (81, 100, "Transformed"),
    ],
    "friendship": [
        (0, 20, "Acquaintance"),
        (21, 40, "Comfortable"),
        (41, 60, "Close"),
        (61, 80, "Best Friends"),
        (81, 100, "Ride or Die"),
    ],
    "professional": [
        (0, 20, "Distant"),
        (21, 40, "Cordial"),
        (41, 60, "Reliable"),
        (61, 80, "Valued"),
        (81, 100, "Indispensable"),
    ],
}

_SCORING_CRITERIA: dict[str, str] = {
    "romance": "emotional warmth, vulnerability, playfulness, genuine curiosity about her, consistency",
    "mentor": "curiosity, applying past advice, growth mindset, thoughtful questions, respect",
    "friendship": "reciprocity, humor, support, authenticity, remembering details",
    "professional": "clarity, active listening, follow-through, professionalism, engagement",
}

_SCORING_MODEL = "claude-haiku-4-5-20251001"


def _get_async_client() -> anthropic.AsyncAnthropic:
    global _async_client
    if _async_client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        _async_client = anthropic.AsyncAnthropic(api_key=api_key)
    return _async_client


def get_stage(score: int, rel_type: str) -> tuple[str, int, int]:
    """Return (stage_name, stage_min, stage_max) for the given score."""
    thresholds = STAGE_THRESHOLDS.get(rel_type, STAGE_THRESHOLDS["romance"])
    for lo, hi, name in thresholds:
        if lo <= score <= hi:
            return (name, lo, hi)
    last = thresholds[-1]
    return (last[2], last[0], last[1])


async def score_user_message(
    user_message: str,
    relationship_type: str,
    companion_name: str,
) -> int:
    """
    Score the user's message via Claude Haiku.
    Returns a score_delta between -5 and +5.
    Defaults to 0 on any error.
    Uses AsyncAnthropic so this never blocks the event loop.
    """
    criteria = _SCORING_CRITERIA.get(relationship_type, _SCORING_CRITERIA["romance"])
    prompt = (
        f"Score this message in a {relationship_type} relationship with AI companion {companion_name}.\n"
        f"Criteria: {criteria}\n\n"
        f'Message: "{user_message}"\n\n'
        f"Reply with ONLY JSON: {{\"score_delta\": <integer -5 to +5>}}\n"
        f"Positive = strengthens the relationship. Negative = weakens it."
    )
    try:
        client = _get_async_client()
        response = await client.messages.create(
            model=_SCORING_MODEL,
            max_tokens=24,
            system="You are a relationship quality scorer. Respond with only valid JSON.",
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        data = json.loads(text)
        delta = int(data.get("score_delta", 0))
        return max(-5, min(5, delta))
    except Exception as exc:
        logger.debug("score_user_message failed (defaulting to 0): %s", exc)
        return 0


async def generate_stage_up_reaction(
    companion_name: str,
    companion_system_prompt: str,
    new_stage: str,
    relationship_type: str,
) -> str:
    """
    Generate a short in-character reaction for crossing a stage boundary.
    Returns 1-2 sentences, or empty string on failure.
    Uses AsyncAnthropic so this never blocks the event loop.
    """
    try:
        client = _get_async_client()
        response = await client.messages.create(
            model=_SCORING_MODEL,
            max_tokens=100,
            system=companion_system_prompt,
            messages=[{
                "role": "user",
                "content": (
                    f"(Internal: the user just reached the '{new_stage}' stage of our {relationship_type} connection. "
                    f"Say one short, in-character reaction (1-2 sentences) that subtly reflects this new depth of feeling. "
                    f"Don't name the stage — just express how you feel right now, naturally.)"
                ),
            }],
        )
        return response.content[0].text.strip()
    except Exception as exc:
        logger.debug("generate_stage_up_reaction failed (returning empty): %s", exc)
        return ""
