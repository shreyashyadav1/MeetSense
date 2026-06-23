import logging

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.meetings import router as meetings_router
from app.api.websocket import router as websocket_router

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    app = FastAPI(
        title="MeetSense AI",
        description=(
            "Real-time meeting transcription and AI insights platform. "
            "Phase 1 — in-memory store with mock transcript streaming."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # -----------------------------------------------------------------------
    # CORS — allow the Vite dev server (and common localhost variants)
    # -----------------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",   # Vite default
            "http://127.0.0.1:5173",
            "http://localhost:3000",   # CRA / Next.js fallback
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -----------------------------------------------------------------------
    # Routers
    # -----------------------------------------------------------------------
    app.include_router(meetings_router, prefix="/api", tags=["Meetings"])
    app.include_router(websocket_router, prefix="/ws", tags=["WebSocket"])

    # -----------------------------------------------------------------------
    # Health-check
    # -----------------------------------------------------------------------
    @app.get("/health", tags=["Health"])
    async def health() -> dict:
        return {"status": "ok", "service": "meetsense-backend"}

    return app


app = create_app()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
