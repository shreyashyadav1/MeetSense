"""Message types for the live stream at ``/ws/meetings/{meeting_id}/stream``.

Client → server
    * binary frames: audio from MediaRecorder (WebM/Opus or Ogg). The client
      starts a fresh recorder per connection, so the first frame carries the
      container header, and only sends audio after ``connected``.
    * ``{"type": "ping"}`` → answered with ``{"type": "pong"}``.
    * ``{"type": "stop"}`` → the server flushes transcription, sends
      ``status: stopped`` and closes with 1000.

Server → client: the models below, serialized with ``model_dump_json()``.
Every ``error`` message is followed by a close frame with the code from
``ERROR_POLICIES``. ``transcript`` messages carry ``emitted_at`` (server wall
clock, seconds since the Unix epoch) so a client can measure delivery latency;
it is additive and ignored by clients that don't read it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

from app.core.config import TranscriptionMode
from app.models.schemas import TranscriptSegment


class ErrorCode(StrEnum):
    MEETING_NOT_FOUND = "meeting_not_found"
    MEETING_ENDED = "meeting_ended"
    ORIGIN_NOT_ALLOWED = "origin_not_allowed"
    TOO_MANY_CONNECTIONS = "too_many_connections"
    SESSION_TIME_LIMIT = "session_time_limit"
    TRANSCRIPTION_UNAVAILABLE = "transcription_unavailable"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True, slots=True)
class ErrorPolicy:
    close_code: int
    retryable: bool
    message: str


ERROR_POLICIES: dict[ErrorCode, ErrorPolicy] = {
    ErrorCode.MEETING_NOT_FOUND: ErrorPolicy(1008, False, "Meeting not found."),
    ErrorCode.MEETING_ENDED: ErrorPolicy(1008, False, "This meeting has already ended."),
    ErrorCode.ORIGIN_NOT_ALLOWED: ErrorPolicy(
        1008, False, "This site is not allowed to open a live stream."
    ),
    ErrorCode.TOO_MANY_CONNECTIONS: ErrorPolicy(
        1013, True, "Too many live streams are open from your network. Close one and retry."
    ),
    ErrorCode.SESSION_TIME_LIMIT: ErrorPolicy(
        1008, False, "This live session reached its time limit."
    ),
    ErrorCode.TRANSCRIPTION_UNAVAILABLE: ErrorPolicy(
        1011, True, "Live transcription is temporarily unavailable."
    ),
    ErrorCode.INTERNAL_ERROR: ErrorPolicy(1011, True, "Something went wrong on our side."),
}


# --- Server → client --------------------------------------------------------


class ConnectedMessage(BaseModel):
    type: Literal["status"] = "status"
    status: Literal["connected"] = "connected"
    mode: TranscriptionMode


class StatusMessage(BaseModel):
    type: Literal["status"] = "status"
    status: Literal["stopped", "stream_complete"]


class TranscriptMessage(TranscriptSegment):
    type: Literal["transcript"] = "transcript"
    emitted_at: float = Field(default_factory=time.time)

    @classmethod
    def from_segment(cls, segment: TranscriptSegment) -> TranscriptMessage:
        return cls.model_validate(segment.model_dump())


class PongMessage(BaseModel):
    type: Literal["pong"] = "pong"


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    code: ErrorCode
    message: str
    retryable: bool

    @classmethod
    def for_code(cls, code: ErrorCode) -> ErrorMessage:
        policy = ERROR_POLICIES[code]
        return cls(code=code, message=policy.message, retryable=policy.retryable)

    @property
    def close_code(self) -> int:
        return ERROR_POLICIES[self.code].close_code


ServerMessage = ConnectedMessage | StatusMessage | TranscriptMessage | PongMessage | ErrorMessage


# --- Client → server --------------------------------------------------------


class PingRequest(BaseModel):
    type: Literal["ping"]


class StopRequest(BaseModel):
    type: Literal["stop"]


ClientMessage = Annotated[PingRequest | StopRequest, Field(discriminator="type")]
client_message_adapter: TypeAdapter[PingRequest | StopRequest] = TypeAdapter(ClientMessage)
