async def create_tables() -> None:
    """Create all tables if they don't exist. Call this once at app startup."""
    from app.db.base import Base, get_engine
    from app.db import models  # noqa: F401 — registers ORM models with Base.metadata

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
