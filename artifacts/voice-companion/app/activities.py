"""
Shared activities system — core generation logic.
Imported by both app/routers/activities.py and app/proactive.py.
"""
import json
import os
import anthropic
from app.companions import COMPANION_MAP, build_system_prompt

_MODEL = "claude-haiku-4-5-20251001"
_async_client: anthropic.AsyncAnthropic | None = None

_MAX_TOOL_ITERATIONS = 5

_INTRO_STYLE: dict[str, str] = {
    "companion-aeva": (
        "Aeva is confident but mid-sentence she searches for the right English word. She "
        "describes around the missing word and the user helps her find it. Example: "
        "\"Okay okay, I have a game. You have to guess the word I am thinking of. I will give "
        "you... how do you say... the little hints? Clues! Yes, clues.\""
    ),
    "companion-ben": (
        "Ben is calm, confident, a little mysterious — he suggests the activity like it's "
        "something he's been quietly looking forward to."
    ),
}

_WORD_GAME_PROMPT = """\
Generate a word-guessing game in the companion's voice. Return ONLY valid JSON — no markdown, no commentary:
{{
  "companion_intro": "<companion introduces the game; style: {style}>",
  "clue1": "<vague first clue>",
  "clue2": "<more specific second clue>",
  "clue3": "<quite specific third clue — still a challenge>",
  "answer": "<the mystery word, lowercase single word>"
}}
Pick a word that is interesting but not obscure — everyday object, emotion, or concept. \
Clues should be fun and in-character. Do not use the word anywhere in the clues."""

_TRIVIA_PROMPT = """\
Generate a trivia question. Return ONLY valid JSON — no markdown, no commentary:
{{
  "companion_intro": "<companion introduces trivia; style: {style}>",
  "question": "<trivia question>",
  "options": {{"A": "<option>", "B": "<option>", "C": "<option>", "D": "<option>"}},
  "correct": "<A, B, C, or D>",
  "fun_fact": "<brief fun fact related to the answer, 1 sentence>"
}}
Category: history, science, pop culture, or nature. Accessible but genuinely interesting."""

_WYR_PROMPT = """\
Generate a Would You Rather question. Return ONLY valid JSON — no markdown, no commentary:
{{
  "companion_intro": "<companion introduces the dilemma; style: {style}>",
  "optionA": "<option A, no 'would you rather' prefix>",
  "optionB": "<option B>",
  "companion_choice": "<A or B>",
  "companion_reason": "<1-2 sentences: companion explains their pick, fully in character>"
}}
Make it fun, personal enough to spark conversation — not dark or gross. \
companion_choice and companion_reason must reflect the companion's personality."""

_PROMPT_TEMPLATES = {
    "word_game": _WORD_GAME_PROMPT,
    "trivia": _TRIVIA_PROMPT,
    "would_you_rather": _WYR_PROMPT,
}


def _get_async_client() -> anthropic.AsyncAnthropic:
    global _async_client
    if _async_client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        _async_client = anthropic.AsyncAnthropic(api_key=api_key)
    return _async_client


def _strip_fences(text: str) -> str:
    """Remove markdown code fences if Claude wrapped the JSON."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


async def generate_activity(companion_id: str, activity_type: str) -> dict:
    """
    Generate activity content for the given companion and activity type.
    Returns a dict with 'type', 'companion_id', 'companion_name', and
    activity-specific fields.
    Raises ValueError for unknown types/companions, RuntimeError on generation failure.
    """
    companion = COMPANION_MAP.get(companion_id)
    if not companion:
        raise ValueError(f"Unknown companion: {companion_id}")

    template = _PROMPT_TEMPLATES.get(activity_type)
    if not template:
        raise ValueError(f"Unknown activity_type: {activity_type}")

    style = _INTRO_STYLE.get(companion_id, _INTRO_STYLE["companion-aeva"])
    user_prompt = template.format(style=style)
    system_prompt = (
        build_system_prompt(companion)
        + "\n\nRespond ONLY with valid JSON, no markdown fences, no extra commentary."
    )

    client = _get_async_client()
    response = await client.messages.create(
        model=_MODEL,
        max_tokens=600,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = response.content[0].text
    text = _strip_fences(raw)
    data = json.loads(text)
    data["type"] = activity_type
    data["companion_id"] = companion_id
    data["companion_name"] = companion.name
    return data
