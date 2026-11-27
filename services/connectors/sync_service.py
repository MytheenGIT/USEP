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
from common.interfaces.object_index import InMemoryObjectIndex, ObjectIndex
from common.checksum import payload_checksum
from common.interfaces.raw_event_publisher import NullRawEventPublisher, RawEvent, RawEventPublisher
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
        raw_event_publisher: RawEventPublisher | None = None,
        object_index: ObjectIndex | None = None,
        initial_cursor: str | None = None,
        max_documents_per_scope: int | None = None,
    ) -> None:
        """``initial_cursor``: where a scope with no stored cursor starts (a backfill start date). None means everything.
        ``max_documents_per_scope``: land at most this many objects per scope per run, oldest first. The cursor stops at the
        last one landed, so a large first sync completes over several runs instead of overrunning a Lambda timeout."""
        self._object_index = object_index or InMemoryObjectIndex()
        self._initial_cursor = initial_cursor or None
        self._max_documents = max_documents_per_scope or None
        self._connectors = connectors
        self._cursor_manager = cursor_manager
        self._raw_payload_writer = raw_payload_writer
        self._audit_writer = audit_writer
        self._sync_run_repository = sync_run_repository
        self._json_sink = json_sink
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._raw_event_publisher = raw_event_publisher or NullRawEventPublisher()

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
        """Make each raw payload durable, then announce it. A failure at either step becomes an object error, so the
        cursor will not pass that object.

        Order matters (ingestion diagram, B): the snapshot must exist before its event is published, because the event
        carries only a reference to it. A retry repeats both steps safely: snapshots are keyed by checksum (writing the
        same payload again is a no-op) and consumers are idempotent (the bus delivers at least once).
        """
        landed: list[SourceDocument] = []
        errors = list(fetched.errors)
        for document in fetched.documents:
            try:
                snapshot_ref = await self._raw_payload_writer.write(
                    document.source.value, document.source_object_id, document.raw_payload
                )
                await self._raw_event_publisher.publish(
                    RawEvent(
                        source=document.source.value,
                        source_type=document.source_type,
                        source_ref=document.source_object_id,
                        source_url=document.source_url,
                        snapshot_ref=snapshot_ref,
                        checksum=payload_checksum(document.raw_payload),
                        retrieved_at=document.retrieved_at,
                        scope=document.scope,
                        source_version=document.source_version,
                        acl=document.acl,
                    )
                )
                landed.append(document)
            except Exception as exc:
                errors.append(
                    ObjectError(
                        scope=scope,
                        object_id=document.source_object_id,
                        source_version=document.source_version,
                        error=f"raw landing failed: {exc}",
                    )
                )
        return ScopeFetch(documents=landed, errors=errors)

    async def _sync_scope(self, run_id: str, source: str, connector: SourceConnector, scope: str,
                          full: bool = False) -> tuple[ScopeFetch, str | None, bool, bool]:
        """Returns (fetched, new_cursor, scope_failed, truncated).

        ``full`` re-reads the whole scope ignoring the cursor, to pick up changes the source does not stamp with an
        updated time (a permission change). The stored cursor never moves backwards, and the run-size cap is not applied,
        so a full refresh is never left half done."""
        key = cursor_key(source, scope)
        stored = await self._cursor_manager.get_cursor(key)
        cursor = stored or self._initial_cursor
        try:
            fetched = await connector.fetch_scope(scope, None if full else cursor)
        except Exception as exc:  # the scope itself could not be read
            logger.error("sync.scope_failed", source=source, scope=scope, run_id=run_id, error=str(exc))
            await self._audit(source, "sync_scope", SyncStatus.FAILED.value, {"run_id": run_id, "scope": scope, "error": str(exc)})
            return ScopeFetch(errors=[ObjectError(scope=scope, error=str(exc))]), stored, True, False

        truncated = False
        if self._max_documents and not full and len(fetched.documents) > self._max_documents:
            # Oldest first, objects with no version first (so they cannot starve). The cursor then stops at the last
            # one landed; what was cut is fetched again next run because fetches are ">= cursor".
            ordered = sorted(fetched.documents, key=lambda d: (d.source_version is not None, d.source_version or ""))
            fetched = ScopeFetch(documents=ordered[: self._max_documents], errors=fetched.errors)
            truncated = True

        fetched = await self._land_raw(run_id, fetched, scope)
        await self._object_index.add(key, {d.source_object_id for d in fetched.documents})
        new_cursor = next_cursor(stored if full else cursor, fetched)
        if new_cursor and new_cursor != stored:
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
            SyncStatus.PARTIAL.value if fetched.errors or truncated else SyncStatus.SUCCESS.value,
            {
                "run_id": run_id,
                "scope": scope,
                "documents_count": len(fetched.documents),
                "errors_count": len(fetched.errors),
                "cursor_before": stored,
                "cursor_after": new_cursor,
                "full": full,
                "truncated": truncated,
            },
        )
        return fetched, new_cursor, False, truncated

    async def sync_source(self, source: str, scopes: list[str] | None = None, full: bool = False) -> SyncResult:
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
        truncated_scopes: list[str] = []
        failed_scopes = 0

        for scope in target_scopes:
            lock = self._locks.setdefault((source, scope), asyncio.Lock())
            if lock.locked():
                logger.info("sync.scope_skipped_already_running", source=source, scope=scope)
                skipped.append(scope)
                continue
            async with lock:
                fetched, new_cursor, scope_failed, truncated = await self._sync_scope(
                    run_id, source, connector, scope, full)
            if truncated:
                truncated_scopes.append(scope)
            documents.extend(fetched.documents)
            object_errors.extend(fetched.errors)
            cursors[scope] = new_cursor
            failed_scopes += int(scope_failed)

        attempted = len(target_scopes) - len(skipped)
        if attempted and failed_scopes == attempted:
            status = SyncStatus.FAILED
        elif object_errors or skipped or truncated_scopes:
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
            truncated_scopes=truncated_scopes,
            object_errors=object_errors,
            errors=[str(e) for e in object_errors],
        )
        await self._audit(
            source,
            "sync",
            status.value,
            {"run_id": run_id, "documents_count": result.documents_count, "errors_count": len(object_errors), "skipped_scopes": skipped,
             "truncated_scopes": truncated_scopes, "full": full},
        )
        await self._record_run(result)
        logger.info("sync.completed", source=source, run_id=run_id, status=status.value, documents_count=result.documents_count)
        return result

    async def sync_all(self) -> list[SyncResult]:
        return list(await asyncio.gather(*(self.sync_source(source) for source in self._connectors)))
