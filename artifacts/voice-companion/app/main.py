import os
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.routers import chat, personas, sessions, memories
from app.routers import import_memories
from app.routers import vault as vault_router
from app.routers import entitlements as entitlements_router
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
from app.routers import export as export_router
from app.routers import photo as photo_router
from app.routers import client_log as client_log_router
from app.routers import weekly_report as weekly_report_router
from app.routers import account as account_router
from app.routers import milestones as milestones_router
from app.routers import ritual as ritual_router
from app.routers import memory_dashboard as memory_dashboard_router
from app.routers import push as push_router
from app.routers import notifications as notifications_router
from app.services import notification_service
from app import store
from app.companions import COMPANIONS, build_system_prompt
from app import proactive, daily_checkin
import asyncio
from app.session_debrief import generate_session_debrief, get_latest_debrief, get_debrief_history
from app.weekly_insight import maybe_generate_weekly_insight, get_latest_weekly_insight, get_weekly_insight_history
from app.personality_map import update_personality_map, get_personality_map, get_personality_history
from app.communication_analysis import maybe_analyze_communication, get_latest_analysis, get_analysis_history
from app.routers.auth import verify_token

load_dotenv()

# Surface app-level INFO logs (e.g. [CLIENT] voice diagnostics from client_log)
# in the console. Uvicorn configures its own loggers; this covers the "app.*"
# namespace without touching uvicorn's handlers.
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)

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
    scheduler.add_job(
        notification_service.send_daily_question_notifications,
        "interval",
        hours=1,
        id="push_daily_questions",
        replace_existing=True,
    )
    scheduler.add_job(
        notification_service.send_weekly_question_set_notifications,
        "cron",
        day_of_week="mon",
        hour=9,
        minute=0,
        id="push_weekly_set",
        replace_existing=True,
    )
    scheduler.add_job(
        notification_service.send_reengagement_notifications,
        "cron",
        hour=9,
        minute=10,
        id="push_reengagement",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Schedulers started: proactive + daily activity + morning check-in + push notifications")

    yield

    scheduler.shutdown(wait=False)


app = FastAPI(
    title="AI Voice Companion API",
    version="1.0.0",
    lifespan=lifespan,
)

# Explicit origin allowlist — wildcard + credentials is invalid per Fetch spec
# and exposes the service to cross-origin abuse.
_ALLOWED_ORIGINS: list[str] = [
    "https://legacybond.ai",
    "https://www.legacybond.ai",
    "https://voice-companion-backend.replit.app",
]
# Include the per-workspace dev preview domain so local dev still works.
_dev_domain = os.environ.get("REPLIT_DEV_DOMAIN", "")
if _dev_domain:
    _ALLOWED_ORIGINS.append(f"https://{_dev_domain}")
# Include all production domains assigned by Replit (comma-separated).
for _prod_domain in os.environ.get("REPLIT_DOMAINS", "").split(","):
    _prod_domain = _prod_domain.strip()
    if _prod_domain:
        _ALLOWED_ORIGINS.append(f"https://{_prod_domain}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
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
app.include_router(memories.router,           prefix="/api/memories",           tags=["memories"])
app.include_router(import_memories.router)
app.include_router(vault_router.router)
app.include_router(entitlements_router.router)
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
app.include_router(export_router.router,          prefix="/api/export",              tags=["export"])
app.include_router(photo_router.router,           prefix="/api/photo",               tags=["photo"])
app.include_router(client_log_router.router,      prefix="/api",                     tags=["diagnostics"])
app.include_router(weekly_report_router.router,   prefix="/api/weekly-report",        tags=["weekly-report"])
app.include_router(account_router.router,         prefix="/api/account",              tags=["account"])
app.include_router(milestones_router.router,        prefix="/api/milestones",            tags=["milestones"])
app.include_router(ritual_router.router,            prefix="/api/ritual",                tags=["ritual"])
app.include_router(memory_dashboard_router.router,  prefix="/api/memory-dashboard",      tags=["memory-dashboard"])
app.include_router(push_router.router,              prefix="/api/push",                  tags=["push"])
app.include_router(notifications_router.router,     prefix="/api/notifications",          tags=["notifications"])


@app.get("/health")
@app.get("/api/healthz")
async def health():
    return {"status": "ok"}


@app.get("/api/debrief/latest")
async def debrief_latest(user_id: str = Depends(verify_token)):
    return await get_latest_debrief(user_id)


@app.get("/api/debrief/history")
async def debrief_history(user_id: str = Depends(verify_token)):
    return await get_debrief_history(user_id, limit=20)


@app.get("/api/insights/weekly/latest")
async def weekly_insight_latest(user_id: str = Depends(verify_token)):
    return await get_latest_weekly_insight(user_id)


@app.get("/api/insights/weekly/history")
async def weekly_insight_history(user_id: str = Depends(verify_token)):
    return await get_weekly_insight_history(user_id, limit=20)


@app.get("/api/personality/map")
async def personality_map_route(user_id: str = Depends(verify_token)):
    return await get_personality_map(user_id)


@app.get("/api/personality/history")
async def personality_history_route(user_id: str = Depends(verify_token)):
    return await get_personality_history(user_id, limit=20)


@app.get("/api/analysis/communication/latest")
async def communication_latest(user_id: str = Depends(verify_token)):
    return await get_latest_analysis(user_id)


@app.get("/api/analysis/communication/history")
async def communication_history(user_id: str = Depends(verify_token)):
    return await get_analysis_history(user_id, limit=10)


# Serve the built React frontend in production.
# In dev, Vite handles /companion/ directly; this directory won't exist unless
# a production build has been run, so the routes are skipped silently.
_companion_dist = Path(os.path.dirname(__file__)).parent / "dist" / "public"
_index_html = _companion_dist / "index.html"

# Cache headers for index.html — must NEVER be cached by the browser or any
# intermediate proxy (CDN, Safari, etc.).  Each deployment renames the
# content-hashed JS/CSS bundles; a stale index.html from a previous build will
# reference old hashes that no longer exist → blank white screen.
_NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _html_response() -> FileResponse:
    """Return index.html with headers that prevent browser/CDN caching."""
    return FileResponse(str(_index_html), headers=_NO_CACHE_HEADERS)


# Inline kill-switch used as a last-resort fallback if the SW file is missing from dist.
_SW_INLINE = """
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.map(k => caches.delete(k)));
    await clients.claim();
    await self.registration.unregister();
    const all = await clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const c of all) c.navigate(c.url);
  })());
});
""".strip()

if _companion_dist.is_dir():
    # Mount /assets/ for the Vite-built JS/CSS bundles.
    # These files are content-hashed by Vite so they can be cached indefinitely;
    # StaticFiles serves them with its default headers (no explicit override needed).
    # Must be registered before the catch-all routes below.
    _assets_dir = _companion_dist / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="companion-assets")

    # Kill-switch service workers — served with no-cache so browsers ALWAYS fetch
    # the latest version on their SW update check, bypassing any HTTP cache layer.
    # Both paths are covered because different builds may have registered either name.
    _SW_HEADERS = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
        "Content-Type": "application/javascript",
        "Service-Worker-Allowed": "/",
    }

    @app.get("/service-worker.js")
    async def _serve_sw() -> Response:
        sw_path = _companion_dist / "service-worker.js"
        if sw_path.is_file():
            return FileResponse(str(sw_path), headers=_SW_HEADERS)
        # Fallback inline kill-switch if file is somehow missing
        return Response(content=_SW_INLINE, media_type="application/javascript", headers=_SW_HEADERS)

    @app.get("/sw.js")
    async def _serve_sw_alt() -> Response:
        sw_path = _companion_dist / "sw.js"
        if sw_path.is_file():
            return FileResponse(str(sw_path), headers=_SW_HEADERS)
        return Response(content=_SW_INLINE, media_type="application/javascript", headers=_SW_HEADERS)

    # Serve root explicitly so the Replit liveness probe at /companion/ → / always gets 200.
    @app.get("/")
    async def _serve_root() -> FileResponse:
        return _html_response()

    # Catch-all: serve index.html for any client-side SPA route (404-fallback).
    # Resolve the candidate to an absolute path and verify it stays inside
    # _companion_dist to prevent path-traversal (e.g. //etc/passwd tricks
    # where pathlib's / operator would replace the base with an absolute path).
    _dist_root = _companion_dist.resolve()

    @app.get("/{full_path:path}")
    async def _serve_spa(full_path: str) -> FileResponse:
        try:
            candidate = (_companion_dist / full_path).resolve()
        except Exception:
            return _html_response()
        if not str(candidate).startswith(str(_dist_root)):
            return _html_response()
        if candidate.is_file():
            return FileResponse(str(candidate))
        return _html_response()
