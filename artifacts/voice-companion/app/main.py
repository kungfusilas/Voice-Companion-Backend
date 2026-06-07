import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from app.routers import chat, personas, sessions, tts, stt

load_dotenv()

app = FastAPI(
    title="AI Voice Companion API",
    description="Backend for an AI voice companion app with custom personas and conversation memory",
    version="1.0.0",
    root_path="/companion/",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(personas.router, prefix="/api/personas", tags=["personas"])
app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])
app.include_router(tts.router, prefix="/api/tts", tags=["tts"])
app.include_router(stt.router, prefix="/api/stt", tags=["stt"])


@app.get("/api/healthz")
async def health():
    return {"status": "ok"}
