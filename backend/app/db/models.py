from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MeetingORM(Base):
    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20))  # "active" | "ended"
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    segments: Mapped[list[TranscriptSegmentORM]] = relationship(
        back_populates="meeting",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    insights: Mapped[Optional[MeetingInsightsORM]] = relationship(
        back_populates="meeting",
        uselist=False,
        lazy="selectin",
        cascade="all, delete-orphan",
    )


class TranscriptSegmentORM(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    meeting_id: Mapped[str] = mapped_column(
        String, ForeignKey("meetings.id", ondelete="CASCADE")
    )
    speaker: Mapped[str] = mapped_column(String(100))
    text: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    is_final: Mapped[bool] = mapped_column(Boolean, default=True)

    meeting: Mapped[MeetingORM] = relationship(back_populates="segments")


class MeetingInsightsORM(Base):
    __tablename__ = "meeting_insights"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    meeting_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("meetings.id", ondelete="CASCADE"),
        unique=True,
    )
    summary: Mapped[str] = mapped_column(Text)
    action_items: Mapped[list] = mapped_column(JSON)
    decisions: Mapped[list] = mapped_column(JSON)
    questions_raised: Mapped[list] = mapped_column(JSON)
    follow_up_email: Mapped[str] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    meeting: Mapped[MeetingORM] = relationship(back_populates="insights")
