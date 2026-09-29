"""Alembic migrations against PostgreSQL."""

from __future__ import annotations

import asyncpg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.engine import Connection
from sqlalchemy.pool import NullPool

from app.db import models  # noqa: F401 - registers the tables
from app.db.base import Base, build_engine
from app.db.migrations import upgrade_to_head
from tests.conftest import asyncpg_dsn, recreate_database

pytestmark = pytest.mark.postgres

# What the application's former Base.metadata.create_all() produced.
LEGACY_SCHEMA = """
CREATE TABLE meetings (
    id VARCHAR NOT NULL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    ended_at TIMESTAMP WITH TIME ZONE
);
CREATE TABLE meeting_insights (
    id VARCHAR NOT NULL PRIMARY KEY,
    meeting_id VARCHAR NOT NULL UNIQUE REFERENCES meetings (id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    action_items JSON NOT NULL,
    decisions JSON NOT NULL,
    questions_raised JSON NOT NULL,
    follow_up_email TEXT NOT NULL,
    generated_at TIMESTAMP WITH TIME ZONE NOT NULL
);
CREATE TABLE transcript_segments (
    id VARCHAR NOT NULL PRIMARY KEY,
    meeting_id VARCHAR NOT NULL REFERENCES meetings (id) ON DELETE CASCADE,
    speaker VARCHAR(100) NOT NULL,
    text TEXT NOT NULL,
    timestamp FLOAT NOT NULL,
    confidence FLOAT NOT NULL,
    is_final BOOLEAN NOT NULL
);
"""


def _schema_diff(connection: Connection) -> list[object]:
    context = MigrationContext.configure(connection, opts={"compare_type": True})
    return compare_metadata(context, Base.metadata)


async def _migrate_and_diff(url: str) -> list[object]:
    engine = build_engine(url, poolclass=NullPool)
    try:
        await upgrade_to_head(engine)
        await upgrade_to_head(engine)  # idempotent
        async with engine.connect() as connection:
            return await connection.run_sync(_schema_diff)
    finally:
        await engine.dispose()


async def test_migrations_create_the_schema_the_models_describe(postgres_url: str) -> None:
    url = postgres_url.rsplit("/", 1)[0] + "/meetsense_test_fresh"
    await recreate_database(url)
    assert await _migrate_and_diff(url) == []


async def test_a_database_created_by_create_all_is_adopted(postgres_url: str) -> None:
    url = postgres_url.rsplit("/", 1)[0] + "/meetsense_test_legacy"
    await recreate_database(url)
    connection = await asyncpg.connect(asyncpg_dsn(url))
    try:
        await connection.execute(LEGACY_SCHEMA)
        await connection.execute(
            "INSERT INTO meetings VALUES ('m1', 'Legacy', 'ended', now(), now())"
        )
        # Before sequences, a reconnect restarted timestamps at zero.
        for segment_id, timestamp in (("a", 5.0), ("b", 0.5), ("c", 2.0)):
            await connection.execute(
                "INSERT INTO transcript_segments"
                " VALUES ($1, 'm1', 'Speaker 1', 'x', $2, 0.9, true)",
                segment_id,
                timestamp,
            )
    finally:
        await connection.close()

    assert await _migrate_and_diff(url) == []

    connection = await asyncpg.connect(asyncpg_dsn(url))
    try:
        rows = await connection.fetch(
            "SELECT id, sequence FROM transcript_segments ORDER BY sequence"
        )
        assert [(row["id"], row["sequence"]) for row in rows] == [("b", 1), ("c", 2), ("a", 3)]
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == "0001"
    finally:
        await connection.close()
