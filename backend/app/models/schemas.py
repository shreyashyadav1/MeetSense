from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import uuid


class Meeting(BaseModel):
    id: str
    title: str
    status: str  # "active" | "ended"
    started_at: datetime
    ended_at: Optional[datetime] = None


class CreateMeetingRequest(BaseModel):
    title: str


class TranscriptSegment(BaseModel):
    id: str
    meeting_id: str
    speaker: str
    text: str
    timestamp: float  # seconds from meeting start
    confidence: float


class WebSocketMessage(BaseModel):
    type: str  # "transcript" | "status" | "error"
    data: dict
