"""
Question bank for daily life/legacy questions, check-in questions, and weekly themed sets.
"""
import hashlib
from datetime import date, timedelta

# ── 50 Legacy / Life Questions ────────────────────────────────────────────────

LEGACY_QUESTIONS: list[str] = [
    "What's a moment from your past that still makes you smile when you think about it?",
    "Who taught you the most about love — and what did they teach you?",
    "What's something you believed at 20 that you've completely changed your mind about?",
    "What does home mean to you — and where or when have you felt most at home?",
    "What's the hardest decision you've ever had to make? Do you still stand by it?",
    "Is there a relationship in your life you wish you had handled differently?",
    "What's something you've never told anyone that you've always wanted to say?",
    "What period of your life felt most alive — and why?",
    "Who is the most underrated person in your life — someone who shaped you but rarely gets credit?",
    "What does it mean to you to truly forgive someone?",
    "What's a fear you've been carrying for years that you haven't fully faced?",
    "What would your younger self think of who you've become?",
    "What's a value you were raised with that you've kept — and one you've quietly let go of?",
    "What does success feel like on the inside — not what it looks like from outside?",
    "Is there something you've been waiting for permission to do or be?",
    "What's the most important lesson a failure taught you?",
    "Who in your life do you feel truly seen by — and what makes that feel different?",
    "What's a piece of advice you've given that you struggle to take yourself?",
    "If you could have one conversation with anyone who's passed away, who would it be and why?",
    "What does grief look like for you — and how have you moved through it?",
    "What's something you're proud of that no one knows about?",
    "What kind of old person do you want to become?",
    "Is there a version of your life you almost lived — a path you didn't take?",
    "What has loving someone taught you about yourself?",
    "What's the most generous thing anyone has ever done for you?",
    "What tradition or ritual do you hold onto — and what does it mean to you?",
    "What does courage look like in your everyday life?",
    "Is there someone from your past you think about but haven't reached out to?",
    "What's a story your family tells about you that reveals something true?",
    "What moment made you realize you were no longer a kid?",
    "What do you know now about relationships that you wish you'd known at the start?",
    "What's a chapter of your life that felt like a survival — one you got through?",
    "What's something you've built — a relationship, a habit, a skill — that took years?",
    "What does loyalty mean to you, and have you ever felt it tested?",
    "What's a place that holds a significant memory for you?",
    "What's the most honest thing someone has ever said to you?",
    "What do you think people misunderstand most about you?",
    "What have you stopped apologizing for — and why?",
    "What's a promise you made to yourself that you've kept?",
    "What does being truly known by someone feel like — and do you have that?",
    "What's a moment you'd freeze in time if you could?",
    "How has your relationship with your parents shaped who you are now?",
    "What's something you're still learning about yourself?",
    "What does integrity cost you in your daily life?",
    "What's a boundary you set that changed everything?",
    "What has disappointment taught you?",
    "What's a dream that hasn't died, no matter how long it's been sitting?",
    "How do you want the people you love to remember you?",
    "What's one thing you want to do before you die that you haven't done yet?",
    "What would you tell someone going through the hardest thing you've ever survived?",
]

# ── 10 Daily Check-in Questions ───────────────────────────────────────────────

CHECKIN_QUESTIONS: list[str] = [
    "How are you actually doing today — not just the surface answer?",
    "What's one thing on your mind that you haven't had a chance to say out loud?",
    "What's something you're looking forward to, even something small?",
    "Who have you been thinking about lately?",
    "What's draining your energy right now — and what's refilling it?",
    "Is there anything you need to get off your chest today?",
    "What was the most meaningful moment of your past few days?",
    "How are the important relationships in your life feeling right now?",
    "What's something you're working on about yourself this week?",
    "What would make today feel like a win — even a small one?",
]

# ── 4 Weekly Themed Question Sets (Mon–Sun) ───────────────────────────────────

WEEKLY_THEMES: list[dict] = [
    {
        "theme": "Origins & Identity",
        "questions": [
            "Where do you come from — and how much of that still lives in you?",
            "What's one thing about your upbringing you've carried forward, and one you've consciously left behind?",
            "Who were you before the world started telling you who to be?",
            "What's something from your culture or family that you're proud of?",
            "If you had to describe your identity in three words, what would they be?",
        ],
    },
    {
        "theme": "Love & Connection",
        "questions": [
            "What's the difference between the love you give and the love you long to receive?",
            "What does being close to someone require of you?",
            "Is there a relationship you've been taking for granted?",
            "What's the most vulnerable thing you've shared with another person?",
            "What do the best moments with the people you love have in common?",
        ],
    },
    {
        "theme": "Growth & Becoming",
        "questions": [
            "What's a version of yourself you've outgrown — and what replaced it?",
            "What are you in the middle of becoming right now?",
            "What's the hardest thing you're currently growing through?",
            "What habit or belief has changed your life the most in the past few years?",
            "What does your future self need from you right now?",
        ],
    },
    {
        "theme": "Legacy & Meaning",
        "questions": [
            "What do you want to leave behind — not in things, but in people?",
            "What's something you've done that has mattered beyond yourself?",
            "What kind of mark do you hope to make on the people closest to you?",
            "If your life were a book, what would this chapter be called?",
            "What story from your life do you most want to be remembered?",
        ],
    },
]


# ── API functions ─────────────────────────────────────────────────────────────

def _user_seed(user_id: str) -> int:
    """Stable integer seed from user_id for per-user question variety."""
    return int(hashlib.sha256(user_id.encode()).hexdigest(), 16) % 1_000_003


def get_daily_question(user_id: str, target_date: date | None = None) -> dict:
    """
    Return today's daily question for a user.

    Uses a deterministic mix of day-of-year and a user-specific seed so
    different users get different questions on the same day, and the same
    user gets a predictable (idempotent) question for a given date.

    Returns:
        {"question": str, "type": "legacy" | "checkin", "date": "YYYY-MM-DD"}
    """
    d = target_date or date.today()
    day_number = (d - date(d.year, 1, 1)).days  # 0-based day of year
    seed = _user_seed(user_id)

    # 5 days legacy, 1 day checkin in every 6 (ratio weighted toward depth)
    cycle_pos = (day_number + seed) % 6
    if cycle_pos == 0:
        idx = (day_number + seed) % len(CHECKIN_QUESTIONS)
        question = CHECKIN_QUESTIONS[idx]
        q_type = "checkin"
    else:
        idx = (day_number + seed) % len(LEGACY_QUESTIONS)
        question = LEGACY_QUESTIONS[idx]
        q_type = "legacy"

    return {
        "question": question,
        "type": q_type,
        "date": d.isoformat(),
    }


def get_weekly_question_set(week_offset: int = 0) -> dict:
    """
    Return the question set for the current (or offset) week.

    Args:
        week_offset: 0 = this week, 1 = next week, -1 = last week.

    Returns:
        {"theme": str, "questions": list[str], "week_start": "YYYY-MM-DD"}
    """
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    target_monday = monday + timedelta(weeks=week_offset)

    # Cycle through the 4 themes by ISO week number
    iso_week = target_monday.isocalendar()[1]
    theme_idx = (iso_week - 1) % len(WEEKLY_THEMES)
    theme = WEEKLY_THEMES[theme_idx]

    return {
        "theme": theme["theme"],
        "questions": theme["questions"],
        "week_start": target_monday.isoformat(),
    }
