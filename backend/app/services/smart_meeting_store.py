"""Meeting store that prefers PostgreSQL and degrades to memory during outages.

* ``DATABASE_URL`` empty: memory only.
* PostgreSQL unreachable: a circuit breaker opens. Calls are served from memory
  (``ALLOW_MEMORY_FALLBACK=true``, the default) or fail fast with
  ``DatabaseUnavailableError`` until a retry delay (exponential backoff, capped)
  elapses; the next call then probes PostgreSQL again and closes the breaker on
  success. Every state change is logged once.
* Errors that are not connectivity problems (bad data, SQL bugs) propagate: they
  would fail the same way on any database, and falling back would hide them.

Data written to memory during an outage stays there; it is not copied into
PostgreSQL once the database is back.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Literal, TypeVar

import asyncpg
from sqlalchemy import exc as sa_exc

from app.core.config import settings
from app.db.base import dispose_engine
from app.models.schemas import Meeting, MeetingInsights, TranscriptSegment
from app.services.meeting_store import MeetingStore, MeetingStoreBackend
from app.services.pg_meeting_store import PgMeetingStore

logger = logging.getLogger(__name__)

T = TypeVar("T")
DatabaseState = Literal["postgres", "memory", "unavailable"]

HEALTH_CHECK_TIMEOUT_SECONDS = 2.0


class DatabaseUnavailableError(RuntimeError):
    """PostgreSQL is unreachable and the memory fallback is disabled."""


def is_unavailable_error(error: BaseException) -> bool:
    """Whether ``error`` means PostgreSQL could not be reached (not a bad query)."""
    if isinstance(error, OSError | sa_exc.TimeoutError):
        # OSError covers refused/reset connections, DNS failures and timeouts.
        return True
    if isinstance(error, sa_exc.DBAPIError):
        return error.connection_invalidated or isinstance(
            error, sa_exc.InterfaceError | sa_exc.OperationalError
        )
    # asyncpg errors raised while *opening* a connection (bad credentials,
    # unknown database, server starting up) reach us unwrapped by SQLAlchemy.
    return isinstance(error, asyncpg.PostgresError | asyncpg.InterfaceError)


class SmartMeetingStore:
    def __init__(
        self,
        primary: MeetingStoreBackend | None = None,
        fallback: MeetingStoreBackend | None = None,
        *,
        allow_fallback: bool = True,
        retry_base_seconds: float = 2.0,
        retry_max_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._retry_base = retry_base_seconds
        self._retry_max = retry_max_seconds
        self._clock = clock
        self.configure(primary=primary, fallback=fallback, allow_fallback=allow_fallback)

    def configure(
        self,
        *,
        primary: MeetingStoreBackend | None,
        fallback: MeetingStoreBackend | None = None,
        allow_fallback: bool = True,
    ) -> None:
        """Replace the backends and reset the breaker (used at startup and in tests)."""
        self._primary = primary
        self._fallback = fallback if fallback is not None else MeetingStore()
        self._allow_fallback = allow_fallback
        self._schema_ready = False
        self._failures = 0
        self._retry_at = 0.0
        self._probe_in_flight = False

    # --- Lifecycle -------------------------------------------------------------

    async def startup(self) -> None:
        """Configure from settings and bring the database schema up to date."""
        primary = PgMeetingStore() if settings.database_url else None
        self.configure(primary=primary, allow_fallback=settings.allow_memory_fallback)
        if primary is None:
            logger.info("DATABASE_URL is not set; meetings are kept in memory")
            return
        try:
            await self._prepare(primary)
        except Exception as error:
            if not self._allow_fallback:
                raise
            self._record_failure(error)
        else:
            logger.info("PostgreSQL ready; migrations applied")

    async def shutdown(self) -> None:
        await dispose_engine()

    async def health(self) -> DatabaseState:
        """Which backend requests are served from right now."""
        if self._primary is None:
            return "memory"
        if self._schema_ready and self._failures == 0:
            try:
                await asyncio.wait_for(self._primary.ping(), HEALTH_CHECK_TIMEOUT_SECONDS)
            except Exception as error:
                self._record_failure(error)
            else:
                return "postgres"
        return "memory" if self._allow_fallback else "unavailable"

    # --- Breaker ---------------------------------------------------------------

    async def _prepare(self, primary: MeetingStoreBackend) -> None:
        await primary.prepare()
        self._schema_ready = True

    def _should_try_primary(self) -> bool:
        if self._primary is None:
            return False
        if self._failures == 0:
            return True
        return not self._probe_in_flight and self._clock() >= self._retry_at

    def _record_failure(self, error: BaseException) -> None:
        self._failures += 1
        delay = min(self._retry_base * 2 ** (self._failures - 1), self._retry_max)
        self._retry_at = self._clock() + delay
        detail = f"{type(error).__name__}: {error}"
        if self._failures == 1:
            logger.warning(
                "PostgreSQL unavailable (%s); %s. Retrying in %.0fs.",
                detail,
                "serving from memory" if self._allow_fallback else "failing requests with 503",
                delay,
            )
        else:
            logger.info(
                "PostgreSQL still unavailable after %d attempts (%s); next retry in %.0fs",
                self._failures,
                detail,
                delay,
            )

    def _record_success(self) -> None:
        if self._failures:
            logger.info(
                "PostgreSQL connection restored after %d failed attempt(s); using it again",
                self._failures,
            )
        self._failures = 0
        self._retry_at = 0.0

    async def _run(self, operation: Callable[[MeetingStoreBackend], Awaitable[T]]) -> T:
        primary = self._primary
        if primary is not None and self._should_try_primary():
            probing = self._failures > 0
            self._probe_in_flight = probing
            try:
                if not self._schema_ready:
                    await self._prepare(primary)
                result = await operation(primary)
            except Exception as error:
                if self._schema_ready and not is_unavailable_error(error):
                    raise
                self._record_failure(error)
            else:
                self._record_success()
                return result
            finally:
                if probing:
                    self._probe_in_flight = False

        if primary is not None and not self._allow_fallback:
            raise DatabaseUnavailableError("PostgreSQL is unavailable")
        return await operation(self._fallback)

    # --- Store API -------------------------------------------------------------

    async def create_meeting(self, title: str) -> Meeting:
        return await self._run(lambda store: store.create_meeting(title))

    async def get_meeting(self, meeting_id: str) -> Meeting | None:
        return await self._run(lambda store: store.get_meeting(meeting_id))

    async def list_meetings(self, *, limit: int, offset: int) -> list[Meeting]:
        return await self._run(lambda store: store.list_meetings(limit=limit, offset=offset))

    async def end_meeting(self, meeting_id: str) -> Meeting | None:
        return await self._run(lambda store: store.end_meeting(meeting_id))

    async def add_segment(self, segment: TranscriptSegment) -> TranscriptSegment:
        return await self._run(lambda store: store.add_segment(segment))

    async def get_segments(self, meeting_id: str) -> list[TranscriptSegment]:
        return await self._run(lambda store: store.get_segments(meeting_id))

    async def get_last_sequence(self, meeting_id: str) -> int:
        return await self._run(lambda store: store.get_last_sequence(meeting_id))

    async def save_insights(self, insights: MeetingInsights) -> MeetingInsights:
        return await self._run(lambda store: store.save_insights(insights))

    async def get_insights(self, meeting_id: str) -> MeetingInsights | None:
        return await self._run(lambda store: store.get_insights(meeting_id))


smart_meeting_store = SmartMeetingStore()
