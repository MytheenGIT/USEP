from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_tables(engine: AsyncEngine) -> None:
    """Create this service's own bookkeeping tables if missing (no migrations tool yet)."""
    import db.models  # noqa: F401  -- registers the models on Base.metadata

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if conn.dialect.name == "postgresql":
            # Append-only audit trail (spec 7.5): refuse UPDATE and DELETE, even for the table owner.
            await conn.execute(
                text(
                    "CREATE OR REPLACE FUNCTION audit_event_append_only() RETURNS trigger AS $$ "
                    "BEGIN RAISE EXCEPTION 'audit_event is append-only'; END; $$ LANGUAGE plpgsql"
                )
            )
            await conn.execute(text("DROP TRIGGER IF EXISTS audit_event_append_only ON audit_event"))
            await conn.execute(
                text(
                    "CREATE TRIGGER audit_event_append_only BEFORE UPDATE OR DELETE ON audit_event "
                    "FOR EACH ROW EXECUTE FUNCTION audit_event_append_only()"
                )
            )
