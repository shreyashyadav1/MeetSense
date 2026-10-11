from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# Relationships use lazy="raise": segments are only ever loaded by explicit
# queries (the transcript endpoint), never implicitly with a meeting.


class MeetingORM(Base):
    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20))  # "active" | "ended"
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    segments: Mapped[list[TranscriptSegmentORM]] = relationship(
        back_populates="meeting", lazy="raise", passive_deletes=True
    )
    insights: Mapped[MeetingInsightsORM | None] = relationship(
        back_populates="meeting", lazy="raise", passive_deletes=True
    )


class TranscriptSegmentORM(Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (
        UniqueConstraint("meeting_id", "sequence", name="uq_transcript_segments_meeting_sequence"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    meeting_id: Mapped[str] = mapped_column(String, ForeignKey("meetings.id", ondelete="CASCADE"))
    # Per-meeting position of the segment; transcripts are ordered by it.
    sequence: Mapped[int] = mapped_column(Integer)
    speaker: Mapped[str] = mapped_column(String(100))
    text: Mapped[str] = mapped_column(Text)
    # Seconds since the meeting started.
    timestamp: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    is_final: Mapped[bool] = mapped_column(Boolean, default=True)

    meeting: Mapped[MeetingORM] = relationship(back_populates="segments", lazy="raise")


class MeetingInsightsORM(Base):
    __tablename__ = "meeting_insights"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    meeting_id: Mapped[str] = mapped_column(
        String, ForeignKey("meetings.id", ondelete="CASCADE"), unique=True
    )
    summary: Mapped[str] = mapped_column(Text)
    action_items: Mapped[list[str]] = mapped_column(JSON)
    decisions: Mapped[list[str]] = mapped_column(JSON)
    questions_raised: Mapped[list[str]] = mapped_column(JSON)
    follow_up_email: Mapped[str] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    meeting: Mapped[MeetingORM] = relationship(back_populates="insights", lazy="raise")
