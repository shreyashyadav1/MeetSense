from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

MeetingStatus = Literal["active", "ended"]

TITLE_MAX_LENGTH = 120
EXPORT_MAX_ITEMS = 20


class Meeting(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    status: MeetingStatus
    started_at: datetime
    ended_at: datetime | None = None


class CreateMeetingRequest(BaseModel):
    title: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=TITLE_MAX_LENGTH),
    ]


class TranscriptSegment(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    meeting_id: str
    sequence: int = Field(
        description=(
            "Per-meeting order of final segments (1, 2, 3, ...), stable across reconnects. "
            "An interim segment carries the number its final version will get."
        )
    )
    speaker: str
    text: str
    timestamp: float = Field(description="Seconds since the meeting started.")
    confidence: float
    is_final: bool = True


class MeetingInsights(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    meeting_id: str
    summary: str
    action_items: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    questions_raised: list[str] = Field(default_factory=list)
    follow_up_email: str
    generated_at: datetime


class ExportActionItemsRequest(BaseModel):
    items: list[Annotated[int, Field(ge=0)]] = Field(
        min_length=1,
        max_length=EXPORT_MAX_ITEMS,
        description="Indexes into the meeting's action_items: the ones approved for export.",
    )


class ExportedIssue(BaseModel):
    action_item: str
    number: int
    url: str
    created: bool = Field(description="False when an earlier export already filed this item.")


class ExportActionItemsResponse(BaseModel):
    repository: str
    issues: list[ExportedIssue]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["postgres", "memory", "unavailable"]
    redis: Literal["connected", "unavailable"]
    transcription: Literal["deepgram", "mock"]
    ai: Literal["configured", "not_configured"]
