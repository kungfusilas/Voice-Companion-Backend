import os
import uvicorn

if __name__ == "__main__":
    # Always run on 8001 so Vite (on PORT) can proxy /companion/api/* to us
    port = int(os.environ.get("API_PORT", 8001))
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        reload=True,
    )
