"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy.engine import make_url

from app.api.health import router as health_router
from app.api.meetings import router as meetings_router
from app.api.websocket import router as websocket_router
from app.core.config import settings
from app.core.rate_limit import limiter, rate_limit_exceeded_handler
from app.services import ai_service
from app.services.redis_service import close_redis
from app.services.smart_meeting_store import DatabaseUnavailableError, smart_meeting_store
from app.services.transcription_hub import transcription_hub

logger = logging.getLogger(__name__)


def _log_configuration() -> None:
    database = (
        make_url(settings.database_url).render_as_string(hide_password=True)
        if settings.database_url
        else "in-memory"
    )
    logger.info(
        "Transcription: %s | AI insights: %s | Database: %s | Redis: %s",
        settings.transcription_mode,
        f"groq/{settings.groq_model}" if settings.ai_configured else "not configured",
        database,
        "configured" if settings.redis_url else "disabled",
    )
    if settings.transcription_mode == "deepgram" and not settings.deepgram_api_key:
        logger.warning(
            "MOCK_TRANSCRIPTION is false but DEEPGRAM_API_KEY is empty; live streams will fail"
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    _log_configuration()
    await smart_meeting_store.startup()
    try:
        yield
    finally:
        await transcription_hub.shutdown()
        await ai_service.close_client()
        await close_redis()
        await smart_meeting_store.shutdown()


def _describe_validation_errors(errors: list[dict[str, Any]]) -> str:
    messages = []
    for error in errors:
        location = ".".join(
            str(part) for part in error.get("loc", ()) if part not in ("body", "query", "path")
        )
        messages.append(f"{location}: {error.get('msg')}" if location else str(error.get("msg")))
    return "; ".join(messages) or "Invalid request."


async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # "detail" is a readable string like every other error response; the
    # structured errors FastAPI normally returns are kept under "errors".
    errors = jsonable_encoder(exc.errors())
    return JSONResponse(
        status_code=422, content={"detail": _describe_validation_errors(errors), "errors": errors}
    )


async def _database_unavailable_handler(
    request: Request, exc: DatabaseUnavailableError
) -> JSONResponse:
    return JSONResponse(
        status_code=503, content={"detail": "The database is unavailable. Please try again."}
    )


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Starlette re-raises after this handler, so the traceback is still logged.
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


def create_app() -> FastAPI:
    app = FastAPI(
        title="MeetSense AI",
        description="Real-time meeting transcription and AI insights.",
        version="0.4.0",
        lifespan=lifespan,
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(DatabaseUnavailableError, _database_unavailable_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.include_router(meetings_router, prefix="/api", tags=["Meetings"])
    app.include_router(websocket_router, prefix="/ws", tags=["WebSocket"])
    app.include_router(health_router, tags=["Health"])
    return app


app = create_app()
