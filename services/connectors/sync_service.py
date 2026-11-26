"""SyncService: runs connectors scope by scope.

For each scope it reads the resume cursor, calls the connector, hands each
raw payload to the Raw Payload Writer, derives and persists the new cursor,
and records audit events -- all through interfaces, so the real
(elsewhere-owned) implementations drop in without touching this file.

Cursor keys are ``<source>:<scope>`` so every JQL query, repository, space
and file advances independently (spec Module 2: cursors per source item).
A per-scope lock stops a manual trigger and a scheduled run from syncing
the same scope at the same time.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import structlog

from common.connector_base import ObjectError, ScopeFetch, SourceConnector, next_cursor
from common.interfaces.audit_writer import AuditEvent, AuditWriter
from common.interfaces.cursor_manager import CursorManager
from common.interfaces.raw_payload_writer import RawPayloadWriter
from common.json_file_sink import JsonFileSink
from common.source_document import SourceDocument
from common.sync_models import SyncResult, SyncStatus
from db.repository import SyncRunRepository

logger = structlog.get_logger(__name__)


def _new_run_id() -> str:
    # LLD Section 1: UUID v7 so ids sort by creation time (Python 3.14+); v4 otherwise.
    factory = getattr(uuid, "uuid7", uuid.uuid4)
    return str(factory())


def cursor_key(source: str, scope: str) -> str:
    return f"{source}:{scope}"


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
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    @property
    def available_sources(self) -> list[str]:
        return list(self._connectors.keys())

    def scopes(self, source: str) -> list[str]:
        return list(self._get_connector(source).scopes)

    def _get_connector(self, source: str) -> SourceConnector:
        connector = self._connectors.get(source)
        if connector is None:
            raise ValueError(f"No connector registered for source '{source}'")
        return connector

    async def _record_run(self, result: SyncResult) -> None:
        """Best-effort operational bookkeeping; must never fail the sync itself."""
        if self._json_sink:
            try:
                path = self._json_sink.write(result)
                logger.info("sync.saved_json", source=result.source.value, run_id=result.run_id, path=str(path))
            except Exception as exc:
                logger.warning("json_sink.write_failed", source=result.source.value, error=str(exc))
        if self._sync_run_repository:
            try:
                await self._sync_run_repository.record(result)
            except Exception as exc:
                logger.warning("sync_run_repository.record_failed", source=result.source.value, error=str(exc))

    async def _audit(self, source: str, action: str, status: str, details: dict) -> None:
        try:
            await self._audit_writer.record(
                AuditEvent(source=source, action=action, status=status, at=datetime.now(UTC), details=details)
            )
        except Exception as exc:
            logger.warning("audit_writer.record_failed", source=source, action=action, error=str(exc))

    async def _land_raw(self, run_id: str, fetched: ScopeFetch, scope: str) -> ScopeFetch:
        """Write raw payloads; a failed write becomes an object error so the cursor won't pass it."""
        landed: list[SourceDocument] = []
        errors = list(fetched.errors)
        for document in fetched.documents:
            try:
                await self._raw_payload_writer.write(
                    document.source.value, document.source_object_id, document.raw_payload
                )
                landed.append(document)
            except Exception as exc:
                errors.append(
                    ObjectError(
                        scope=scope,
                        object_id=document.source_object_id,
                        source_version=document.source_version,
                        error=f"raw payload write failed: {exc}",
                    )
                )
        return ScopeFetch(documents=landed, errors=errors)

    async def _sync_scope(self, run_id: str, source: str, connector: SourceConnector, scope: str) -> tuple[ScopeFetch, str | None, bool]:
        """Returns (fetched, new_cursor, scope_failed)."""
        key = cursor_key(source, scope)
        cursor = await self._cursor_manager.get_cursor(key)
        try:
            fetched = await connector.fetch_scope(scope, cursor)
        except Exception as exc:  # the scope itself could not be read
            logger.error("sync.scope_failed", source=source, scope=scope, run_id=run_id, error=str(exc))
            await self._audit(source, "sync_scope", SyncStatus.FAILED.value, {"run_id": run_id, "scope": scope, "error": str(exc)})
            return ScopeFetch(errors=[ObjectError(scope=scope, error=str(exc))]), cursor, True

        fetched = await self._land_raw(run_id, fetched, scope)
        new_cursor = next_cursor(cursor, fetched)
        if new_cursor and new_cursor != cursor:
            await self._cursor_manager.set_cursor(key, new_cursor)

        for error in fetched.errors:
            await self._audit(
                source,
                "fetch_object",
                SyncStatus.FAILED.value,
                {"run_id": run_id, "scope": scope, "object_id": error.object_id, "error": error.error},
            )
        await self._audit(
            source,
            "sync_scope",
            SyncStatus.PARTIAL.value if fetched.errors else SyncStatus.SUCCESS.value,
            {
                "run_id": run_id,
                "scope": scope,
                "documents_count": len(fetched.documents),
                "errors_count": len(fetched.errors),
                "cursor_before": cursor,
                "cursor_after": new_cursor,
            },
        )
        return fetched, new_cursor, False

    async def sync_source(self, source: str, scopes: list[str] | None = None) -> SyncResult:
        connector = self._get_connector(source)
        configured = list(connector.scopes)
        if scopes is not None:
            unknown = [s for s in scopes if s not in configured]
            if unknown:
                raise ValueError(f"Unknown scope(s) for source '{source}': {unknown}")
        target_scopes = scopes if scopes is not None else configured

        run_id = _new_run_id()
        started_at = datetime.now(UTC)
        documents: list[SourceDocument] = []
        object_errors: list[ObjectError] = []
        cursors: dict[str, str | None] = {}
        skipped: list[str] = []
        failed_scopes = 0

        for scope in target_scopes:
            lock = self._locks.setdefault((source, scope), asyncio.Lock())
            if lock.locked():
                logger.info("sync.scope_skipped_already_running", source=source, scope=scope)
                skipped.append(scope)
                continue
            async with lock:
                fetched, new_cursor, scope_failed = await self._sync_scope(run_id, source, connector, scope)
            documents.extend(fetched.documents)
            object_errors.extend(fetched.errors)
            cursors[scope] = new_cursor
            failed_scopes += int(scope_failed)

        attempted = len(target_scopes) - len(skipped)
        if attempted and failed_scopes == attempted:
            status = SyncStatus.FAILED
        elif object_errors or skipped:
            status = SyncStatus.PARTIAL
        else:
            status = SyncStatus.SUCCESS

        result = SyncResult(
            run_id=run_id,
            source=connector.source,
            status=status,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            documents=documents,
            cursors=cursors,
            skipped_scopes=skipped,
            object_errors=object_errors,
            errors=[str(e) for e in object_errors],
        )
        await self._audit(
            source,
            "sync",
            status.value,
            {"run_id": run_id, "documents_count": result.documents_count, "errors_count": len(object_errors), "skipped_scopes": skipped},
        )
        await self._record_run(result)
        logger.info("sync.completed", source=source, run_id=run_id, status=status.value, documents_count=result.documents_count)
        return result

    async def sync_all(self) -> list[SyncResult]:
        return list(await asyncio.gather(*(self.sync_source(source) for source in self._connectors)))
