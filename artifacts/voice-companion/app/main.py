import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.routers import chat, personas, sessions, tts, stt, memories
from app.routers import proactive as proactive_router
from app.routers import selfie as selfie_router
from app.routers import relationship as relationship_router
from app.routers import activities as activities_router
from app import store
from app.companions import COMPANIONS, build_system_prompt
from app import proactive

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
    scheduler.start()
    logger.info("Schedulers started: proactive check-in + daily activity")

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

app.include_router(chat.router,              prefix="/api/chat",               tags=["chat"])
app.include_router(personas.router,          prefix="/api/personas",           tags=["personas"])
app.include_router(sessions.router,          prefix="/api/sessions",           tags=["sessions"])
app.include_router(tts.router,               prefix="/api/tts",                tags=["tts"])
app.include_router(stt.router,               prefix="/api/stt",                tags=["stt"])
app.include_router(memories.router,          prefix="/api/memories",           tags=["memories"])
app.include_router(proactive_router.router,  prefix="/api/proactive-messages", tags=["proactive"])
app.include_router(selfie_router.router,     prefix="/api/selfie",             tags=["selfie"])
app.include_router(relationship_router.router, prefix="/api/relationship",     tags=["relationship"])
app.include_router(activities_router.router, prefix="/api/activity",           tags=["activities"])


@app.get("/api/healthz")
async def health():
    return {"status": "ok"}
