from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models import SyncRunRecord
from common.sync_models import SyncResult


class SyncRunRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record(self, result: SyncResult) -> None:
        async with self._session_factory() as session:
            session.add(
                SyncRunRecord(
                    source=result.source.value,
                    status=result.status.value,
                    started_at=result.started_at,
                    finished_at=result.finished_at,
                    documents_count=result.documents_count,
                    cursor=result.cursor,
                    errors=result.errors,
                )
            )
            await session.commit()

    async def list_recent(self, limit: int = 20) -> list[SyncRunRecord]:
        async with self._session_factory() as session:
            rows = await session.execute(
                select(SyncRunRecord).order_by(SyncRunRecord.finished_at.desc()).limit(limit)
            )
            return list(rows.scalars().all())
