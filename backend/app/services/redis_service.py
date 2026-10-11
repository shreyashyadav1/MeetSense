"""Shared Redis client (optional: a blank REDIS_URL disables Redis)."""

from __future__ import annotations

import asyncio

from redis.asyncio import Redis

from app.core.config import settings

PING_TIMEOUT_SECONDS = 1.0

_client: Redis | None = None


def get_redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            health_check_interval=30,
        )
    return _client


async def redis_available() -> bool:
    """Whether Redis is configured and answers a PING promptly."""
    if not settings.redis_url:
        return False
    try:
        return bool(await asyncio.wait_for(get_redis().ping(), PING_TIMEOUT_SECONDS))
    except Exception:
        return False


def segment_channel(meeting_id: str) -> str:
    return f"meeting:{meeting_id}:segments"


async def close_redis() -> None:
    global _client
    client, _client = _client, None
    if client is not None:
        await client.aclose()
