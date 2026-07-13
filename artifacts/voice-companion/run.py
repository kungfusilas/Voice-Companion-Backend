import os
import uvicorn

if __name__ == "__main__":
    # Always run on 8001 so Vite (on PORT) can proxy /companion/api/* to us
    port = int(os.environ.get("API_PORT", 8001))
    # Hot-reload is a dev-only feature (file watching, higher overhead, and
    # unexpected restarts in prod). Opt in with DEV=1 for local development.
    reload = os.environ.get("DEV", "").lower() in ("1", "true", "yes")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        reload=reload,
    )
