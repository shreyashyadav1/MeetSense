import logging

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.api.meetings import router as meetings_router
from app.api.websocket import router as websocket_router
from app.db.init_db import create_tables
from app.services.redis_service import close_redis

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
# Rate limiter (shared instance — imported by routers)
# ---------------------------------------------------------------------------

limiter = Limiter(key_func=get_remote_address)

# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    app = FastAPI(
        title="MeetSense AI",
        description="Real-time meeting transcription and AI insights platform.",
        version="0.3.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # -----------------------------------------------------------------------
    # Rate limiting
    # -----------------------------------------------------------------------
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.on_event("startup")
    async def startup():
        try:
            await create_tables()
            logger.info("Database tables ready")
        except Exception as exc:
            logger.warning("DB init failed (will retry on first request): %s", exc)

    @app.on_event("shutdown")
    async def shutdown():
        await close_redis()
        logger.info("Redis connection closed")

    # -----------------------------------------------------------------------
    # CORS — allow the Vite dev server (and common localhost variants)
    # -----------------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "https://meet-sense.vercel.app",
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
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info",
    )
