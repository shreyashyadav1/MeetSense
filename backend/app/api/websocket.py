"""WebSocket endpoint for live transcription (protocol: ``app/models/ws.py``)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from starlette.types import Message

from app.core.config import settings
from app.models.schemas import Meeting
from app.models.ws import (
    ConnectedMessage,
    ErrorCode,
    ErrorMessage,
    PingRequest,
    PongMessage,
    StatusMessage,
    client_message_adapter,
)
from app.services.redis_service import get_redis, redis_available
from app.services.smart_meeting_store import smart_meeting_store
from app.services.transcription import TranscriptionUnavailableError
from app.services.transcription_hub import (
    CloseRequest,
    MeetingSession,
    Subscriber,
    transcription_hub,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# How long to wait for queued messages (and the close frame) to reach the client.
SEND_DRAIN_TIMEOUT_SECONDS = 2.0

# Open sockets per client IP, for this process.
_open_connections: Counter[str] = Counter()


async def _redis_available() -> bool:
    return await redis_available()


def _origin_allowed(origin: str | None) -> bool:
    # Browsers always send Origin on WebSocket handshakes; the check exists to
    # stop other sites from opening streams with a visitor's browser. Clients
    # without an Origin header are not browsers and could forge one anyway.
    if origin is None:
        return True
    allowed = settings.allowed_origins
    return "*" in allowed or origin.rstrip("/") in allowed


async def _reject(websocket: WebSocket, code: ErrorCode) -> None:
    error = ErrorMessage.for_code(code)
    with contextlib.suppress(WebSocketDisconnect, RuntimeError):
        await websocket.send_text(error.model_dump_json())
        await websocket.close(code=error.close_code)


@router.websocket("/meetings/{meeting_id}/stream")
async def meeting_stream(websocket: WebSocket, meeting_id: str) -> None:
    await websocket.accept()

    origin = websocket.headers.get("origin")
    if not _origin_allowed(origin):
        logger.warning("Rejected stream for meeting %s from origin %r", meeting_id, origin)
        await _reject(websocket, ErrorCode.ORIGIN_NOT_ALLOWED)
        return

    client_ip = websocket.client.host if websocket.client else "unknown"
    if _open_connections[client_ip] >= settings.ws_max_connections_per_ip:
        logger.warning(
            "Rejected stream for meeting %s: too many sockets from %s", meeting_id, client_ip
        )
        await _reject(websocket, ErrorCode.TOO_MANY_CONNECTIONS)
        return

    _open_connections[client_ip] += 1
    try:
        await _serve(websocket, meeting_id, client_ip)
    finally:
        _open_connections[client_ip] -= 1
        if _open_connections[client_ip] <= 0:
            del _open_connections[client_ip]


async def _serve(websocket: WebSocket, meeting_id: str, client_ip: str) -> None:
    try:
        meeting = await smart_meeting_store.get_meeting(meeting_id)
    except Exception:
        logger.exception("Could not load meeting %s for streaming", meeting_id)
        await _reject(websocket, ErrorCode.INTERNAL_ERROR)
        return
    if meeting is None:
        await _reject(websocket, ErrorCode.MEETING_NOT_FOUND)
        return
    if meeting.status == "ended":
        await _reject(websocket, ErrorCode.MEETING_ENDED)
        return
    await StreamConnection(websocket, meeting, client_ip).run()


@dataclass(frozen=True, slots=True)
class _Ending:
    """Why the receive loop stopped."""

    reason: Literal["disconnected", "stop", "error"]
    error: ErrorCode | None = None


_DISCONNECTED = _Ending("disconnected")
_STOP = _Ending("stop")


class StreamConnection:
    """One client socket: reads audio and control frames, writes session messages.

    Everything sent to the client goes through the subscriber queue and a single
    sender task, so messages keep their order and never race on the socket.
    """

    def __init__(self, websocket: WebSocket, meeting: Meeting, client_ip: str) -> None:
        self._ws = websocket
        self._meeting = meeting
        self._mode = settings.transcription_mode
        self._subscriber = Subscriber(label=client_ip)
        self._audio_frames = 0

    async def run(self) -> None:
        self._subscriber.send(ConnectedMessage(mode=self._mode))
        sender = asyncio.create_task(self._send_loop(), name=f"ws-send-{self._meeting.id}")
        redis = get_redis() if await _redis_available() else None
        session = await transcription_hub.join(self._meeting, self._subscriber, redis=redis)
        try:
            try:
                if self._mode == "mock":
                    await session.start_source(self._subscriber, "mock")
                ending = await self._receive_loop(session)
            except Exception:
                logger.exception("Stream for meeting %s failed", self._meeting.id)
                ending = _Ending("error", ErrorCode.INTERNAL_ERROR)
            await self._release_source(session, ending)
            if ending.reason == "stop":
                self._finish(StatusMessage(status="stopped"), close_code=1000)
            elif ending.error is not None:
                error = ErrorMessage.for_code(ending.error)
                self._finish(error, close_code=error.close_code)
            if ending.reason != "disconnected":
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(sender), SEND_DRAIN_TIMEOUT_SECONDS)
        finally:
            sender.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sender
            await transcription_hub.leave(session, self._subscriber)

    def _finish(self, message: StatusMessage | ErrorMessage, *, close_code: int) -> None:
        self._subscriber.send(message)
        self._subscriber.close(close_code)

    async def _release_source(self, session: MeetingSession, ending: _Ending) -> None:
        """Flush this connection's source before the socket goes away."""
        if not session.owns_source(self._subscriber):
            return
        if ending.reason != "stop" and session.hand_over_source(self._subscriber):
            return
        await session.stop_source(self._subscriber)

    async def _receive_loop(self, session: MeetingSession) -> _Ending:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + settings.session_max_seconds
        while True:
            try:
                message = await asyncio.wait_for(self._ws.receive(), deadline - loop.time())
            except TimeoutError:
                logger.info(
                    "Stream for meeting %s reached the session time limit", self._meeting.id
                )
                return _Ending("error", ErrorCode.SESSION_TIME_LIMIT)
            # receive() reports a closed socket as a message; it does not raise.
            if message["type"] == "websocket.disconnect":
                return _DISCONNECTED
            if (ending := await self._handle_frame(session, message)) is not None:
                return ending

    async def _handle_frame(self, session: MeetingSession, message: Message) -> _Ending | None:
        if (chunk := message.get("bytes")) is not None:
            return await self._handle_audio(session, chunk)
        if (text := message.get("text")) is not None:
            return self._handle_text(text)
        return None

    async def _handle_audio(self, session: MeetingSession, chunk: bytes) -> _Ending | None:
        self._audio_frames += 1
        if self._mode != "deepgram" or not chunk:
            return None
        if session.owns_source(self._subscriber):
            await session.send_audio(self._subscriber, chunk)
            return None
        # Only a connection's first frame carries the container header, so a
        # Deepgram stream can be opened from nowhere else.
        if self._audio_frames > 1 or session.has_source:
            if self._audio_frames == 1:
                logger.info(
                    "Ignoring audio from a second client on meeting %s; another client is live",
                    self._meeting.id,
                )
            return None
        try:
            await session.start_source(self._subscriber, "deepgram")
        except TranscriptionUnavailableError as error:
            logger.warning("Transcription unavailable for meeting %s: %s", self._meeting.id, error)
            return _Ending("error", ErrorCode.TRANSCRIPTION_UNAVAILABLE)
        await session.send_audio(self._subscriber, chunk)
        return None

    def _handle_text(self, text: str) -> _Ending | None:
        try:
            request = client_message_adapter.validate_json(text)
        except ValidationError:
            logger.debug("Ignoring unrecognized client message on meeting %s", self._meeting.id)
            return None
        if isinstance(request, PingRequest):
            self._subscriber.send(PongMessage())
            return None
        return _STOP

    async def _send_loop(self) -> None:
        while True:
            item = await self._subscriber.next()
            try:
                if isinstance(item, CloseRequest):
                    await self._ws.close(code=item.code)
                    return
                await self._ws.send_text(item)
            except (WebSocketDisconnect, RuntimeError):
                return  # the client is gone; the receive loop sees the disconnect
