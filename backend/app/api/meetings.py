import logging
from typing import List

from fastapi import APIRouter, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.models.schemas import Meeting, CreateMeetingRequest, MeetingInsights, TranscriptSegment
from app.services.smart_meeting_store import smart_meeting_store as meeting_store
from app.services.ai_service import generate_insights

logger = logging.getLogger(__name__)

router = APIRouter()

limiter = Limiter(key_func=get_remote_address)


# ---------------------------------------------------------------------------
# POST /api/meetings — create a new meeting
# ---------------------------------------------------------------------------

@router.post(
    "/meetings",
    response_model=Meeting,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new meeting",
)
@limiter.limit("20/minute")
async def create_meeting(request: Request, body: CreateMeetingRequest) -> Meeting:
    """
    Create a new meeting in *active* status.
    Returns the full Meeting object including the generated id and started_at.
    """
    meeting = await meeting_store.create_meeting(title=body.title)
    return meeting


# ---------------------------------------------------------------------------
# GET /api/meetings — list all meetings
# ---------------------------------------------------------------------------

@router.get(
    "/meetings",
    response_model=List[Meeting],
    summary="List all meetings",
)
async def list_meetings() -> List[Meeting]:
    """Return all meetings sorted by start time (newest first)."""
    return await meeting_store.list_meetings()


# ---------------------------------------------------------------------------
# GET /api/meetings/{meeting_id} — get a single meeting
# ---------------------------------------------------------------------------

@router.get(
    "/meetings/{meeting_id}",
    response_model=Meeting,
    summary="Get a meeting by id",
)
async def get_meeting(meeting_id: str) -> Meeting:
    meeting = await meeting_store.get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting '{meeting_id}' not found.",
        )
    return meeting


# ---------------------------------------------------------------------------
# POST /api/meetings/{meeting_id}/end — end a meeting
# ---------------------------------------------------------------------------

@router.post(
    "/meetings/{meeting_id}/end",
    response_model=Meeting,
    summary="End an active meeting",
)
async def end_meeting(meeting_id: str) -> Meeting:
    """
    Transition a meeting from *active* to *ended* and record the ended_at
    timestamp.  Returns 404 if the meeting does not exist.
    """
    meeting = await meeting_store.get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting '{meeting_id}' not found.",
        )
    if meeting.status == "ended":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Meeting '{meeting_id}' has already ended.",
        )
    updated = await meeting_store.end_meeting(meeting_id)
    return updated  # type: ignore[return-value]  # end_meeting returns Optional but we checked above


# ---------------------------------------------------------------------------
# GET /api/meetings/{meeting_id}/transcript — fetch transcript segments
# ---------------------------------------------------------------------------

@router.get(
    "/meetings/{meeting_id}/transcript",
    response_model=List[TranscriptSegment],
    summary="Get transcript segments for a meeting",
)
async def get_transcript(meeting_id: str) -> List[TranscriptSegment]:
    """
    Return all transcript segments collected so far for the given meeting.
    Returns 404 if the meeting does not exist.
    """
    meeting = await meeting_store.get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting '{meeting_id}' not found.",
        )
    return await meeting_store.get_segments(meeting_id)


# ---------------------------------------------------------------------------
# POST /api/meetings/{meeting_id}/summarize — generate AI insights
# ---------------------------------------------------------------------------

@router.post(
    "/meetings/{meeting_id}/summarize",
    response_model=MeetingInsights,
    summary="Generate AI insights for a meeting (idempotent)",
)
@limiter.limit("5/minute")
async def summarize_meeting(request: Request, meeting_id: str) -> MeetingInsights:
    """
    Generate AI-powered insights (summary, action items, decisions, questions,
    follow-up email) from the meeting transcript using Groq.

    - Returns 200 with cached insights if they have already been generated.
    - Returns 400 if no transcript segments exist yet.
    - Returns 503 if GROQ_API_KEY is not configured.
    - Returns 502 if the Groq API call fails.
    """
    meeting = await meeting_store.get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting '{meeting_id}' not found.",
        )

    # Idempotent: return cached insights if already generated
    existing = await meeting_store.get_insights(meeting_id)
    if existing is not None:
        return existing

    segments = await meeting_store.get_segments(meeting_id)
    final_segments = [s for s in segments if s.is_final]

    if not final_segments:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No transcript available to summarize.",
        )

    try:
        insights = await generate_insights(
            meeting_id=meeting_id,
            meeting_title=meeting.title,
            segments=final_segments,
        )
    except ValueError as exc:
        msg = str(exc)
        if "GROQ_API_KEY" in msg:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI service not configured. Set GROQ_API_KEY in .env",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=msg,
        )
    except Exception as exc:
        logger.error("[AI] Groq API error for meeting %s: %s", meeting_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI service error: {exc}",
        )

    saved = await meeting_store.save_insights(insights)
    return saved


# ---------------------------------------------------------------------------
# GET /api/meetings/{meeting_id}/insights — retrieve saved AI insights
# ---------------------------------------------------------------------------

@router.get(
    "/meetings/{meeting_id}/insights",
    response_model=MeetingInsights,
    summary="Get saved AI insights for a meeting",
)
async def get_insights(meeting_id: str) -> MeetingInsights:
    """
    Return previously generated insights for the given meeting.
    Returns 404 if the meeting does not exist or insights have not been generated yet.
    """
    meeting = await meeting_store.get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting '{meeting_id}' not found.",
        )

    insights = await meeting_store.get_insights(meeting_id)
    if insights is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No insights found for meeting '{meeting_id}'. Call POST /summarize first.",
        )
    return insights
