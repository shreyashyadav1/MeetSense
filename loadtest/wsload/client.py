"""One simulated client socket: connects, plays a role until a deadline, records metrics.

Two roles, matching the streaming protocol (``backend/app/models/ws.py``):

* ``streamer`` sends a small binary "audio" frame every 250ms, like a browser's
  MediaRecorder would. In mock mode the bytes are never inspected, so any
  small payload exercises the same receive-loop code path as real audio.
* ``viewer`` only reads: it subscribes to the same meeting's fan-out without
  sending audio.

Both roles send periodic pings (to sample round-trip latency) and a clean
``stop`` at the shared ``deadline``, then let the server close the socket.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from dataclasses import dataclass
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from .metrics import Recorder

AUDIO_FRAME = bytes(1000)
AUDIO_INTERVAL_SECONDS = 0.25
VIEWER_IDLE_TICK_SECONDS = 1.0
PING_INTERVAL_SECONDS = 3.0
DEFAULT_ORIGIN = "http://localhost:5173"
CLOSE_GRACE_SECONDS = 15.0


@dataclass
class _SessionState:
    last_seq: int = 0
    finals: int = 0
    gaps: int = 0
    dupes: int = 0
    pending_ping_at: float | None = None
    got_connected: bool = False


async def run_connection(
    recorder: Recorder,
    ws_url: str,
    *,
    role: str,
    deadline: float,
    origin: str = DEFAULT_ORIGIN,
) -> None:
    """Open one socket, act out ``role`` until ``deadline`` (a ``perf_counter()`` time)."""
    t_dial = time.perf_counter()
    try:
        async with websockets.connect(ws_url, origin=origin, open_timeout=10) as ws:
            t_socket_open = time.perf_counter()
            recorder.connect(role, (t_socket_open - t_dial) * 1000)
            grace = max(0.0, deadline - time.perf_counter()) + CLOSE_GRACE_SECONDS
            try:
                await asyncio.wait_for(_play(recorder, ws, role, deadline, t_socket_open), grace)
            except TimeoutError:
                recorder.exception(role, "timed out waiting for the server to close the socket")
    except Exception as error:
        recorder.exception(role, f"{type(error).__name__}: {error}")


async def _play(
    recorder: Recorder, ws: Any, role: str, deadline: float, t_socket_open: float
) -> None:
    state = _SessionState()
    sender = asyncio.create_task(_sender_loop(ws, role, deadline, state))
    try:
        # A clean close (1000/1001) ends this loop silently; an abnormal one
        # raises. Either way, ws.close_code/close_reason are read below, once
        # the connection is actually closed.
        async for raw in ws:
            if isinstance(raw, bytes | bytearray):
                continue  # the server never sends binary frames to the client
            _handle_message(recorder, role, json.loads(raw), state, t_socket_open)
    except ConnectionClosed:
        pass
    finally:
        sender.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sender
        recorder.close(role, ws.close_code, ws.close_reason or "")
        recorder.sequence_summary(
            role, finals=state.finals, gaps=state.gaps, duplicates=state.dupes
        )


def _handle_message(
    recorder: Recorder,
    role: str,
    message: dict[str, Any],
    state: _SessionState,
    t_socket_open: float,
) -> None:
    mtype = message.get("type")
    if mtype == "status" and message.get("status") == "connected":
        if not state.got_connected:
            state.got_connected = True
            recorder.connected(role, (time.perf_counter() - t_socket_open) * 1000)
    elif mtype == "transcript":
        emitted_at = message.get("emitted_at")
        if emitted_at is not None:
            recorder.transcript_latency(role, (time.time() - emitted_at) * 1000)
        if message.get("is_final"):
            _track_sequence(state, message["sequence"])
    elif mtype == "pong":
        if state.pending_ping_at is not None:
            recorder.ping_rtt(role, (time.perf_counter() - state.pending_ping_at) * 1000)
            state.pending_ping_at = None
    elif mtype == "error":
        recorder.error(role, message.get("code", "unknown"))


def _track_sequence(state: _SessionState, seq: int) -> None:
    state.finals += 1
    if state.last_seq and seq <= state.last_seq:
        state.dupes += 1
        return
    if state.last_seq and seq > state.last_seq + 1:
        state.gaps += seq - state.last_seq - 1
    state.last_seq = seq


async def _sender_loop(ws: Any, role: str, deadline: float, state: _SessionState) -> None:
    next_ping = time.perf_counter() + PING_INTERVAL_SECONDS
    tick = AUDIO_INTERVAL_SECONDS if role == "streamer" else VIEWER_IDLE_TICK_SECONDS
    try:
        while True:
            now = time.perf_counter()
            if now >= deadline:
                with contextlib.suppress(ConnectionClosed):
                    await ws.send(json.dumps({"type": "stop"}))
                return
            if role == "streamer":
                with contextlib.suppress(ConnectionClosed):
                    await ws.send(AUDIO_FRAME)
            if now >= next_ping and state.pending_ping_at is None:
                state.pending_ping_at = time.perf_counter()
                with contextlib.suppress(ConnectionClosed):
                    await ws.send(json.dumps({"type": "ping"}))
                next_ping = now + PING_INTERVAL_SECONDS
            await asyncio.sleep(tick)
    except asyncio.CancelledError:
        raise
