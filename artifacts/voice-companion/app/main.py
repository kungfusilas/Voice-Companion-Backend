import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.routers import chat, personas, sessions, tts, stt, memories
from app.routers import goals as goals_router
from app.routers import bond_score as bond_score_router
from app.routers import hearts as hearts_router
from app.routers import future_memory as future_memory_router
from app.routers import auth as auth_router
from app.routers import proactive as proactive_router
from app.routers import selfie as selfie_router
from app.routers import relationship as relationship_router
from app.routers import activities as activities_router
from app.routers import romantic as romantic_router
from app.routers import daily_checkin as daily_checkin_router
from app.routers import waitlist as waitlist_router
from app.routers import payments as payments_router
from app.routers import roleplay as roleplay_router
from app.routers import personality as personality_router
from app.routers import analysis as analysis_router
from app.routers import onboarding as onboarding_router
from app.routers import reports as reports_router
from app.routers import usage as usage_router
from app.routers import legacy_chapters as legacy_chapters_router
from app import store
from app.companions import COMPANIONS, build_system_prompt
from app import proactive, daily_checkin

load_dotenv()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    for companion in COMPANIONS:
        companion.system_prompt_override = build_system_prompt(companion)
        store.create_persona(companion)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        proactive.check_and_send_proactive_messages,
        "interval",
        hours=1,
        id="proactive_checkin",
        replace_existing=True,
    )
    scheduler.add_job(
        proactive.check_and_send_daily_activity,
        "interval",
        hours=1,
        id="daily_activity",
        replace_existing=True,
    )
    scheduler.add_job(
        daily_checkin.run_daily_checkins,
        "cron",
        hour=9,
        minute=0,
        id="daily_morning_checkin",
        replace_existing=True,
    )
    scheduler.add_job(
        reports_router.run_weekly_reports_for_all_users,
        "cron",
        day_of_week="mon",
        hour=7,
        minute=0,
        id="weekly_insight_reports",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Schedulers started: proactive check-in + daily activity + daily morning check-in")

    yield

    scheduler.shutdown(wait=False)


app = FastAPI(
    title="AI Voice Companion API",
    version="1.0.0",
    root_path="/companion/",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class _StripCompanionPrefix:
    """Pure ASGI middleware: strip the /companion path prefix.

    Replit's production reverse proxy does NOT rewrite paths before forwarding
    to the service (unlike the Vite dev proxy which strips /companion before
    reaching uvicorn on port 8001). Adding this middleware makes routing work
    identically in dev and production — FastAPI always sees /api/* paths.
    In dev the Vite proxy already strips the prefix, so incoming paths never
    start with /companion and this middleware is a no-op.
    """

    def __init__(self, app_) -> None:
        self.app = app_

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") in ("http", "websocket"):
            path: str = scope.get("path", "")
            if path.startswith("/companion"):
                stripped = path[len("/companion"):] or "/"
                scope = {**scope, "path": stripped, "raw_path": stripped.encode("latin-1")}
        await self.app(scope, receive, send)


app.add_middleware(_StripCompanionPrefix)

app.include_router(chat.router,               prefix="/api/chat",               tags=["chat"])
app.include_router(personas.router,           prefix="/api/personas",           tags=["personas"])
app.include_router(sessions.router,           prefix="/api/sessions",           tags=["sessions"])
app.include_router(tts.router,                prefix="/api/tts",                tags=["tts"])
app.include_router(stt.router,                prefix="/api/stt",                tags=["stt"])
app.include_router(memories.router,           prefix="/api/memories",           tags=["memories"])
app.include_router(proactive_router.router,   prefix="/api/proactive-messages", tags=["proactive"])
app.include_router(selfie_router.router,      prefix="/api/selfie",             tags=["selfie"])
app.include_router(relationship_router.router,prefix="/api/relationship",       tags=["relationship"])
app.include_router(activities_router.router,  prefix="/api/activity",           tags=["activities"])
app.include_router(auth_router.router,          prefix="/api/auth",              tags=["auth"])
app.include_router(romantic_router.router,      prefix="/api/romantic-mode",      tags=["romantic"])
app.include_router(daily_checkin_router.router, prefix="/api/daily-checkin",      tags=["daily-checkin"])
app.include_router(waitlist_router.router,      prefix="/api/waitlist",           tags=["waitlist"])
app.include_router(payments_router.router,     prefix="/api",                    tags=["payments"])
app.include_router(goals_router.router,        prefix="/api/goals",              tags=["goals"])
app.include_router(bond_score_router.router,   prefix="/api/bond-score",         tags=["bond-score"])
app.include_router(hearts_router.router,       prefix="/api/hearts",             tags=["hearts"])
app.include_router(future_memory_router.router, prefix="/api/future-memory",     tags=["future-memory"])
app.include_router(roleplay_router.router,      prefix="/api/roleplay",           tags=["roleplay"])
app.include_router(personality_router.router,   prefix="/api/personality",        tags=["personality"])
app.include_router(analysis_router.router,     prefix="/api/analysis",           tags=["analysis"])
app.include_router(onboarding_router.router,   prefix="/api/onboarding",         tags=["onboarding"])
app.include_router(reports_router.router,      prefix="/api/reports/weekly",      tags=["reports"])
app.include_router(usage_router.router,        prefix="/api",                     tags=["usage"])
app.include_router(legacy_chapters_router.router, prefix="/api/legacy-chapters",   tags=["legacy-chapters"])


@app.get("/api/healthz")
async def health():
    return {"status": "ok"}


# Serve the built React frontend in production.
# In dev, Vite handles /companion/ directly; this directory won't exist unless
# a production build has been run, so the mount is skipped silently.
_companion_dist = os.path.join(os.path.dirname(__file__), "..", "dist", "public")
if os.path.isdir(_companion_dist):
    app.mount("/", StaticFiles(directory=_companion_dist, html=True), name="companion-frontend")
