from fastapi import APIRouter, Depends
from app.auth_middleware import verify_token
from app import weekly_insight

router = APIRouter()


@router.get("/{companion_id}")
async def get_weekly_report(
    companion_id: str,
    user_id: str = Depends(verify_token),
):
    """
    Generate and return a weekly insight report for the authenticated user
    and the given companion.

    GET /api/weekly-report/{companion_id}

    Returns:
      - emotional_themes: list of up to 3 top emotional themes this week
      - growth_moment: a specific moment of progress or self-awareness
      - recurring_pattern: a pattern worth exploring further
      - next_session_question: a suggested open-ended question for next session
      - memory_count: number of memories analysed
      - period_days: always 7
    """
    report = await weekly_insight.generate_weekly_report(user_id, companion_id)
    return report
