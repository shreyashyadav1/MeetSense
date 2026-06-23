from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MeetingInsightsORM, MeetingORM, TranscriptSegmentORM
from app.models.schemas import Meeting, MeetingInsights, TranscriptSegment


def _orm_to_meeting(row: MeetingORM) -> Meeting:
    return Meeting(
        id=row.id,
        title=row.title,
        status=row.status,
        started_at=row.started_at,
        ended_at=row.ended_at,
    )


def _orm_to_segment(row: TranscriptSegmentORM) -> TranscriptSegment:
    return TranscriptSegment(
        id=row.id,
        meeting_id=row.meeting_id,
        speaker=row.speaker,
        text=row.text,
        timestamp=row.timestamp,
        confidence=row.confidence,
        is_final=row.is_final,
    )


def _orm_to_insights(row: MeetingInsightsORM) -> MeetingInsights:
    return MeetingInsights(
        id=row.id,
        meeting_id=row.meeting_id,
        summary=row.summary,
        action_items=row.action_items,
        decisions=row.decisions,
        questions_raised=row.questions_raised,
        follow_up_email=row.follow_up_email,
        generated_at=row.generated_at,
    )


class MeetingRepository:
    """
    Data-access layer backed by an SQLAlchemy AsyncSession.

    All methods mirror the interface of MeetingStore so that
    PgMeetingStore can be used as a drop-in replacement.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Meeting operations
    # ------------------------------------------------------------------

    async def create_meeting(self, id: str, title: str) -> Meeting:
        row = MeetingORM(
            id=id,
            title=title,
            status="active",
            started_at=datetime.now(timezone.utc),
            ended_at=None,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return _orm_to_meeting(row)

    async def get_meeting(self, meeting_id: str) -> Optional[Meeting]:
        result = await self._session.execute(
            select(MeetingORM).where(MeetingORM.id == meeting_id)
        )
        row = result.scalar_one_or_none()
        return _orm_to_meeting(row) if row is not None else None

    async def list_meetings(self) -> list[Meeting]:
        result = await self._session.execute(
            select(MeetingORM).order_by(MeetingORM.started_at.desc())
        )
        rows = result.scalars().all()
        return [_orm_to_meeting(r) for r in rows]

    async def end_meeting(self, meeting_id: str) -> Optional[Meeting]:
        result = await self._session.execute(
            select(MeetingORM).where(MeetingORM.id == meeting_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        row.status = "ended"
        row.ended_at = datetime.now(timezone.utc)
        await self._session.commit()
        await self._session.refresh(row)
        return _orm_to_meeting(row)

    # ------------------------------------------------------------------
    # Transcript operations
    # ------------------------------------------------------------------

    async def add_segment(self, segment: TranscriptSegment) -> TranscriptSegment:
        row = TranscriptSegmentORM(
            id=segment.id,
            meeting_id=segment.meeting_id,
            speaker=segment.speaker,
            text=segment.text,
            timestamp=segment.timestamp,
            confidence=segment.confidence,
            is_final=segment.is_final,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return _orm_to_segment(row)

    async def get_segments(self, meeting_id: str) -> list[TranscriptSegment]:
        result = await self._session.execute(
            select(TranscriptSegmentORM)
            .where(TranscriptSegmentORM.meeting_id == meeting_id)
            .order_by(TranscriptSegmentORM.timestamp)
        )
        rows = result.scalars().all()
        return [_orm_to_segment(r) for r in rows]

    # ------------------------------------------------------------------
    # Insights operations
    # ------------------------------------------------------------------

    async def save_insights(self, insights: MeetingInsights) -> MeetingInsights:
        # Upsert pattern: replace existing row for this meeting if present.
        result = await self._session.execute(
            select(MeetingInsightsORM).where(
                MeetingInsightsORM.meeting_id == insights.meeting_id
            )
        )
        row = result.scalar_one_or_none()

        if row is None:
            row = MeetingInsightsORM(
                id=insights.id,
                meeting_id=insights.meeting_id,
            )
            self._session.add(row)

        row.summary = insights.summary
        row.action_items = insights.action_items
        row.decisions = insights.decisions
        row.questions_raised = insights.questions_raised
        row.follow_up_email = insights.follow_up_email
        row.generated_at = insights.generated_at

        await self._session.commit()
        await self._session.refresh(row)
        return _orm_to_insights(row)

    async def get_insights(self, meeting_id: str) -> Optional[MeetingInsights]:
        result = await self._session.execute(
            select(MeetingInsightsORM).where(
                MeetingInsightsORM.meeting_id == meeting_id
            )
        )
        row = result.scalar_one_or_none()
        return _orm_to_insights(row) if row is not None else None
