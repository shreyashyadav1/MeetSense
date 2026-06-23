"""
PostgreSQL-backed meeting store.

Drop-in replacement for MeetingStore (meeting_store.py).
Has an identical async interface — every public method has the same
signature and return type.  Swap the singleton import in meetings.py
and websocket.py when the DATABASE_URL is ready.
"""

from __future__ import annotations

from typing import Optional
import uuid

from app.db.base import get_session_factory
from app.db.repository import MeetingRepository
from app.models.schemas import Meeting, MeetingInsights, TranscriptSegment


class PgMeetingStore:
    """
    Each method opens its own session from the factory, delegates to
    MeetingRepository, and closes the session on exit.

    No in-memory state is kept — all data lives in PostgreSQL.
    """

    # ------------------------------------------------------------------
    # Meeting operations
    # ------------------------------------------------------------------

    async def create_meeting(self, title: str) -> Meeting:
        meeting_id = str(uuid.uuid4())
        async with get_session_factory()() as session:
            repo = MeetingRepository(session)
            return await repo.create_meeting(id=meeting_id, title=title)

    async def get_meeting(self, meeting_id: str) -> Optional[Meeting]:
        async with get_session_factory()() as session:
            repo = MeetingRepository(session)
            return await repo.get_meeting(meeting_id)

    async def list_meetings(self) -> list[Meeting]:
        async with get_session_factory()() as session:
            repo = MeetingRepository(session)
            return await repo.list_meetings()

    async def end_meeting(self, meeting_id: str) -> Optional[Meeting]:
        async with get_session_factory()() as session:
            repo = MeetingRepository(session)
            return await repo.end_meeting(meeting_id)

    # ------------------------------------------------------------------
    # Transcript operations
    # ------------------------------------------------------------------

    async def add_segment(self, segment: TranscriptSegment) -> TranscriptSegment:
        async with get_session_factory()() as session:
            repo = MeetingRepository(session)
            return await repo.add_segment(segment)

    async def get_segments(self, meeting_id: str) -> list[TranscriptSegment]:
        async with get_session_factory()() as session:
            repo = MeetingRepository(session)
            return await repo.get_segments(meeting_id)

    # ------------------------------------------------------------------
    # Insights operations
    # ------------------------------------------------------------------

    async def save_insights(self, insights: MeetingInsights) -> MeetingInsights:
        async with get_session_factory()() as session:
            repo = MeetingRepository(session)
            return await repo.save_insights(insights)

    async def get_insights(self, meeting_id: str) -> Optional[MeetingInsights]:
        async with get_session_factory()() as session:
            repo = MeetingRepository(session)
            return await repo.get_insights(meeting_id)


# Module-level singleton — mirrors meeting_store.meeting_store.
# Import this instead of meeting_store once DATABASE_URL is configured.
pg_meeting_store = PgMeetingStore()
