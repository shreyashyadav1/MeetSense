"""Alembic environment for the MeetSense schema.

Used both by the ``alembic`` CLI and by the application at startup; the
application passes its own connection in ``config.attributes["connection"]``.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db import models  # noqa: F401 - registers the tables on Base.metadata
from app.db.base import Base, build_engine

config = context.config
target_metadata = Base.metadata

# Held for the duration of the migration transaction so that two instances
# starting at once don't both try to apply the same revision.
MIGRATION_LOCK_ID = 7_265_406_573  # arbitrary, app-specific


def _database_url() -> str:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not set; there is no database to migrate.")
    return settings.database_url


def _run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        connection.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": MIGRATION_LOCK_ID})
        context.run_migrations()


async def _run_migrations_with_new_engine() -> None:
    engine = build_engine(
        _database_url(),
        disable_statement_cache=settings.db_disable_statement_cache,
        poolclass=NullPool,
    )
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run_migrations)
    finally:
        await engine.dispose()


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run_migrations(connection)
    else:
        asyncio.run(_run_migrations_with_new_engine())


# The application configures logging itself; only the CLI uses alembic.ini's.
if config.attributes.get("connection") is None and config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
