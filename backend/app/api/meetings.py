from fastapi import APIRouter, HTTPException, status
from typing import List

from app.models.schemas import Meeting, CreateMeetingRequest, TranscriptSegment
from app.services.meeting_store import meeting_store

router = APIRouter()


# ---------------------------------------------------------------------------
# POST /api/meetings — create a new meeting
# ---------------------------------------------------------------------------

@router.post(
    "/meetings",
    response_model=Meeting,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new meeting",
)
async def create_meeting(body: CreateMeetingRequest) -> Meeting:
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
