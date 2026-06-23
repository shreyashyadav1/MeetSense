import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.services.smart_meeting_store import smart_meeting_store as meeting_store
from app.services.redis_service import publish_segment, subscribe_segments
from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


async def _publish_task(transcript_iter, meeting_id: str, stop_event: asyncio.Event) -> None:
    """Reads transcript segments and publishes each to Redis."""
    try:
        async for segment in transcript_iter:
            if stop_event.is_set():
                logger.info("Stop event set — halting publish task for %s", meeting_id)
                return
            # Only persist final segments
            if segment.is_final:
                await meeting_store.add_segment(segment)
            await publish_segment(
                meeting_id,
                json.dumps({"type": "transcript", "data": segment.model_dump()}),
            )

        # Stream finished naturally — publish a status message
        if not stop_event.is_set():
            await publish_segment(
                meeting_id,
                json.dumps({
                    "type": "status",
                    "data": {
                        "status": "stream_complete",
                        "meeting_id": meeting_id,
                        "message": "Transcription stream has finished.",
                    },
                }),
            )
    except asyncio.CancelledError:
        logger.info("Publish task cancelled for meeting %s", meeting_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error in publish task for %s: %s", meeting_id, exc)
        # Publish the error so the subscribe task can forward it to the client
        try:
            await publish_segment(
                meeting_id,
                json.dumps({
                    "type": "error",
                    "data": {
                        "message": "Internal error during transcription stream.",
                        "detail": str(exc),
                    },
                }),
            )
        except Exception:  # noqa: BLE001
            pass


async def _subscribe_task(
    websocket: WebSocket,
    meeting_id: str,
    stop_event: asyncio.Event,
) -> None:
    """Reads from Redis pub/sub and forwards messages to the WebSocket client."""
    ps = await subscribe_segments(meeting_id)
    try:
        async for message in ps.listen():
            if stop_event.is_set():
                break
            if message["type"] == "message":
                try:
                    await websocket.send_text(message["data"])
                except (WebSocketDisconnect, RuntimeError):
                    logger.info("WebSocket closed during subscribe task for meeting %s", meeting_id)
                    break
    except asyncio.CancelledError:
        logger.info("Subscribe task cancelled for meeting %s", meeting_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error in subscribe task for %s: %s", meeting_id, exc)
    finally:
        await ps.unsubscribe()
        await ps.aclose()


@router.websocket("/meetings/{meeting_id}/stream")
async def meeting_stream(websocket: WebSocket, meeting_id: str):
    """
    WS /ws/meetings/{meeting_id}/stream

    Protocol
    --------
    On connect:
        server -> {"type": "status", "data": {"status": "connected", "meeting_id": "...", "mode": "deepgram"|"mock"}}

    During stream:
        server -> {"type": "transcript", "data": {segment fields}}

    Client may send:
        binary bytes          -> forwarded to Deepgram as audio chunks (deepgram mode only)
        {"type": "ping"}      -> server replies {"type": "pong"}
        {"type": "stop"}      -> server tears down the stream

    On error:
        server -> {"type": "error", "data": {"message": "...", "detail": "..."}}
    """
    meeting = await meeting_store.get_meeting(meeting_id)
    if not meeting:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning("WebSocket rejected — meeting '%s' not found", meeting_id)
        return

    await websocket.accept()
    logger.info("WebSocket connected for meeting %s", meeting_id)

    use_deepgram = bool(settings.deepgram_api_key)

    await websocket.send_text(json.dumps({
        "type": "status",
        "data": {
            "status": "connected",
            "meeting_id": meeting_id,
            "title": meeting.title,
            "mode": "deepgram" if use_deepgram else "mock",
        },
    }))

    if use_deepgram:
        from app.services.deepgram_service import DeepgramStreamer
        streamer = DeepgramStreamer(meeting_id)
        await streamer.connect()
        transcript_iter = streamer.transcript_stream()
    else:
        from app.services.mock_transcription import mock_transcript_stream
        transcript_iter = mock_transcript_stream(meeting_id)
        streamer = None

    stop_event = asyncio.Event()

    publish_task = asyncio.create_task(
        _publish_task(transcript_iter, meeting_id, stop_event),
        name=f"publish-{meeting_id}",
    )
    subscribe_task = asyncio.create_task(
        _subscribe_task(websocket, meeting_id, stop_event),
        name=f"subscribe-{meeting_id}",
    )

    try:
        while True:
            data = await websocket.receive()

            if "bytes" in data:
                # Audio chunk from browser — forward to Deepgram
                if use_deepgram and streamer:
                    await streamer.send_audio(data["bytes"])

            elif "text" in data:
                try:
                    msg = json.loads(data["text"])
                except json.JSONDecodeError:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "data": {"message": "Invalid JSON received."},
                    }))
                    continue

                msg_type = msg.get("type", "")

                if msg_type == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))

                elif msg_type == "stop":
                    stop_event.set()
                    await websocket.send_text(json.dumps({
                        "type": "status",
                        "data": {
                            "status": "stopped",
                            "meeting_id": meeting_id,
                            "message": "Stream stopped by client request.",
                        },
                    }))
                    break

                else:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "data": {"message": f"Unknown message type: '{msg_type}'."},
                    }))

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for meeting %s", meeting_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unhandled WebSocket error for meeting %s: %s", meeting_id, exc)
    finally:
        stop_event.set()
        for task in (publish_task, subscribe_task):
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        if streamer:
            await streamer.close()
        logger.info("WebSocket handler cleaned up for meeting %s", meeting_id)
