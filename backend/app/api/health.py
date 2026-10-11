from __future__ import annotations

import asyncio

from fastapi import APIRouter, Response, status

from app.core.config import settings
from app.models.schemas import HealthResponse
from app.services.redis_service import redis_available
from app.services.smart_meeting_store import smart_meeting_store

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health",
    responses={503: {"description": "PostgreSQL is down and the memory fallback is disabled"}},
)
async def health(response: Response) -> HealthResponse:
    """Reports which backends are in use. ``degraded`` still serves requests."""
    database, redis_ok = await asyncio.gather(smart_meeting_store.health(), redis_available())
    if database == "unavailable":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if database == "postgres" and redis_ok else "degraded",
        database=database,
        redis="connected" if redis_ok else "unavailable",
        transcription=settings.transcription_mode,
        ai="configured" if settings.ai_configured else "not_configured",
    )
