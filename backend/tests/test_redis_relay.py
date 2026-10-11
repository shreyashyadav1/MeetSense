"""Fan-out through Redis for viewers connected to other backend instances."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis

from app.models.ws import StatusMessage
from app.services.mock_transcription import DIALOGUE
from app.services.smart_meeting_store import SmartMeetingStore
from app.services.transcription_hub import Subscriber, TranscriptionHub

pytestmark = pytest.mark.redis


async def test_messages_reach_viewers_on_other_instances(redis_url: str) -> None:
    store = SmartMeetingStore()
    meeting = await store.create_meeting("Relay")
    redis_a = Redis.from_url(redis_url, decode_responses=True)
    redis_b = Redis.from_url(redis_url, decode_responses=True)
    hub_a = TranscriptionHub(store, instance_id="instance-a")
    hub_b = TranscriptionHub(store, instance_id="instance-b")
    viewer_a, viewer_b = Subscriber("a"), Subscriber("b")
    try:
        session_a = await hub_a.join(meeting, viewer_a, redis=redis_a)
        await hub_b.join(meeting, viewer_b, redis=redis_b)

        await session_a.publish(StatusMessage(status="stream_complete"))
        expected = StatusMessage(status="stream_complete").model_dump_json()
        assert await asyncio.wait_for(viewer_b.next(), 2) == expected
        assert await asyncio.wait_for(viewer_a.next(), 2) == expected
        # Instance A ignores its own message coming back from Redis.
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(viewer_a.next(), 0.3)
    finally:
        await hub_a.shutdown()
        await hub_b.shutdown()
        await redis_a.aclose()
        await redis_b.aclose()


def test_stream_with_redis_delivers_each_message_once(
    redis_enabled: str, client: TestClient
) -> None:
    meeting_id = client.post("/api/meetings", json={"title": "Redis"}).json()["id"]
    with client.websocket_connect(f"/ws/meetings/{meeting_id}/stream") as ws:
        messages = []
        while (message := ws.receive_json()).get("status") != "stream_complete":
            messages.append(message)
    finals = [m for m in messages if m.get("type") == "transcript" and m["is_final"]]
    assert len(finals) == len({m["id"] for m in finals}) == len(DIALOGUE)
