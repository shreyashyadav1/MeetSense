"""DeepgramStreamer against a local stand-in for Deepgram's live API."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from http import HTTPStatus

import pytest
from websockets.asyncio.server import Request, Response, ServerConnection, serve

from app.services.deepgram_service import DeepgramStreamer, parse_result
from app.services.transcription import TranscriptionUnavailableError

Handler = Callable[[ServerConnection], Awaitable[None]]


def results_message(
    text: str, *, is_final: bool, start: float = 0.0, speakers: tuple[int, ...] = ()
) -> str:
    words = [{"word": w, "speaker": s} for w, s in zip(text.split(), speakers, strict=False)]
    alternative = {"transcript": text, "confidence": 0.93, "words": words}
    return json.dumps(
        {
            "type": "Results",
            "is_final": is_final,
            "start": start,
            "channel": {"alternatives": [alternative]},
        }
    )


@asynccontextmanager
async def fake_deepgram(handler: Handler, *, api_key: str = "test-key") -> AsyncIterator[str]:
    def authenticate(connection: ServerConnection, request: Request) -> Response | None:
        if request.headers.get("Authorization") != f"Token {api_key}":
            return connection.respond(HTTPStatus.UNAUTHORIZED, "Invalid credentials\n")
        return None

    async with serve(handler, "127.0.0.1", 0, process_request=authenticate) as server:
        port = server.sockets[0].getsockname()[1]
        yield f"ws://127.0.0.1:{port}/v1/listen"


async def test_streams_results_keeps_alive_and_flushes_on_close_stream() -> None:
    received: list[str | bytes] = []

    async def handler(ws: ServerConnection) -> None:
        async for message in ws:
            received.append(message)
            if isinstance(message, bytes):
                await ws.send(results_message("hello", is_final=False))
            elif json.loads(message)["type"] == "CloseStream":
                await ws.send(
                    results_message(
                        "hello there team", is_final=True, start=0.5, speakers=(1, 1, 0)
                    )
                )
                await ws.close()

    async with fake_deepgram(handler) as url:
        streamer = DeepgramStreamer("test-key", url=url, keepalive_interval=0.05)
        await streamer.connect()
        await streamer.send_audio(b"\x1a\x45\xdf\xa3 webm header")
        await asyncio.sleep(0.2)  # no audio: KeepAlive messages keep the stream open
        await streamer.finish()
        results = [result async for result in streamer.results()]
        await streamer.aclose()

    assert [(r.text, r.is_final) for r in results] == [
        ("hello", False),
        ("hello there team", True),
    ]
    assert results[1].speaker == "Speaker 2"
    assert results[1].start == 0.5
    assert received[0] == b"\x1a\x45\xdf\xa3 webm header"
    assert json.dumps({"type": "KeepAlive"}) in received
    assert received[-1] == json.dumps({"type": "CloseStream"})


async def test_rejected_api_key_is_reported_as_unavailable() -> None:
    async def handler(ws: ServerConnection) -> None:
        await ws.wait_closed()

    async with fake_deepgram(handler) as url:
        streamer = DeepgramStreamer("wrong-key", url=url)
        with pytest.raises(TranscriptionUnavailableError, match="HTTP 401"):
            await streamer.connect()


async def test_unreachable_deepgram_is_reported_as_unavailable(unused_tcp_port: int) -> None:
    streamer = DeepgramStreamer("test-key", url=f"ws://127.0.0.1:{unused_tcp_port}/v1/listen")
    with pytest.raises(TranscriptionUnavailableError, match="could not connect"):
        await streamer.connect()


async def test_missing_api_key_is_reported_as_unavailable() -> None:
    with pytest.raises(TranscriptionUnavailableError, match="DEEPGRAM_API_KEY"):
        await DeepgramStreamer("").connect()


async def test_unexpected_close_ends_results_with_an_error() -> None:
    async def handler(ws: ServerConnection) -> None:
        await ws.recv()
        await ws.send(results_message("partial", is_final=True))
        await ws.close(code=1011, reason="NET-0001")

    async with fake_deepgram(handler) as url:
        streamer = DeepgramStreamer("test-key", url=url)
        await streamer.connect()
        await streamer.send_audio(b"audio")
        seen = []
        with pytest.raises(TranscriptionUnavailableError, match="1011"):
            async for result in streamer.results():
                seen.append(result.text)
        await streamer.aclose()
    assert seen == ["partial"]


def test_parse_result_ignores_other_messages_and_empty_transcripts() -> None:
    assert parse_result({"type": "Metadata", "request_id": "abc"}) is None
    assert parse_result({"type": "UtteranceEnd"}) is None
    assert parse_result(json.loads(results_message("   ", is_final=True))) is None
    interim = parse_result(json.loads(results_message("so we", is_final=False, speakers=(2, 2))))
    assert interim is not None
    assert (interim.speaker, interim.is_final) == ("", False)
    final = parse_result(json.loads(results_message("no diarization", is_final=True)))
    assert final is not None
    assert final.speaker == "Speaker 1"
