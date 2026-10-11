from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import asyncpg
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import exc as sa_exc

from app.core.config import settings
from app.db.base import dispose_engine
from app.models.schemas import Meeting, MeetingInsights, TranscriptSegment
from app.services.meeting_store import MeetingStore
from app.services.pg_meeting_store import PgMeetingStore
from app.services.smart_meeting_store import (
    DatabaseUnavailableError,
    SmartMeetingStore,
    is_unavailable_error,
    smart_meeting_store,
)
from tests.fakes import VALID_INSIGHTS, FakeGroq


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


class FlakyBackend(MeetingStore):
    """An in-memory backend whose calls raise ``error`` while it is set."""

    def __init__(self) -> None:
        super().__init__()
        self.error: BaseException | None = None
        self.calls = 0

    def _call(self) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error

    async def prepare(self) -> None:
        self._call()

    async def ping(self) -> None:
        self._call()

    async def create_meeting(self, title: str) -> Meeting:
        self._call()
        return await super().create_meeting(title)

    async def list_meetings(self, *, limit: int, offset: int) -> list[Meeting]:
        self._call()
        return await super().list_meetings(limit=limit, offset=offset)


def make_store(
    *, allow_fallback: bool = True
) -> tuple[SmartMeetingStore, FlakyBackend, MeetingStore, FakeClock]:
    clock, primary, fallback = FakeClock(), FlakyBackend(), MeetingStore()
    store = SmartMeetingStore(
        primary,
        fallback,
        allow_fallback=allow_fallback,
        retry_base_seconds=2,
        retry_max_seconds=8,
        clock=clock,
    )
    return store, primary, fallback, clock


async def test_healthy_primary_serves_everything() -> None:
    store, primary, fallback, _ = make_store()
    meeting = await store.create_meeting("Sync")
    assert await primary.get_meeting(meeting.id) == meeting
    assert await fallback.list_meetings(limit=10, offset=0) == []
    assert await store.health() == "postgres"


async def test_outage_falls_back_backs_off_and_recovers(caplog: pytest.LogCaptureFixture) -> None:
    store, primary, fallback, clock = make_store()
    await store.list_meetings(limit=10, offset=0)  # schema prepared, breaker closed
    primary.error = ConnectionRefusedError("connection refused")

    with caplog.at_level(logging.INFO, logger="app.services.smart_meeting_store"):
        meeting = await store.create_meeting("During the outage")
        assert await fallback.get_meeting(meeting.id) == meeting

        # While the breaker is open, PostgreSQL is not touched at all.
        calls = primary.calls
        await store.list_meetings(limit=10, offset=0)
        assert primary.calls == calls
        assert await store.health() == "memory"

        clock.now += 2  # first retry: still down, next delay doubles to 4 s
        await store.list_meetings(limit=10, offset=0)
        assert primary.calls == calls + 1
        clock.now += 2
        await store.list_meetings(limit=10, offset=0)
        assert primary.calls == calls + 1

        primary.error = None
        clock.now += 2
        recovered = await store.create_meeting("After recovery")
        assert await primary.get_meeting(recovered.id) == recovered
        assert await store.health() == "postgres"

    messages = [r.getMessage() for r in caplog.records]
    assert sum("PostgreSQL unavailable" in m for m in messages) == 1
    assert sum("connection restored" in m for m in messages) == 1


async def test_retry_delay_is_capped() -> None:
    store, primary, _, clock = make_store()
    primary.error = TimeoutError()
    for _ in range(10):
        clock.now += 8
        await store.list_meetings(limit=1, offset=0)
    calls = primary.calls
    clock.now += 8  # the cap: never waits longer than retry_max_seconds
    await store.list_meetings(limit=1, offset=0)
    assert primary.calls == calls + 1


async def test_without_fallback_an_outage_fails_fast() -> None:
    store, primary, fallback, clock = make_store(allow_fallback=False)
    primary.error = OSError("network unreachable")
    with pytest.raises(DatabaseUnavailableError):
        await store.create_meeting("Lost")
    assert await store.health() == "unavailable"
    assert await fallback.list_meetings(limit=10, offset=0) == []

    primary.error = None
    clock.now += 2
    assert (await store.create_meeting("Back")).title == "Back"


@pytest.mark.parametrize(
    "error",
    [ValueError("bad data"), sa_exc.IntegrityError("INSERT", {}, Exception("duplicate key"))],
)
async def test_other_errors_propagate_without_falling_back(error: Exception) -> None:
    store, primary, fallback, _ = make_store()
    await store.list_meetings(limit=1, offset=0)
    primary.error = error
    with pytest.raises(type(error)):
        await store.create_meeting("Bad")
    primary.error = None
    await store.create_meeting("Fine")
    assert await fallback.list_meetings(limit=10, offset=0) == []
    assert len(await primary.list_meetings(limit=10, offset=0)) == 1


async def test_a_failed_schema_upgrade_counts_as_an_outage() -> None:
    store, primary, fallback, clock = make_store()
    primary.error = RuntimeError("migration failed")
    await store.create_meeting("Early")
    assert len(await fallback.list_meetings(limit=10, offset=0)) == 1

    primary.error = None
    clock.now += 2
    await store.create_meeting("Later")
    assert len(await primary.list_meetings(limit=10, offset=0)) == 1


@pytest.mark.parametrize(
    ("error", "unavailable"),
    [
        (ConnectionRefusedError(), True),
        (TimeoutError(), True),
        (sa_exc.OperationalError("SELECT 1", {}, Exception("server closed")), True),
        (sa_exc.DBAPIError("SELECT 1", {}, Exception("gone"), connection_invalidated=True), True),
        (sa_exc.TimeoutError("pool exhausted"), True),
        (asyncpg.InvalidPasswordError("password authentication failed"), True),
        (sa_exc.IntegrityError("INSERT", {}, Exception("duplicate")), False),
        (sa_exc.ProgrammingError("SELECT", {}, Exception("syntax")), False),
        (ValueError("bad"), False),
    ],
)
def test_is_unavailable_error(error: BaseException, unavailable: bool) -> None:
    assert is_unavailable_error(error) is unavailable


async def test_startup_tolerates_an_unreachable_database(
    unused_tcp_port: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"postgresql+asyncpg://postgres:postgres@127.0.0.1:{unused_tcp_port}/meetsense"
    monkeypatch.setattr(settings, "database_url", url)
    store = SmartMeetingStore()
    try:
        await store.startup()
        assert await store.health() == "memory"
        assert (await store.create_meeting("Offline")).title == "Offline"

        monkeypatch.setattr(settings, "allow_memory_fallback", False)
        with pytest.raises(OSError):
            await SmartMeetingStore().startup()
    finally:
        await store.shutdown()


# --- PostgreSQL --------------------------------------------------------------------


def _segment(meeting_id: str, sequence: int, timestamp: float) -> TranscriptSegment:
    return TranscriptSegment(
        id=f"{meeting_id}-{sequence}",
        meeting_id=meeting_id,
        sequence=sequence,
        speaker="Speaker 1",
        text=f"Line {sequence}",
        timestamp=timestamp,
        confidence=0.9,
    )


def _insights(meeting_id: str, summary: str) -> MeetingInsights:
    return MeetingInsights(
        id=f"insights-{summary}",
        meeting_id=meeting_id,
        generated_at=datetime.now(UTC),
        **{**VALID_INSIGHTS, "summary": summary},
    )


@pytest.mark.postgres
async def test_postgres_store_round_trip(postgres: str) -> None:
    store = PgMeetingStore()
    try:
        await store.prepare()
        created = [await store.create_meeting(f"Meeting {n}") for n in range(3)]
        newest_first = [m.id for m in reversed(created)]
        assert [m.id for m in await store.list_meetings(limit=10, offset=0)] == newest_first
        assert [m.id for m in await store.list_meetings(limit=1, offset=1)] == newest_first[1:2]

        meeting = created[0]
        assert await store.get_meeting(meeting.id) == meeting
        assert await store.get_meeting("missing") is None
        ended = await store.end_meeting(meeting.id)
        assert ended is not None and ended.status == "ended" and ended.ended_at is not None

        await store.add_segment(_segment(meeting.id, 2, timestamp=0.5))
        await store.add_segment(_segment(meeting.id, 1, timestamp=9.0))
        assert [s.sequence for s in await store.get_segments(meeting.id)] == [1, 2]
        assert await store.get_last_sequence(meeting.id) == 2
        assert await store.get_last_sequence(created[1].id) == 0

        # Concurrent saves for one meeting upsert instead of hitting the unique key.
        await asyncio.gather(
            store.save_insights(_insights(meeting.id, "first")),
            store.save_insights(_insights(meeting.id, "second")),
        )
        stored = await store.get_insights(meeting.id)
        assert stored is not None and stored.summary in {"first", "second"}
    finally:
        await dispose_engine()


@pytest.mark.postgres
def test_over_long_titles_no_longer_knock_out_postgres(postgres: str, client: TestClient) -> None:
    assert client.post("/api/meetings", json={"title": "x" * 256}).status_code == 422
    assert client.post("/api/meetings", json={"title": "Still here"}).status_code == 201
    assert client.get("/health").json()["database"] == "postgres"


@pytest.mark.postgres
def test_live_transcript_is_persisted_in_order(postgres: str, client: TestClient) -> None:
    meeting_id = client.post("/api/meetings", json={"title": "Persisted"}).json()["id"]
    with client.websocket_connect(f"/ws/meetings/{meeting_id}/stream") as ws:
        messages = []
        while (message := ws.receive_json()).get("status") != "stream_complete":
            messages.append(message)
    finals = [m for m in messages if m.get("type") == "transcript" and m["is_final"]]
    stored = client.get(f"/api/meetings/{meeting_id}/transcript").json()
    assert [s["id"] for s in stored] == [m["id"] for m in finals]
    assert [s["sequence"] for s in stored] == list(range(1, len(finals) + 1))


@pytest.mark.postgres
async def test_concurrent_summarize_calls_share_one_model_call(
    postgres: str, fake_groq: type[FakeGroq]
) -> None:
    from app.main import app

    fake_groq.reset(VALID_INSIGHTS, VALID_INSIGHTS)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            meeting_id = (await http.post("/api/meetings", json={"title": "Race"})).json()["id"]
            await smart_meeting_store.add_segment(_segment(meeting_id, 1, timestamp=1.0))
            url = f"/api/meetings/{meeting_id}/summarize"
            first, second = await asyncio.gather(http.post(url), http.post(url))

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(fake_groq.requests_made()) == 1
