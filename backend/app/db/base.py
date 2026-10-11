"""SQLAlchemy declarative base and the lazily created async engine."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

CONNECT_TIMEOUT_SECONDS = 5.0
# Upper bound for a single statement, so a stalled network path surfaces as an
# error (and triggers the memory fallback) instead of hanging a request.
COMMAND_TIMEOUT_SECONDS = 15.0


class Base(DeclarativeBase):
    pass


def build_engine(url: str, *, disable_statement_cache: bool = False, **kwargs: Any) -> AsyncEngine:
    connect_args: dict[str, Any] = {
        "timeout": CONNECT_TIMEOUT_SECONDS,
        "command_timeout": COMMAND_TIMEOUT_SECONDS,
    }
    if disable_statement_cache:
        # Transaction-mode poolers hand each transaction to an arbitrary server
        # connection, so asyncpg must not rely on (or name-clash with) prepared
        # statements left behind on another connection.
        connect_args |= {
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
        }
    kwargs.setdefault("pool_pre_ping", True)
    if "poolclass" not in kwargs:
        kwargs.setdefault("pool_timeout", CONNECT_TIMEOUT_SECONDS)
    return create_async_engine(url, connect_args=connect_args, **kwargs)


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = build_engine(
            settings.database_url,
            disable_statement_cache=settings.db_disable_statement_cache,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def dispose_engine() -> None:
    """Close pooled connections; the next ``get_engine()`` builds a fresh engine."""
    global _engine, _session_factory
    engine, _engine, _session_factory = _engine, None, None
    if engine is not None:
        await engine.dispose()
