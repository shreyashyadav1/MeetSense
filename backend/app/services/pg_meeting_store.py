"""PostgreSQL implementation of the meeting store."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import get_engine, get_session_factory
from app.db.migrations import upgrade_to_head
from app.db.models import MeetingInsightsORM, MeetingORM, TranscriptSegmentORM
from app.models.schemas import Meeting, MeetingInsights, TranscriptSegment


class PgMeetingStore:
    """Each call runs in its own short-lived session."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        self._session_factory = session_factory

    def _session(self) -> AsyncSession:
        factory = self._session_factory or get_session_factory()
        return factory()

    async def prepare(self) -> None:
        await upgrade_to_head(get_engine())

    async def ping(self) -> None:
        async with self._session() as session:
            await session.execute(text("SELECT 1"))

    # --- Meetings -----------------------------------------------------------

    async def create_meeting(self, title: str) -> Meeting:
        row = MeetingORM(
            id=str(uuid.uuid4()),
            title=title,
            status="active",
            started_at=datetime.now(UTC),
            ended_at=None,
        )
        async with self._session() as session:
            session.add(row)
            await session.commit()
        return Meeting.model_validate(row)

    async def get_meeting(self, meeting_id: str) -> Meeting | None:
        async with self._session() as session:
            row = await session.get(MeetingORM, meeting_id)
        return Meeting.model_validate(row) if row is not None else None

    async def list_meetings(self, *, limit: int, offset: int) -> list[Meeting]:
        query = (
            select(MeetingORM)
            .order_by(MeetingORM.started_at.desc(), MeetingORM.id)
            .limit(limit)
            .offset(offset)
        )
        async with self._session() as session:
            rows = (await session.scalars(query)).all()
        return [Meeting.model_validate(row) for row in rows]

    async def end_meeting(self, meeting_id: str) -> Meeting | None:
        async with self._session() as session:
            row = await session.get(MeetingORM, meeting_id, with_for_update=True)
            if row is None:
                return None
            if row.status != "ended":
                row.status = "ended"
                row.ended_at = datetime.now(UTC)
            await session.commit()
        return Meeting.model_validate(row)

    # --- Transcript ---------------------------------------------------------

    async def add_segment(self, segment: TranscriptSegment) -> TranscriptSegment:
        async with self._session() as session:
            session.add(TranscriptSegmentORM(**segment.model_dump()))
            await session.commit()
        return segment

    async def get_segments(self, meeting_id: str) -> list[TranscriptSegment]:
        query = (
            select(TranscriptSegmentORM)
            .where(TranscriptSegmentORM.meeting_id == meeting_id)
            .order_by(TranscriptSegmentORM.sequence)
        )
        async with self._session() as session:
            rows = (await session.scalars(query)).all()
        return [TranscriptSegment.model_validate(row) for row in rows]

    async def get_last_sequence(self, meeting_id: str) -> int:
        query = select(func.coalesce(func.max(TranscriptSegmentORM.sequence), 0)).where(
            TranscriptSegmentORM.meeting_id == meeting_id
        )
        async with self._session() as session:
            return int(await session.scalar(query) or 0)

    # --- Insights -----------------------------------------------------------

    async def save_insights(self, insights: MeetingInsights) -> MeetingInsights:
        values = insights.model_dump()
        statement = insert(MeetingInsightsORM).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[MeetingInsightsORM.meeting_id],
            set_={
                column: statement.excluded[column]
                for column in values
                if column not in ("id", "meeting_id")
            },
        ).returning(MeetingInsightsORM)
        async with self._session() as session:
            row = (await session.scalars(statement)).one()
            await session.commit()
        return MeetingInsights.model_validate(row)

    async def get_insights(self, meeting_id: str) -> MeetingInsights | None:
        query = select(MeetingInsightsORM).where(MeetingInsightsORM.meeting_id == meeting_id)
        async with self._session() as session:
            row = await session.scalar(query)
        return MeetingInsights.model_validate(row) if row is not None else None
