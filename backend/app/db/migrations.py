"""Run Alembic migrations from inside the application."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def alembic_config() -> Config:
    return Config(str(ALEMBIC_INI))


async def upgrade_to_head(engine: AsyncEngine) -> None:
    """Apply pending migrations on one of ``engine``'s connections.

    ``migrations/env.py`` takes an advisory lock, so replicas starting at the
    same time apply each revision once.
    """
    config = alembic_config()

    def _upgrade(connection: Connection) -> None:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

    async with engine.begin() as connection:
        await connection.run_sync(_upgrade)
