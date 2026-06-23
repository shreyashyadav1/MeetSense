import logging
from typing import Optional

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis: Optional[Redis] = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def publish_segment(meeting_id: str, segment_json: str) -> None:
    """Publish a transcript segment JSON string to the meeting channel."""
    r = get_redis()
    channel = f"meeting:{meeting_id}:segments"
    await r.publish(channel, segment_json)
    logger.debug("[Redis] published to %s", channel)


async def subscribe_segments(meeting_id: str) -> PubSub:
    """Return a PubSub subscribed to the meeting's segment channel."""
    r = get_redis()
    ps = r.pubsub()
    await ps.subscribe(f"meeting:{meeting_id}:segments")
    return ps


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None
