"""Example SyncService implementation.

Orchestrates one connector per source: reads the resume cursor, calls the
connector, hands off each raw payload to the Raw Payload Writer, persists
the new cursor, and records an audit event -- all through interfaces, so
the real (elsewhere-owned) implementations drop in without touching this
file.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import structlog

from common.connector_base import SourceConnector
from common.json_file_sink import JsonFileSink
from db.repository import SyncRunRepository
from common.interfaces.audit_writer import AuditEvent, AuditWriter
from common.interfaces.cursor_manager import CursorManager
from common.interfaces.raw_payload_writer import RawPayloadWriter
from common.sync_models import SyncResult, SyncStatus

logger = structlog.get_logger(__name__)


class SyncService:
    def __init__(
        self,
        connectors: dict[str, SourceConnector],
        cursor_manager: CursorManager,
        raw_payload_writer: RawPayloadWriter,
        audit_writer: AuditWriter,
        sync_run_repository: SyncRunRepository | None = None,
        json_sink: JsonFileSink | None = None,
    ) -> None:
        self._connectors = connectors
        self._cursor_manager = cursor_manager
        self._raw_payload_writer = raw_payload_writer
        self._audit_writer = audit_writer
        self._sync_run_repository = sync_run_repository
        self._json_sink = json_sink

    @property
    def available_sources(self) -> list[str]:
        return list(self._connectors.keys())

    async def _record_run(self, result: SyncResult) -> None:
        """Best-effort operational bookkeeping; must never fail the sync itself."""
        if self._json_sink:
            path = self._json_sink.write(result)
            logger.info("sync.saved_json", source=result.source.value, path=str(path))
        if not self._sync_run_repository:
            return
        try:
            await self._sync_run_repository.record(result)
        except Exception as exc:
            logger.warning("sync_run_repository.record_failed", source=result.source.value, error=str(exc))

    async def sync_source(self, source: str) -> SyncResult:
        connector = self._connectors.get(source)
        if connector is None:
            raise ValueError(f"No connector registered for source '{source}'")

        started_at = datetime.now(UTC)
        cursor = await self._cursor_manager.get_cursor(source)

        try:
            documents, new_cursor = await connector.fetch(cursor)
        except Exception as exc:  # connector failures must not take down the service
            finished_at = datetime.now(UTC)
            logger.error("sync.failed", source=source, error=str(exc))
            result = SyncResult(
                source=connector.source,
                status=SyncStatus.FAILED,
                started_at=started_at,
                finished_at=finished_at,
                documents=[],
                cursor=cursor,
                errors=[str(exc)],
            )
            await self._audit_writer.record(
                AuditEvent(source=source, action="sync", status=SyncStatus.FAILED.value, at=finished_at, details={"error": str(exc)})
            )
            await self._record_run(result)
            return result

        for document in documents:
            await self._raw_payload_writer.write(document.source.value, document.source_object_id, document.raw_payload)

        if new_cursor and new_cursor != cursor:
            await self._cursor_manager.set_cursor(source, new_cursor)

        finished_at = datetime.now(UTC)
        result = SyncResult(
            source=connector.source,
            status=SyncStatus.SUCCESS,
            started_at=started_at,
            finished_at=finished_at,
            documents=documents,
            cursor=new_cursor or cursor,
            errors=[],
        )

        await self._audit_writer.record(
            AuditEvent(
                source=source,
                action="sync",
                status=SyncStatus.SUCCESS.value,
                at=finished_at,
                details={"documents_count": result.documents_count, "cursor": result.cursor},
            )
        )
        await self._record_run(result)

        logger.info("sync.completed", source=source, documents_count=result.documents_count, cursor=result.cursor)
        return result

    async def sync_all(self) -> list[SyncResult]:
        return list(await asyncio.gather(*(self.sync_source(source) for source in self._connectors)))
