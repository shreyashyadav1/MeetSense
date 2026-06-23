import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.models.schemas import TranscriptSegment
from app.services.meeting_store import meeting_store
from app.services.mock_transcription import mock_transcript_stream

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helper: safe send — swallow errors when the socket closes mid-send
# ---------------------------------------------------------------------------

async def _send_json(ws: WebSocket, payload: dict) -> bool:
    """
    Send a JSON payload over *ws*.
    Returns True on success, False if the connection is already closed.
    """
    try:
        await ws.send_json(payload)
        return True
    except (WebSocketDisconnect, RuntimeError):
        return False


# ---------------------------------------------------------------------------
# Background task: stream mock transcription and push segments to the client
# ---------------------------------------------------------------------------

async def _stream_transcript(
    ws: WebSocket,
    meeting_id: str,
    stop_event: asyncio.Event,
) -> None:
    """
    Consume the mock transcript generator and forward each segment to the
    WebSocket client.  Stops early if *stop_event* is set (client disconnected).
    """
    try:
        async for segment in mock_transcript_stream(meeting_id):
            if stop_event.is_set():
                logger.info("Stop event set — halting transcript stream for %s", meeting_id)
                return

            # Persist the segment so REST clients can fetch it later
            await meeting_store.add_segment(segment)

            payload = {
                "type": "transcript",
                "data": {
                    "id": segment.id,
                    "meeting_id": segment.meeting_id,
                    "speaker": segment.speaker,
                    "text": segment.text,
                    "timestamp": segment.timestamp,
                    "confidence": segment.confidence,
                },
            }
            ok = await _send_json(ws, payload)
            if not ok:
                logger.info("WebSocket closed during stream for meeting %s", meeting_id)
                return

        # Stream finished — notify the client
        if not stop_event.is_set():
            await _send_json(
                ws,
                {
                    "type": "status",
                    "data": {
                        "status": "stream_complete",
                        "meeting_id": meeting_id,
                        "message": "Mock transcription stream has finished.",
                    },
                },
            )
    except asyncio.CancelledError:
        logger.info("Transcript stream task cancelled for meeting %s", meeting_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error in transcript stream for %s: %s", meeting_id, exc)
        await _send_json(
            ws,
            {
                "type": "error",
                "data": {
                    "message": "Internal error during transcription stream.",
                    "detail": str(exc),
                },
            },
        )


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/meetings/{meeting_id}/stream")
async def websocket_meeting_stream(ws: WebSocket, meeting_id: str) -> None:
    """
    WS /ws/meetings/{meeting_id}/stream

    Protocol
    --------
    On connect:
        server -> {"type": "status", "data": {"status": "connected", "meeting_id": "..."}}

    During stream:
        server -> {"type": "transcript", "data": {segment fields}}

    When stream finishes:
        server -> {"type": "status", "data": {"status": "stream_complete", ...}}

    Client may send:
        {"type": "ping"}   ->   server replies {"type": "pong"}

    On error:
        server -> {"type": "error", "data": {"message": "...", "detail": "..."}}
    """
    # Validate the meeting exists before accepting the socket
    meeting = await meeting_store.get_meeting(meeting_id)
    if meeting is None:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning("WebSocket rejected — meeting '%s' not found", meeting_id)
        return

    await ws.accept()
    logger.info("WebSocket connected for meeting %s", meeting_id)

    # Signal used to tell the background stream task to stop
    stop_event = asyncio.Event()

    # Send the initial connected status
    await _send_json(
        ws,
        {
            "type": "status",
            "data": {
                "status": "connected",
                "meeting_id": meeting_id,
                "title": meeting.title,
            },
        },
    )

    # Launch the transcript streaming task in the background
    stream_task = asyncio.create_task(
        _stream_transcript(ws, meeting_id, stop_event),
        name=f"stream-{meeting_id}",
    )

    try:
        # Keep the connection open and handle incoming client messages
        while True:
            raw = await ws.receive_text()

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send_json(
                    ws,
                    {
                        "type": "error",
                        "data": {"message": "Invalid JSON received."},
                    },
                )
                continue

            msg_type = msg.get("type", "")

            if msg_type == "ping":
                await _send_json(ws, {"type": "pong"})

            elif msg_type == "stop":
                # Client explicitly requests early termination of the stream
                stop_event.set()
                await _send_json(
                    ws,
                    {
                        "type": "status",
                        "data": {
                            "status": "stopped",
                            "meeting_id": meeting_id,
                            "message": "Stream stopped by client request.",
                        },
                    },
                )

            else:
                await _send_json(
                    ws,
                    {
                        "type": "error",
                        "data": {
                            "message": f"Unknown message type: '{msg_type}'.",
                        },
                    },
                )

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for meeting %s", meeting_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unhandled WebSocket error for meeting %s: %s", meeting_id, exc)
    finally:
        # Clean up: signal and cancel the background stream task
        stop_event.set()
        if not stream_task.done():
            stream_task.cancel()
            try:
                await stream_task
            except asyncio.CancelledError:
                pass
        logger.info("WebSocket handler cleaned up for meeting %s", meeting_id)
