import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timezone
import uuid

from app.models.schemas import Meeting, MeetingInsights, TranscriptSegment


class MeetingStore:
    """
    Thread-safe in-memory store for meetings and transcript segments.
    Uses asyncio.Lock to guard all mutations.
    """

    def __init__(self) -> None:
        self._meetings: Dict[str, Meeting] = {}
        self._transcripts: Dict[str, List[TranscriptSegment]] = {}
        self._insights: Dict[str, MeetingInsights] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Meeting operations
    # ------------------------------------------------------------------

    async def create_meeting(self, title: str) -> Meeting:
        """Create a new active meeting and return it."""
        meeting = Meeting(
            id=str(uuid.uuid4()),
            title=title,
            status="active",
            started_at=datetime.now(timezone.utc),
            ended_at=None,
        )
        async with self._lock:
            self._meetings[meeting.id] = meeting
            self._transcripts[meeting.id] = []
        return meeting

    async def get_meeting(self, meeting_id: str) -> Optional[Meeting]:
        """Return a meeting by id, or None if not found."""
        async with self._lock:
            return self._meetings.get(meeting_id)

    async def list_meetings(self) -> List[Meeting]:
        """Return all meetings sorted by start time (newest first)."""
        async with self._lock:
            return sorted(
                self._meetings.values(),
                key=lambda m: m.started_at,
                reverse=True,
            )

    async def end_meeting(self, meeting_id: str) -> Optional[Meeting]:
        """
        Mark a meeting as ended.
        Returns the updated Meeting, or None if the meeting does not exist.
        """
        async with self._lock:
            meeting = self._meetings.get(meeting_id)
            if meeting is None:
                return None
            # Pydantic v2 models are immutable by default — rebuild with updates
            updated = meeting.model_copy(
                update={
                    "status": "ended",
                    "ended_at": datetime.now(timezone.utc),
                }
            )
            self._meetings[meeting_id] = updated
            return updated

    # ------------------------------------------------------------------
    # Transcript operations
    # ------------------------------------------------------------------

    async def add_segment(self, segment: TranscriptSegment) -> TranscriptSegment:
        """Append a transcript segment to the meeting's transcript list."""
        async with self._lock:
            if segment.meeting_id not in self._transcripts:
                self._transcripts[segment.meeting_id] = []
            self._transcripts[segment.meeting_id].append(segment)
        return segment

    async def get_segments(self, meeting_id: str) -> List[TranscriptSegment]:
        """Return all transcript segments for a meeting, in order."""
        async with self._lock:
            return list(self._transcripts.get(meeting_id, []))

    # ------------------------------------------------------------------
    # Insights operations
    # ------------------------------------------------------------------

    async def save_insights(self, insights: MeetingInsights) -> MeetingInsights:
        """Persist AI-generated insights for a meeting."""
        async with self._lock:
            self._insights[insights.meeting_id] = insights
        return insights

    async def get_insights(self, meeting_id: str) -> Optional[MeetingInsights]:
        """Return stored insights for a meeting, or None if not yet generated."""
        async with self._lock:
            return self._insights.get(meeting_id)


# Module-level singleton — imported by routers and the WebSocket handler.
meeting_store = MeetingStore()
