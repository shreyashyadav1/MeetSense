"""Shared fixtures.

Unit tests need nothing but Python. Integration tests use the PostgreSQL and
Redis servers named by TEST_DATABASE_URL and TEST_REDIS_URL (the defaults match
the development containers on ports 5433 and 6380) and are skipped when those
servers are unreachable. They never call Deepgram or Groq.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator, Coroutine, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
import redis
import uvicorn
from fastapi.testclient import TestClient

from app.core.config import Settings, normalize_database_url, settings
from tests.fakes import FakeDeepgram, FakeGroq, ScriptedSource

T = TypeVar("T")

TEST_DATABASE_URL = normalize_database_url(
    os.environ.get(
        "TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/meetsense_test"
    )
)
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6380/0")

# Every test starts from the declared defaults, never from backend/.env or the
# shell, so a developer's real keys or database can't leak into a test run.
BASELINE = Settings.model_construct(redis_url="")
for _name in Settings.model_fields:
    setattr(settings, _name, getattr(BASELINE, _name))


def run_sync(coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine to completion on a private event loop (for sync fixtures)."""
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coro).result()


@pytest.fixture(autouse=True)
def _baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.rate_limit import limiter
    from app.services import mock_transcription

    for name in Settings.model_fields:
        monkeypatch.setattr(settings, name, getattr(BASELINE, name))
    monkeypatch.setattr(mock_transcription, "PACE", 0.0)
    monkeypatch.setattr(limiter, "enabled", False)
    limiter.reset()


@pytest.fixture
def client() -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
async def live_server(unused_tcp_port: int) -> AsyncIterator[str]:
    """The app served by a real uvicorn on this test's event loop."""
    from app.main import app

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=unused_tcp_port, log_level="warning")
    )
    task = asyncio.create_task(server.serve())
    while not server.started:
        if task.done():
            task.result()
        await asyncio.sleep(0.01)
    try:
        yield f"127.0.0.1:{unused_tcp_port}"
    finally:
        server.should_exit = True
        await task


# --- PostgreSQL ------------------------------------------------------------------


def asyncpg_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def recreate_database(url: str) -> None:
    """Create the database if needed and drop everything in it."""
    parts = urlsplit(asyncpg_dsn(url))
    name = parts.path.lstrip("/")
    admin = await asyncpg.connect(urlunsplit(parts._replace(path="/postgres")), timeout=3)
    try:
        if not await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name):
            await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()
    connection = await asyncpg.connect(asyncpg_dsn(url), timeout=3)
    try:
        await connection.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    finally:
        await connection.close()


async def _truncate(url: str) -> None:
    connection = await asyncpg.connect(asyncpg_dsn(url), timeout=3)
    try:
        if await connection.fetchval("SELECT to_regclass('public.meetings')"):
            await connection.execute("TRUNCATE meetings, transcript_segments, meeting_insights")
    finally:
        await connection.close()


@pytest.fixture(scope="session")
def postgres_url() -> str:
    try:
        run_sync(recreate_database(TEST_DATABASE_URL))
    except (OSError, asyncpg.PostgresError) as error:
        pytest.skip(f"PostgreSQL unavailable at TEST_DATABASE_URL ({type(error).__name__})")
    return TEST_DATABASE_URL


@pytest.fixture
def postgres(postgres_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Point the app at the (emptied) test database."""
    from app.db.base import dispose_engine

    run_sync(_truncate(postgres_url))
    monkeypatch.setattr(settings, "database_url", postgres_url)
    yield postgres_url
    # The app's lifespan normally disposes the engine; this covers tests that
    # used the store without it.
    with contextlib.suppress(Exception):
        run_sync(dispose_engine())


# --- Redis -------------------------------------------------------------------------


@pytest.fixture(scope="session")
def redis_url() -> str:
    probe = redis.Redis.from_url(TEST_REDIS_URL, socket_connect_timeout=2)
    try:
        probe.ping()
    except redis.RedisError as error:
        pytest.skip(f"Redis unavailable at TEST_REDIS_URL ({type(error).__name__})")
    finally:
        probe.close()
    return TEST_REDIS_URL


@pytest.fixture
def redis_enabled(redis_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    from app.services.redis_service import close_redis

    monkeypatch.setattr(settings, "redis_url", redis_url)
    yield redis_url
    with contextlib.suppress(Exception):
        run_sync(close_redis())


# --- Test doubles ------------------------------------------------------------------


@pytest.fixture
def fake_groq(monkeypatch: pytest.MonkeyPatch) -> type[FakeGroq]:
    """Route insight generation to FakeGroq; queue replies with FakeGroq.reset(...)."""
    from app.services import ai_service

    FakeGroq.reset()
    monkeypatch.setattr(ai_service, "AsyncGroq", FakeGroq)
    monkeypatch.setattr(ai_service, "_client", None)
    monkeypatch.setattr(settings, "groq_api_key", "test-groq-key")
    return FakeGroq


@pytest.fixture
def scripted_source(monkeypatch: pytest.MonkeyPatch) -> type[ScriptedSource]:
    """Replace the mock script with ScriptedSource (see tests/fakes.py)."""
    from app.services import mock_transcription

    ScriptedSource.reset()
    monkeypatch.setattr(mock_transcription, "MockTranscriptionSource", ScriptedSource)
    return ScriptedSource


@pytest.fixture
def fake_deepgram(monkeypatch: pytest.MonkeyPatch) -> type[FakeDeepgram]:
    """Deepgram mode with FakeDeepgram in place of the real streamer."""
    from app.services import deepgram_service

    FakeDeepgram.reset()
    monkeypatch.setattr(deepgram_service, "DeepgramStreamer", FakeDeepgram)
    monkeypatch.setattr(settings, "deepgram_api_key", "test-deepgram-key")
    return FakeDeepgram
