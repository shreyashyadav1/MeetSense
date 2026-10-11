"""Meeting storage interface and its in-memory implementation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Protocol

from app.models.schemas import Meeting, MeetingInsights, TranscriptSegment


class MeetingStoreBackend(Protocol):
    """Operations every meeting store implements."""

    async def prepare(self) -> None:
        """Make the backend ready for use (e.g. apply schema migrations)."""

    async def ping(self) -> None:
        """Raise if the backend is not reachable."""

    async def create_meeting(self, title: str) -> Meeting: ...

    async def get_meeting(self, meeting_id: str) -> Meeting | None: ...

    async def list_meetings(self, *, limit: int, offset: int) -> list[Meeting]:
        """Meetings ordered newest first."""
        ...

    async def end_meeting(self, meeting_id: str) -> Meeting | None: ...

    async def add_segment(self, segment: TranscriptSegment) -> TranscriptSegment: ...

    async def get_segments(self, meeting_id: str) -> list[TranscriptSegment]:
        """Segments ordered by sequence."""
        ...

    async def get_last_sequence(self, meeting_id: str) -> int:
        """Highest stored segment sequence for the meeting, or 0."""
        ...

    async def save_insights(self, insights: MeetingInsights) -> MeetingInsights:
        """Insert or replace the meeting's insights."""
        ...

    async def get_insights(self, meeting_id: str) -> MeetingInsights | None: ...


class MeetingStore:
    """Process-local store, used when no database is configured or reachable.

    Everything runs on the event loop and no method awaits while mutating, so
    no locking is needed. Data is lost when the process exits.
    """

    def __init__(self) -> None:
        self._meetings: dict[str, Meeting] = {}
        self._segments: dict[str, list[TranscriptSegment]] = {}
        self._insights: dict[str, MeetingInsights] = {}

    async def prepare(self) -> None:
        return None

    async def ping(self) -> None:
        return None

    async def create_meeting(self, title: str) -> Meeting:
        meeting = Meeting(
            id=str(uuid.uuid4()),
            title=title,
            status="active",
            started_at=datetime.now(UTC),
        )
        self._meetings[meeting.id] = meeting
        return meeting

    async def get_meeting(self, meeting_id: str) -> Meeting | None:
        return self._meetings.get(meeting_id)

    async def list_meetings(self, *, limit: int, offset: int) -> list[Meeting]:
        newest_first = sorted(self._meetings.values(), key=lambda m: m.started_at, reverse=True)
        return newest_first[offset : offset + limit]

    async def end_meeting(self, meeting_id: str) -> Meeting | None:
        meeting = self._meetings.get(meeting_id)
        if meeting is None:
            return None
        if meeting.status != "ended":
            meeting = meeting.model_copy(update={"status": "ended", "ended_at": datetime.now(UTC)})
            self._meetings[meeting_id] = meeting
        return meeting

    async def add_segment(self, segment: TranscriptSegment) -> TranscriptSegment:
        self._segments.setdefault(segment.meeting_id, []).append(segment)
        return segment

    async def get_segments(self, meeting_id: str) -> list[TranscriptSegment]:
        return sorted(self._segments.get(meeting_id, []), key=lambda s: s.sequence)

    async def get_last_sequence(self, meeting_id: str) -> int:
        return max((s.sequence for s in self._segments.get(meeting_id, [])), default=0)

    async def save_insights(self, insights: MeetingInsights) -> MeetingInsights:
        self._insights[insights.meeting_id] = insights
        return insights

    async def get_insights(self, meeting_id: str) -> MeetingInsights | None:
        return self._insights.get(meeting_id)
