"""Streaming speech-to-text through Deepgram's live WebSocket API."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections import Counter
from collections.abc import AsyncIterator
from typing import Any

import websockets
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus, InvalidURI

from app.services.transcription import TranscriptionUnavailableError, TranscriptResult

logger = logging.getLogger(__name__)

# No encoding/sample_rate/channels: Deepgram detects them from the WebM or Ogg
# container that MediaRecorder produces.
LISTEN_URL = (
    "wss://api.deepgram.com/v1/listen"
    "?model=nova-2"
    "&language=en-US"
    "&punctuate=true"
    "&interim_results=true"
    "&utterance_end_ms=1000"
    "&vad_events=true"
    "&diarize=true"
)
CONNECT_TIMEOUT_SECONDS = 10.0
CLOSE_TIMEOUT_SECONDS = 2.0
# Deepgram closes a stream that receives neither audio nor a KeepAlive for
# about 10 seconds, e.g. while the user has paused the microphone.
KEEPALIVE_INTERVAL_SECONDS = 5.0

_KEEPALIVE = json.dumps({"type": "KeepAlive"})
_CLOSE_STREAM = json.dumps({"type": "CloseStream"})


def parse_result(message: dict[str, Any]) -> TranscriptResult | None:
    """Convert a Deepgram ``Results`` message; other message types return None."""
    if message.get("type") != "Results":
        return None
    alternatives = (message.get("channel") or {}).get("alternatives") or []
    if not alternatives:
        return None
    best = alternatives[0]
    text = (best.get("transcript") or "").strip()
    if not text:
        return None
    is_final = bool(message.get("is_final"))
    return TranscriptResult(
        text=text,
        speaker=_speaker_label(best.get("words") or []) if is_final else "",
        start=float(message.get("start") or 0.0),
        confidence=round(float(best.get("confidence") or 0.0), 3),
        is_final=is_final,
    )


def _speaker_label(words: list[dict[str, Any]]) -> str:
    """Label a segment with the diarized speaker who said most of its words."""
    speakers = Counter(word["speaker"] for word in words if isinstance(word.get("speaker"), int))
    if not speakers:
        return "Speaker 1"
    speaker, _ = speakers.most_common(1)[0]
    return f"Speaker {speaker + 1}"


class DeepgramStreamer:
    """One Deepgram live-transcription stream.

    ``connect()`` is called when the first audio frame arrives, because that
    frame carries the container header Deepgram needs. While no audio flows, a
    KeepAlive is sent every ``KEEPALIVE_INTERVAL_SECONDS``. ``finish()`` sends
    CloseStream; Deepgram then returns the remaining final results and closes
    the socket, which ends ``results()``.
    """

    def __init__(
        self,
        api_key: str,
        *,
        url: str = LISTEN_URL,
        keepalive_interval: float = KEEPALIVE_INTERVAL_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._url = url
        self._keepalive_interval = keepalive_interval
        self._ws: ClientConnection | None = None
        # None marks the end of the stream.
        self._results: asyncio.Queue[TranscriptResult | None] = asyncio.Queue()
        self._tasks: list[asyncio.Task[None]] = []
        self._last_sent = 0.0
        self._finishing = False
        self._failure: str | None = None

    async def connect(self) -> None:
        if not self._api_key:
            raise TranscriptionUnavailableError("DEEPGRAM_API_KEY is not set")
        try:
            ws = await websockets.connect(
                self._url,
                additional_headers={"Authorization": f"Token {self._api_key}"},
                open_timeout=CONNECT_TIMEOUT_SECONDS,
                close_timeout=CLOSE_TIMEOUT_SECONDS,
            )
        except InvalidStatus as error:
            raise TranscriptionUnavailableError(
                f"Deepgram refused the connection (HTTP {error.response.status_code})"
            ) from error
        except (OSError, TimeoutError, InvalidHandshake, InvalidURI) as error:
            raise TranscriptionUnavailableError(
                f"could not connect to Deepgram ({type(error).__name__})"
            ) from error
        self._ws = ws
        self._last_sent = time.monotonic()
        self._tasks = [
            asyncio.create_task(self._receive_loop(ws), name="deepgram-receive"),
            asyncio.create_task(self._keepalive_loop(ws), name="deepgram-keepalive"),
        ]
        request_id = ws.response.headers.get("dg-request-id") if ws.response else None
        logger.info("Deepgram stream opened (request id %s)", request_id or "unknown")

    async def send_audio(self, chunk: bytes) -> None:
        if self._ws is None or self._finishing:
            return
        try:
            await self._ws.send(chunk)
        except ConnectionClosed:
            return  # reported by the receive loop
        self._last_sent = time.monotonic()

    async def finish(self) -> None:
        if self._ws is None or self._finishing:
            return
        self._finishing = True
        with contextlib.suppress(ConnectionClosed):
            await self._ws.send(_CLOSE_STREAM)

    async def results(self) -> AsyncIterator[TranscriptResult]:
        while (result := await self._results.get()) is not None:
            yield result
        if self._failure is not None:
            raise TranscriptionUnavailableError(self._failure)

    async def aclose(self) -> None:
        self._finishing = True
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if self._ws is not None:
            await self._ws.close()

    async def _receive_loop(self, ws: ClientConnection) -> None:
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue
                message = json.loads(raw)
                if not isinstance(message, dict):
                    continue
                result = parse_result(message)
                if result is not None:
                    self._results.put_nowait(result)
                elif message.get("type") == "Error":
                    logger.warning("Deepgram reported an error: %s", message)
            if not self._finishing:
                self._failure = f"Deepgram closed the stream (code {ws.close_code})"
        except ConnectionClosed as error:
            if not self._finishing:
                self._failure = f"Deepgram connection lost: {error}"
        except ValueError as error:
            self._failure = f"unreadable message from Deepgram ({error})"
        finally:
            if self._failure is not None:
                logger.warning("Deepgram stream ended unexpectedly: %s", self._failure)
            self._results.put_nowait(None)

    async def _keepalive_loop(self, ws: ClientConnection) -> None:
        with contextlib.suppress(ConnectionClosed):
            while not self._finishing:
                idle = time.monotonic() - self._last_sent
                if idle < self._keepalive_interval:
                    await asyncio.sleep(self._keepalive_interval - idle)
                    continue
                await ws.send(_KEEPALIVE)
                self._last_sent = time.monotonic()
