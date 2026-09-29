from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest
import websockets
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from app.core.config import settings
from app.services.mock_transcription import DIALOGUE
from tests.fakes import FakeDeepgram, ScriptedSource, final, interim

Message = dict[str, Any]

CONNECTED_MOCK = {"type": "status", "status": "connected", "mode": "mock"}
CONNECTED_DEEPGRAM = {"type": "status", "status": "connected", "mode": "deepgram"}
STREAM_COMPLETE = {"type": "status", "status": "stream_complete"}
STOPPED = {"type": "status", "status": "stopped"}


def create_meeting(client: TestClient) -> str:
    return client.post("/api/meetings", json={"title": "Standup"}).json()["id"]


def stream_url(meeting_id: str) -> str:
    return f"/ws/meetings/{meeting_id}/stream"


def receive_until(ws: WebSocketTestSession, predicate: Callable[[Message], bool]) -> list[Message]:
    messages = []
    for _ in range(1000):
        message = ws.receive_json()
        messages.append(message)
        if predicate(message):
            return messages
    raise AssertionError(f"expected message not received; got {messages[-5:]}")


def is_status(status: str) -> Callable[[Message], bool]:
    return lambda message: message.get("type") == "status" and message.get("status") == status


def assert_closed(ws: WebSocketTestSession, code: int) -> None:
    with pytest.raises(WebSocketDisconnect) as closed:
        ws.receive_json()
    assert closed.value.code == code


def wait_until(condition: Callable[[], bool], timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        time.sleep(0.01)


def error(code: str, message: str, retryable: bool) -> Message:
    return {"type": "error", "code": code, "message": message, "retryable": retryable}


# --- Mock mode ---------------------------------------------------------------------


def test_mock_stream_end_to_end(client: TestClient) -> None:
    meeting_id = create_meeting(client)
    with client.websocket_connect(stream_url(meeting_id)) as ws:
        assert ws.receive_json() == CONNECTED_MOCK
        messages = receive_until(ws, is_status("stream_complete"))
        ws.send_json({"type": "stop"})
        assert ws.receive_json() == STOPPED
        assert_closed(ws, 1000)

    transcripts = [m for m in messages if m["type"] == "transcript"]
    finals = [m for m in transcripts if m["is_final"]]
    assert [m["sequence"] for m in finals] == list(range(1, len(DIALOGUE) + 1))
    assert [(m["speaker"], m["text"]) for m in finals] == list(DIALOGUE)
    assert set(finals[0]) == {
        "type", "id", "meeting_id", "sequence", "speaker", "text", "timestamp", "confidence",
        "is_final",
    }  # fmt: skip

    # Interim results preview the segment that takes the next number.
    last_final = 0
    for message in transcripts:
        if message["is_final"]:
            last_final = message["sequence"]
        else:
            assert message["id"] == f"interim-{meeting_id}"
            assert message["sequence"] == last_final + 1

    stored = client.get(f"/api/meetings/{meeting_id}/transcript").json()
    assert [s["id"] for s in stored] == [m["id"] for m in finals]
    timestamps = [s["timestamp"] for s in stored]
    assert timestamps == sorted(timestamps)


def test_stop_flushes_the_source_before_confirming(
    client: TestClient, scripted_source: type[ScriptedSource]
) -> None:
    scripted_source.reset(final("First point."), interim("Second"))
    meeting_id = create_meeting(client)
    with client.websocket_connect(stream_url(meeting_id)) as ws:
        assert ws.receive_json() == CONNECTED_MOCK
        assert ws.receive_json()["text"] == "First point."
        assert ws.receive_json()["is_final"] is False
        ws.send_json({"type": "stop"})
        assert ws.receive_json() == STREAM_COMPLETE
        assert ws.receive_json() == STOPPED
        assert_closed(ws, 1000)
    assert scripted_source.instances[0].finished.is_set()


def test_reconnect_continues_sequence_script_and_clock(
    client: TestClient, scripted_source: type[ScriptedSource]
) -> None:
    scripted_source.reset(final("One."), final("Two."))
    meeting_id = create_meeting(client)
    time.sleep(0.2)  # timestamps count from the meeting start, not the connection
    for expected in ([1, 2], [3, 4]):
        with client.websocket_connect(stream_url(meeting_id)) as ws:
            assert ws.receive_json() == CONNECTED_MOCK
            assert [ws.receive_json()["sequence"] for _ in range(2)] == expected
            ws.send_json({"type": "stop"})
            receive_until(ws, is_status("stopped"))
        time.sleep(0.1)

    # The mock script resumes after the lines already delivered.
    assert [source.start_index for source in scripted_source.instances] == [0, 2]
    stored = client.get(f"/api/meetings/{meeting_id}/transcript").json()
    assert [s["sequence"] for s in stored] == [1, 2, 3, 4]
    timestamps = [s["timestamp"] for s in stored]
    assert timestamps[0] >= 0.2
    assert timestamps[2] >= timestamps[1] + 0.1


def test_a_second_viewer_shares_the_single_source(
    client: TestClient, scripted_source: type[ScriptedSource]
) -> None:
    scripted_source.reset(final("Hello."), final("World."), auto_release=False)
    meeting_id = create_meeting(client)
    with client.websocket_connect(stream_url(meeting_id)) as owner:
        assert owner.receive_json() == CONNECTED_MOCK
        wait_until(lambda: len(scripted_source.instances) == 1)
        with client.websocket_connect(stream_url(meeting_id)) as viewer:
            assert viewer.receive_json() == CONNECTED_MOCK
            (source,) = scripted_source.instances
            client.portal.call(source.released.set)

            owner_view = [owner.receive_json() for _ in range(2)]
            viewer_view = [viewer.receive_json() for _ in range(2)]
            assert owner_view == viewer_view
            assert [m["sequence"] for m in owner_view] == [1, 2]

            owner.send_json({"type": "stop"})
            assert receive_until(owner, is_status("stopped"))[-2:] == [STREAM_COMPLETE, STOPPED]
            assert viewer.receive_json() == STREAM_COMPLETE

    assert len(scripted_source.instances) == 1
    stored = client.get(f"/api/meetings/{meeting_id}/transcript").json()
    assert [s["text"] for s in stored] == ["Hello.", "World."]


def test_ping_pong_and_unknown_messages(
    client: TestClient, scripted_source: type[ScriptedSource]
) -> None:
    with client.websocket_connect(stream_url(create_meeting(client))) as ws:
        assert ws.receive_json() == CONNECTED_MOCK
        ws.send_text("not json")
        ws.send_json({"type": "subscribe"})
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


# --- Rejections and limits -----------------------------------------------------------


def test_unknown_meeting_is_rejected(client: TestClient) -> None:
    with client.websocket_connect(stream_url("nope")) as ws:
        assert ws.receive_json() == error("meeting_not_found", "Meeting not found.", False)
        assert_closed(ws, 1008)


def test_ended_meeting_is_rejected(client: TestClient) -> None:
    meeting_id = create_meeting(client)
    client.post(f"/api/meetings/{meeting_id}/end")
    with client.websocket_connect(stream_url(meeting_id)) as ws:
        assert ws.receive_json() == error("meeting_ended", "This meeting has already ended.", False)
        assert_closed(ws, 1008)


def test_disallowed_origin_is_rejected(client: TestClient) -> None:
    meeting_id = create_meeting(client)
    headers = {"origin": "https://evil.example"}
    with client.websocket_connect(stream_url(meeting_id), headers=headers) as ws:
        assert ws.receive_json() == error(
            "origin_not_allowed", "This site is not allowed to open a live stream.", False
        )
        assert_closed(ws, 1008)


@pytest.mark.parametrize("headers", [{"origin": "http://localhost:5173"}, {}])
def test_allowed_or_missing_origin_connects(
    client: TestClient, scripted_source: type[ScriptedSource], headers: dict[str, str]
) -> None:
    with client.websocket_connect(stream_url(create_meeting(client)), headers=headers) as ws:
        assert ws.receive_json() == CONNECTED_MOCK


def test_connections_per_ip_are_capped(
    client: TestClient, scripted_source: type[ScriptedSource]
) -> None:
    meeting_id = create_meeting(client)
    with contextlib.ExitStack() as stack:
        for _ in range(settings.ws_max_connections_per_ip):
            ws = stack.enter_context(client.websocket_connect(stream_url(meeting_id)))
            assert ws.receive_json() == CONNECTED_MOCK
        with client.websocket_connect(stream_url(meeting_id)) as extra:
            assert extra.receive_json() == error(
                "too_many_connections",
                "Too many live streams are open from your network. Close one and retry.",
                True,
            )
            assert_closed(extra, 1013)
    with client.websocket_connect(stream_url(meeting_id)) as ws:
        assert ws.receive_json() == CONNECTED_MOCK


def test_sessions_are_time_limited(
    client: TestClient, scripted_source: type[ScriptedSource], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "session_max_seconds", 0.2)
    with client.websocket_connect(stream_url(create_meeting(client))) as ws:
        assert ws.receive_json() == CONNECTED_MOCK
        assert receive_until(ws, lambda m: m["type"] == "error")[-1] == error(
            "session_time_limit", "This live session reached its time limit.", False
        )
        assert_closed(ws, 1008)


# --- Deepgram mode (with a fake streamer) ---------------------------------------------


@pytest.fixture
def deepgram_mode(fake_deepgram: type[FakeDeepgram]) -> type[FakeDeepgram]:
    return fake_deepgram


def test_deepgram_opens_on_first_audio_and_flushes_on_stop(
    client: TestClient, deepgram_mode: type[FakeDeepgram]
) -> None:
    meeting_id = create_meeting(client)
    with client.websocket_connect(stream_url(meeting_id)) as ws:
        assert ws.receive_json() == CONNECTED_DEEPGRAM
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
        assert deepgram_mode.instances == []  # nothing opened before audio

        ws.send_bytes(b"webm-header")
        ws.send_bytes(b"chunk-2")
        assert [ws.receive_json()["text"] for _ in range(2)] == ["heard 1", "heard 2"]

        ws.send_json({"type": "stop"})
        flushed, complete, stopped = receive_until(ws, is_status("stopped"))
        assert (flushed["is_final"], flushed["sequence"], flushed["speaker"]) == (
            True,
            1,
            "Speaker 1",
        )
        assert (complete, stopped) == (STREAM_COMPLETE, STOPPED)
        assert_closed(ws, 1000)

    (streamer,) = deepgram_mode.instances
    assert streamer.audio == [b"webm-header", b"chunk-2"]
    assert streamer.finished
    stored = client.get(f"/api/meetings/{meeting_id}/transcript").json()
    assert [s["text"] for s in stored] == ["final words after 2 frames"]


def test_deepgram_connect_failure_is_reported(
    client: TestClient, deepgram_mode: type[FakeDeepgram]
) -> None:
    deepgram_mode.reset(fail_connect=True)
    with client.websocket_connect(stream_url(create_meeting(client))) as ws:
        assert ws.receive_json() == CONNECTED_DEEPGRAM
        ws.send_bytes(b"webm-header")
        assert ws.receive_json() == error(
            "transcription_unavailable", "Live transcription is temporarily unavailable.", True
        )
        assert_closed(ws, 1011)


def test_audio_from_a_second_client_is_ignored(
    client: TestClient, deepgram_mode: type[FakeDeepgram]
) -> None:
    meeting_id = create_meeting(client)
    with client.websocket_connect(stream_url(meeting_id)) as owner:
        assert owner.receive_json() == CONNECTED_DEEPGRAM
        owner.send_bytes(b"owner-header")
        assert owner.receive_json()["text"] == "heard 1"
        with client.websocket_connect(stream_url(meeting_id)) as other:
            assert other.receive_json() == CONNECTED_DEEPGRAM
            other.send_bytes(b"other-header")
            owner.send_bytes(b"owner-2")
            assert owner.receive_json()["text"] == "heard 2"
            assert other.receive_json()["text"] == "heard 2"

    (streamer,) = deepgram_mode.instances
    assert streamer.audio == [b"owner-header", b"owner-2"]


# --- Against a real uvicorn server --------------------------------------------------


async def _create_meeting_live(base: str) -> str:
    async with httpx.AsyncClient(base_url=f"http://{base}") as http:
        return (await http.post("/api/meetings", json={"title": "Live"})).json()["id"]


async def _stored_texts(base: str, meeting_id: str) -> list[str]:
    async with httpx.AsyncClient(base_url=f"http://{base}") as http:
        response = await http.get(f"/api/meetings/{meeting_id}/transcript")
        return [segment["text"] for segment in response.json()]


async def test_live_stop_flow_and_close_code(
    live_server: str, scripted_source: type[ScriptedSource]
) -> None:
    scripted_source.reset(final("Hello from uvicorn."))
    meeting_id = await _create_meeting_live(live_server)
    url = f"ws://{live_server}/ws/meetings/{meeting_id}/stream"
    async with websockets.connect(url, origin="http://localhost:5173") as ws:
        assert json.loads(await ws.recv()) == CONNECTED_MOCK
        assert json.loads(await ws.recv())["sequence"] == 1
        await ws.send(json.dumps({"type": "stop"}))
        assert json.loads(await ws.recv()) == STREAM_COMPLETE
        assert json.loads(await ws.recv()) == STOPPED
        with pytest.raises(websockets.ConnectionClosedOK):
            await ws.recv()
        assert ws.close_code == 1000


async def test_live_disconnect_flushes_final_words_without_errors(
    live_server: str, deepgram_mode: type[FakeDeepgram], caplog: pytest.LogCaptureFixture
) -> None:
    meeting_id = await _create_meeting_live(live_server)
    url = f"ws://{live_server}/ws/meetings/{meeting_id}/stream"
    with caplog.at_level(logging.INFO):
        async with websockets.connect(url) as ws:
            assert json.loads(await ws.recv()) == CONNECTED_DEEPGRAM
            await ws.send(b"webm-header")
            assert json.loads(await ws.recv())["is_final"] is False
        # The client left without "stop"; the server still flushes the stream.
        for _ in range(100):
            if await _stored_texts(live_server, meeting_id):
                break
            await asyncio.sleep(0.02)

    assert await _stored_texts(live_server, meeting_id) == ["final words after 1 frames"]
    assert deepgram_mode.instances[0].finished
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []


async def test_live_origin_check_uses_the_close_code(live_server: str) -> None:
    meeting_id = await _create_meeting_live(live_server)
    url = f"ws://{live_server}/ws/meetings/{meeting_id}/stream"
    async with websockets.connect(url, origin="https://evil.example") as ws:
        assert json.loads(await ws.recv())["code"] == "origin_not_allowed"
        with pytest.raises(websockets.ConnectionClosed):
            await ws.recv()
        assert ws.close_code == 1008
