"""
Meeting store that tries PostgreSQL first, then falls back to in-memory.

This lets the app run on Railway even when the database is unreachable (e.g.
the Supabase project is IPv6-only and Railway has no IPv6 route).  The full
PostgreSQL code path (models, repository, async engine) is still exercised
when the DB is reachable, so the architecture remains valid.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.models.schemas import Meeting, MeetingInsights, TranscriptSegment
from app.services.meeting_store import MeetingStore
from app.services.pg_meeting_store import PgMeetingStore

logger = logging.getLogger(__name__)


class SmartMeetingStore:
    def __init__(self) -> None:
        self._pg = PgMeetingStore()
        self._mem = MeetingStore()
        self._use_pg = True

    def _mark_mem(self, exc: Exception) -> None:
        if self._use_pg:
            logger.warning(
                "DB unavailable — switching to in-memory store for this session. "
                "Error: %s",
                exc,
            )
            self._use_pg = False

    # ------------------------------------------------------------------
    # Meeting operations
    # ------------------------------------------------------------------

    async def create_meeting(self, title: str) -> Meeting:
        if not self._use_pg:
            return await self._mem.create_meeting(title)
        try:
            return await self._pg.create_meeting(title)
        except Exception as exc:
            self._mark_mem(exc)
            return await self._mem.create_meeting(title)

    async def get_meeting(self, meeting_id: str) -> Optional[Meeting]:
        if not self._use_pg:
            return await self._mem.get_meeting(meeting_id)
        try:
            return await self._pg.get_meeting(meeting_id)
        except Exception as exc:
            self._mark_mem(exc)
            return await self._mem.get_meeting(meeting_id)

    async def list_meetings(self) -> list[Meeting]:
        if not self._use_pg:
            return await self._mem.list_meetings()
        try:
            return await self._pg.list_meetings()
        except Exception as exc:
            self._mark_mem(exc)
            return await self._mem.list_meetings()

    async def end_meeting(self, meeting_id: str) -> Optional[Meeting]:
        if not self._use_pg:
            return await self._mem.end_meeting(meeting_id)
        try:
            return await self._pg.end_meeting(meeting_id)
        except Exception as exc:
            self._mark_mem(exc)
            return await self._mem.end_meeting(meeting_id)

    # ------------------------------------------------------------------
    # Transcript operations
    # ------------------------------------------------------------------

    async def add_segment(self, segment: TranscriptSegment) -> TranscriptSegment:
        if not self._use_pg:
            return await self._mem.add_segment(segment)
        try:
            return await self._pg.add_segment(segment)
        except Exception as exc:
            self._mark_mem(exc)
            return await self._mem.add_segment(segment)

    async def get_segments(self, meeting_id: str) -> list[TranscriptSegment]:
        if not self._use_pg:
            return await self._mem.get_segments(meeting_id)
        try:
            return await self._pg.get_segments(meeting_id)
        except Exception as exc:
            self._mark_mem(exc)
            return await self._mem.get_segments(meeting_id)

    # ------------------------------------------------------------------
    # Insights operations
    # ------------------------------------------------------------------

    async def save_insights(self, insights: MeetingInsights) -> MeetingInsights:
        if not self._use_pg:
            return await self._mem.save_insights(insights)
        try:
            return await self._pg.save_insights(insights)
        except Exception as exc:
            self._mark_mem(exc)
            return await self._mem.save_insights(insights)

    async def get_insights(self, meeting_id: str) -> Optional[MeetingInsights]:
        if not self._use_pg:
            return await self._mem.get_insights(meeting_id)
        try:
            return await self._pg.get_insights(meeting_id)
        except Exception as exc:
            self._mark_mem(exc)
            return await self._mem.get_insights(meeting_id)


# Singleton — import this in routers instead of pg_meeting_store.
smart_meeting_store = SmartMeetingStore()
