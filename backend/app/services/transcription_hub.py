"""Live transcription sessions: one per meeting, one transcription source per session.

The first WebSocket for a meeting creates its ``MeetingSession``; later sockets
only subscribe. A session runs at most one source at a time - the scripted mock,
or a Deepgram stream opened by the first audio frame of the socket that owns it
- numbers final segments with a per-meeting sequence, converts timestamps to
seconds since the meeting started, stores final segments and fans every message
out to all subscribers.

When Redis is available a session also relays its messages through
``meeting:{id}:segments``, so viewers connected to other backend instances see
them. Source ownership is tracked per process: live audio for a meeting has to
reach a single instance (true for the single Railway service).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from app.core.config import TranscriptionMode, settings
from app.models.schemas import Meeting, TranscriptSegment
from app.models.ws import ErrorCode, ErrorMessage, ServerMessage, StatusMessage, TranscriptMessage
from app.services import deepgram_service, mock_transcription
from app.services.redis_service import segment_channel
from app.services.smart_meeting_store import SmartMeetingStore, smart_meeting_store
from app.services.transcription import (
    TranscriptionSource,
    TranscriptionUnavailableError,
    TranscriptResult,
)

logger = logging.getLogger(__name__)

# How long stop/disconnect waits for a source to deliver its last results.
FLUSH_TIMEOUT_SECONDS = 3.0
REDIS_TIMEOUT_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class CloseRequest:
    code: int


class Subscriber:
    """Outbound queue of one WebSocket connection; drained by its sender task."""

    def __init__(self, label: str) -> None:
        self.label = label
        self._queue: asyncio.Queue[str | CloseRequest] = asyncio.Queue()

    def send(self, message: ServerMessage) -> None:
        self._queue.put_nowait(message.model_dump_json())

    def send_raw(self, payload: str) -> None:
        self._queue.put_nowait(payload)

    def close(self, code: int) -> None:
        self._queue.put_nowait(CloseRequest(code))

    async def next(self) -> str | CloseRequest:
        return await self._queue.get()


class MeetingSession:
    def __init__(self, hub: TranscriptionHub, meeting: Meeting) -> None:
        self.meeting = meeting
        self.channel = segment_channel(meeting.id)
        self._hub = hub
        self._subscribers: list[Subscriber] = []
        self._owner: Subscriber | None = None
        self._source: TranscriptionSource | None = None
        self._source_mode: TranscriptionMode | None = None
        self._pump: asyncio.Task[None] | None = None
        self._last_sequence = 0
        self._sequence_loaded = False
        self._redis: Redis | None = None
        self._pubsub: PubSub | None = None
        self._relay: asyncio.Task[None] | None = None

    # --- Subscribers -----------------------------------------------------------

    def add(self, subscriber: Subscriber) -> None:
        self._subscribers.append(subscriber)

    def remove(self, subscriber: Subscriber) -> None:
        with contextlib.suppress(ValueError):
            self._subscribers.remove(subscriber)

    @property
    def is_idle(self) -> bool:
        return not self._subscribers and self._owner is None

    # --- Transcription source --------------------------------------------------

    @property
    def has_source(self) -> bool:
        return self._owner is not None

    def owns_source(self, subscriber: Subscriber) -> bool:
        return self._owner is subscriber

    async def start_source(self, owner: Subscriber, mode: TranscriptionMode) -> None:
        """Start the meeting's transcription source, owned by ``owner``.

        Does nothing if a source is already running. Raises
        ``TranscriptionUnavailableError`` if Deepgram cannot be reached.
        """
        if self._owner is not None:
            return
        self._owner = owner  # claim first, so concurrent callers back off
        try:
            if not self._sequence_loaded:
                self._last_sequence = await self._hub.store.get_last_sequence(self.meeting.id)
                self._sequence_loaded = True
            source = await self._open_source(mode)
        except BaseException:
            self._owner = None
            raise
        if source is None:
            self._owner = None
            owner.send(StatusMessage(status="stream_complete"))
            return
        offset = max(0.0, (datetime.now(UTC) - self.meeting.started_at).total_seconds())
        self._source, self._source_mode = source, mode
        self._pump = asyncio.create_task(
            self._run_source(source, offset), name=f"transcription-{self.meeting.id}"
        )

    async def _open_source(self, mode: TranscriptionMode) -> TranscriptionSource | None:
        if mode == "mock":
            # Final segments so far = script lines already delivered.
            mock = mock_transcription.MockTranscriptionSource(start_index=self._last_sequence)
            return None if mock.exhausted else mock
        streamer = deepgram_service.DeepgramStreamer(settings.deepgram_api_key)
        await streamer.connect()
        return streamer

    async def send_audio(self, subscriber: Subscriber, chunk: bytes) -> None:
        if self._owner is subscriber and self._source is not None:
            await self._source.send_audio(chunk)

    async def stop_source(self, owner: Subscriber) -> None:
        """Flush and stop ``owner``'s source.

        Returns once the source's last results are published and stored, or
        after ``FLUSH_TIMEOUT_SECONDS``, whichever comes first.
        """
        pump, source = self._pump, self._source
        if self._owner is not owner or pump is None or source is None:
            return
        with contextlib.suppress(Exception):
            await source.finish()
        try:
            await asyncio.wait_for(asyncio.shield(pump), FLUSH_TIMEOUT_SECONDS)
        except TimeoutError:
            logger.warning(
                "Transcription for meeting %s did not flush within %.0fs; stopping it",
                self.meeting.id,
                FLUSH_TIMEOUT_SECONDS,
            )
            pump.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump
            await self.publish(StatusMessage(status="stream_complete"))

    def hand_over_source(self, owner: Subscriber) -> bool:
        """Let another viewer inherit a running mock script when its owner leaves.

        Deepgram streams can't be handed over: their audio comes from the owner.
        """
        if self._owner is not owner or self._source_mode != "mock":
            return False
        successor = next((s for s in self._subscribers if s is not owner), None)
        if successor is None:
            return False
        self._owner = successor
        return True

    async def _run_source(self, source: TranscriptionSource, offset: float) -> None:
        try:
            failure = await self._consume(source, offset)
            if failure is None:
                await self.publish(StatusMessage(status="stream_complete"))
            elif (owner := self._owner) is not None:
                error = ErrorMessage.for_code(failure)
                owner.send(error)
                owner.close(error.close_code)
        finally:
            with contextlib.suppress(Exception):
                await source.aclose()
            if self._source is source:
                self._owner = self._source = self._source_mode = self._pump = None

    async def _consume(self, source: TranscriptionSource, offset: float) -> ErrorCode | None:
        try:
            async for result in source.results():
                await self._publish_result(result, offset)
        except TranscriptionUnavailableError as error:
            logger.warning("Transcription for meeting %s stopped: %s", self.meeting.id, error)
            return ErrorCode.TRANSCRIPTION_UNAVAILABLE
        except Exception:
            logger.exception("Transcription for meeting %s failed", self.meeting.id)
            return ErrorCode.INTERNAL_ERROR
        return None

    async def _publish_result(self, result: TranscriptResult, offset: float) -> None:
        if result.is_final:
            self._last_sequence += 1
        segment = TranscriptSegment(
            id=str(uuid.uuid4()) if result.is_final else f"interim-{self.meeting.id}",
            meeting_id=self.meeting.id,
            # An interim result previews the segment that will take the next number.
            sequence=self._last_sequence if result.is_final else self._last_sequence + 1,
            speaker=result.speaker,
            text=result.text,
            timestamp=round(offset + result.start, 2),
            confidence=result.confidence,
            is_final=result.is_final,
        )
        await self.publish(TranscriptMessage.from_segment(segment))
        if segment.is_final:
            try:
                await self._hub.store.add_segment(segment)
            except Exception:
                logger.exception(
                    "Could not store segment %d of meeting %s", segment.sequence, self.meeting.id
                )

    # --- Fan-out -----------------------------------------------------------------

    async def publish(self, message: ServerMessage) -> None:
        payload = message.model_dump_json()
        self._deliver(payload)
        if self._redis is None:
            return
        envelope = json.dumps({"origin": self._hub.instance_id, "payload": payload})
        try:
            await asyncio.wait_for(
                self._redis.publish(self.channel, envelope), REDIS_TIMEOUT_SECONDS
            )
        except Exception as error:
            logger.warning(
                "Redis publish for meeting %s failed (%s); relaying to other instances stopped",
                self.meeting.id,
                error,
            )
            await self._stop_relay()

    def _deliver(self, payload: str) -> None:
        for subscriber in tuple(self._subscribers):
            subscriber.send_raw(payload)

    async def start_relay(self, redis: Redis) -> None:
        pubsub = redis.pubsub(ignore_subscribe_messages=True)
        try:
            async with asyncio.timeout(REDIS_TIMEOUT_SECONDS):
                await pubsub.subscribe(self.channel)
                # Wait for the confirmation, so the relay is live once join() returns.
                await pubsub.get_message(ignore_subscribe_messages=False, timeout=None)
        except Exception as error:
            logger.warning("Could not subscribe to %s (%s); relay disabled", self.channel, error)
            with contextlib.suppress(Exception):
                await pubsub.aclose()
            return
        self._redis, self._pubsub = redis, pubsub
        self._relay = asyncio.create_task(self._relay_loop(pubsub), name=f"relay-{self.meeting.id}")

    async def _relay_loop(self, pubsub: PubSub) -> None:
        """Deliver messages that other instances published for this meeting."""
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    envelope = json.loads(message["data"])
                    origin, payload = envelope["origin"], envelope["payload"]
                except (ValueError, KeyError, TypeError):
                    logger.warning("Ignoring malformed message on %s", self.channel)
                    continue
                if origin != self._hub.instance_id and isinstance(payload, str):
                    self._deliver(payload)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("Redis relay for meeting %s stopped (%s)", self.meeting.id, error)

    async def _stop_relay(self) -> None:
        relay, pubsub = self._relay, self._pubsub
        self._redis = self._pubsub = self._relay = None
        if relay is not None and relay is not asyncio.current_task():
            relay.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await relay
        if pubsub is not None:
            with contextlib.suppress(Exception):
                await pubsub.aclose()

    async def close(self) -> None:
        """Abort the running source (if any) and stop relaying."""
        if (pump := self._pump) is not None:
            pump.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump
        await self._stop_relay()


class TranscriptionHub:
    """Registry of the live sessions in this process."""

    def __init__(self, store: SmartMeetingStore, *, instance_id: str | None = None) -> None:
        self.store = store
        self.instance_id = instance_id or uuid.uuid4().hex
        self._sessions: dict[str, MeetingSession] = {}

    def session(self, meeting_id: str) -> MeetingSession | None:
        return self._sessions.get(meeting_id)

    async def join(
        self, meeting: Meeting, subscriber: Subscriber, *, redis: Redis | None = None
    ) -> MeetingSession:
        session = self._sessions.get(meeting.id)
        if session is not None:
            session.add(subscriber)
            return session
        session = MeetingSession(self, meeting)
        session.add(subscriber)
        self._sessions[meeting.id] = session
        if redis is not None:
            await session.start_relay(redis)
        return session

    async def leave(self, session: MeetingSession, subscriber: Subscriber) -> None:
        if session.owns_source(subscriber):
            await session.stop_source(subscriber)
        session.remove(subscriber)
        if session.is_idle and self._sessions.get(session.meeting.id) is session:
            del self._sessions[session.meeting.id]
            await session.close()

    async def shutdown(self) -> None:
        sessions = list(self._sessions.values())
        self._sessions.clear()
        for session in sessions:
            await session.close()


transcription_hub = TranscriptionHub(smart_meeting_store)
