import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.services.smart_meeting_store import smart_meeting_store as meeting_store
from app.services.redis_service import publish_segment, subscribe_segments
from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Redis-backed tasks (used when Redis is reachable)
# ---------------------------------------------------------------------------

async def _publish_task(transcript_iter, meeting_id: str, stop_event: asyncio.Event) -> None:
    """Reads transcript segments and publishes each to Redis."""
    try:
        async for segment in transcript_iter:
            if stop_event.is_set():
                return
            if segment.is_final:
                await meeting_store.add_segment(segment)
            await publish_segment(
                meeting_id,
                json.dumps({"type": "transcript", "data": segment.model_dump()}),
            )
        if not stop_event.is_set():
            await publish_segment(
                meeting_id,
                json.dumps({"type": "status", "data": {"status": "stream_complete", "meeting_id": meeting_id}}),
            )
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.exception("Publish task error for %s: %s", meeting_id, exc)
        try:
            await publish_segment(meeting_id, json.dumps({"type": "error", "data": {"message": str(exc)}}))
        except Exception:
            pass


async def _subscribe_task(websocket: WebSocket, meeting_id: str, stop_event: asyncio.Event) -> None:
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
                    break
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.exception("Subscribe task error for %s: %s", meeting_id, exc)
    finally:
        await ps.unsubscribe()
        await ps.aclose()


# ---------------------------------------------------------------------------
# Direct asyncio.Queue tasks (fallback when Redis is unavailable)
# ---------------------------------------------------------------------------

async def _publish_to_queue(
    transcript_iter, meeting_id: str, queue: asyncio.Queue, stop_event: asyncio.Event
) -> None:
    try:
        async for segment in transcript_iter:
            if stop_event.is_set():
                return
            if segment.is_final:
                await meeting_store.add_segment(segment)
            await queue.put(json.dumps({"type": "transcript", "data": segment.model_dump()}))
        if not stop_event.is_set():
            await queue.put(json.dumps({"type": "status", "data": {"status": "stream_complete", "meeting_id": meeting_id}}))
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.exception("Queue publish task error for %s: %s", meeting_id, exc)
        await queue.put(json.dumps({"type": "error", "data": {"message": str(exc)}}))
    finally:
        await queue.put(None)  # sentinel: signal consumer to stop


async def _subscribe_from_queue(
    websocket: WebSocket, queue: asyncio.Queue, stop_event: asyncio.Event
) -> None:
    try:
        while not stop_event.is_set():
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if msg is None:
                break
            try:
                await websocket.send_text(msg)
            except (WebSocketDisconnect, RuntimeError):
                break
    except asyncio.CancelledError:
        pass


# ---------------------------------------------------------------------------
# Check Redis availability (fast, single ping)
# ---------------------------------------------------------------------------

async def _redis_available() -> bool:
    try:
        from app.services.redis_service import get_redis
        r = await get_redis()
        await asyncio.wait_for(r.ping(), timeout=2.0)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/meetings/{meeting_id}/stream")
async def meeting_stream(websocket: WebSocket, meeting_id: str):
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

    # Use Redis if available, otherwise fall back to asyncio.Queue
    redis_ok = await _redis_available()
    if not redis_ok:
        logger.info("Redis unavailable — using direct queue transport for %s", meeting_id)

    if redis_ok:
        publish_task = asyncio.create_task(
            _publish_task(transcript_iter, meeting_id, stop_event),
            name=f"publish-{meeting_id}",
        )
        subscribe_task = asyncio.create_task(
            _subscribe_task(websocket, meeting_id, stop_event),
            name=f"subscribe-{meeting_id}",
        )
    else:
        queue: asyncio.Queue = asyncio.Queue()
        publish_task = asyncio.create_task(
            _publish_to_queue(transcript_iter, meeting_id, queue, stop_event),
            name=f"publish-{meeting_id}",
        )
        subscribe_task = asyncio.create_task(
            _subscribe_from_queue(websocket, queue, stop_event),
            name=f"subscribe-{meeting_id}",
        )

    try:
        while True:
            data = await websocket.receive()

            if "bytes" in data:
                if use_deepgram and streamer:
                    await streamer.send_audio(data["bytes"])

            elif "text" in data:
                try:
                    msg = json.loads(data["text"])
                except json.JSONDecodeError:
                    await websocket.send_text(json.dumps({"type": "error", "data": {"message": "Invalid JSON."}}))
                    continue

                msg_type = msg.get("type", "")

                if msg_type == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))

                elif msg_type == "stop":
                    stop_event.set()
                    await websocket.send_text(json.dumps({
                        "type": "status",
                        "data": {"status": "stopped", "meeting_id": meeting_id},
                    }))
                    break

                else:
                    await websocket.send_text(json.dumps({"type": "error", "data": {"message": f"Unknown type: '{msg_type}'"}}))

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for meeting %s", meeting_id)
    except Exception as exc:
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
