from __future__ import annotations

import asyncio
import logging
from typing import Annotated
from weakref import WeakValueDictionary

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.core.config import settings
from app.core.rate_limit import limiter
from app.models.schemas import CreateMeetingRequest, Meeting, MeetingInsights, TranscriptSegment
from app.services.ai_service import (
    AINotConfiguredError,
    AIResponseError,
    AIUpstreamError,
    generate_insights,
)
from app.services.smart_meeting_store import smart_meeting_store as meeting_store

logger = logging.getLogger(__name__)

router = APIRouter()

# One summarization at a time per meeting, so concurrent requests share one
# model call. Entries disappear once no request holds the lock.
_insight_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()


def _insights_lock(meeting_id: str) -> asyncio.Lock:
    lock = _insight_locks.get(meeting_id)
    if lock is None:
        lock = _insight_locks[meeting_id] = asyncio.Lock()
    return lock


async def _get_meeting_or_404(meeting_id: str) -> Meeting:
    meeting = await meeting_store.get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Meeting '{meeting_id}' not found.")
    return meeting


@router.post(
    "/meetings",
    response_model=Meeting,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new meeting",
)
@limiter.limit(lambda: settings.create_meeting_rate_limit)
async def create_meeting(request: Request, body: CreateMeetingRequest) -> Meeting:
    """Create a meeting in *active* status. The title is trimmed (1-120 characters)."""
    return await meeting_store.create_meeting(title=body.title)


@router.get("/meetings", response_model=list[Meeting], summary="List meetings, newest first")
async def list_meetings(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Meeting]:
    return await meeting_store.list_meetings(limit=limit, offset=offset)


@router.get("/meetings/{meeting_id}", response_model=Meeting, summary="Get a meeting by id")
async def get_meeting(meeting_id: str) -> Meeting:
    return await _get_meeting_or_404(meeting_id)


@router.post(
    "/meetings/{meeting_id}/end",
    response_model=Meeting,
    summary="End an active meeting",
    responses={404: {"description": "Unknown meeting"}, 409: {"description": "Already ended"}},
)
async def end_meeting(meeting_id: str) -> Meeting:
    meeting = await _get_meeting_or_404(meeting_id)
    if meeting.status == "ended":
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=f"Meeting '{meeting_id}' has already ended."
        )
    ended = await meeting_store.end_meeting(meeting_id)
    if ended is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Meeting '{meeting_id}' not found.")
    return ended


@router.get(
    "/meetings/{meeting_id}/transcript",
    response_model=list[TranscriptSegment],
    summary="Get the stored transcript, in order",
)
async def get_transcript(meeting_id: str) -> list[TranscriptSegment]:
    await _get_meeting_or_404(meeting_id)
    return await meeting_store.get_segments(meeting_id)


@router.post(
    "/meetings/{meeting_id}/summarize",
    response_model=MeetingInsights,
    summary="Generate AI insights for a meeting",
    responses={
        400: {"description": "The meeting has no transcript yet"},
        404: {"description": "Unknown meeting"},
        429: {"description": "Rate limited"},
        502: {"description": "The AI provider failed or returned unusable output"},
        503: {"description": "AI insights are not configured"},
    },
)
@limiter.limit("5/minute")
async def summarize_meeting(
    request: Request,
    meeting_id: str,
    force: Annotated[bool, Query(description="Regenerate even if insights exist")] = False,
) -> MeetingInsights:
    """Summary, action items, decisions, open questions and a follow-up email.

    Returns the stored insights unless ``force=true``.
    """
    meeting = await _get_meeting_or_404(meeting_id)
    async with _insights_lock(meeting_id):
        if not force and (cached := await meeting_store.get_insights(meeting_id)) is not None:
            return cached

        segments = [s for s in await meeting_store.get_segments(meeting_id) if s.is_final]
        if not segments:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail="No transcript available to summarize."
            )
        try:
            insights = await generate_insights(
                meeting_id=meeting_id, meeting_title=meeting.title, segments=segments
            )
        except AINotConfiguredError:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI insights are not configured on this server.",
            ) from None
        except (AIUpstreamError, AIResponseError) as error:
            logger.warning("Insight generation failed for meeting %s: %s", meeting_id, error)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                detail="The AI service could not generate insights. Please try again.",
            ) from None
        return await meeting_store.save_insights(insights)


@router.get(
    "/meetings/{meeting_id}/insights",
    response_model=MeetingInsights,
    summary="Get stored AI insights",
)
async def get_insights(meeting_id: str) -> MeetingInsights:
    await _get_meeting_or_404(meeting_id)
    insights = await meeting_store.get_insights(meeting_id)
    if insights is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"No insights found for meeting '{meeting_id}'. Call POST /summarize first.",
        )
    return insights
