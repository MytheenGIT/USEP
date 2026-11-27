"""SyncService: runs connectors scope by scope through the foundation's ingestion path.

For each scope: the Cursor Manager gives the resume point (stored cursor minus the overlap
window), the connector fetches, each document goes to the Raw Payload Writer (scan, dedupe,
encrypt, object store, index, publish), and the cursor moves only after the writes, to the
newest version that is safe. A write that failed holds the cursor back at that object, so it
is fetched again next run (LLD Table 1: checkpoint only after publish is acknowledged).

Cursors are keyed ``<source>:<scope>:<lane>`` so every JQL query, repository, space and file
advances independently. A per-scope lock stops a manual trigger and a scheduled run from
syncing the same scope at the same time.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

import structlog

from common.client_base import error_detail
from common.connector_base import ObjectError, ScopeFetch, SourceCheck, SourceConnector, next_cursor
from common.interfaces.audit_writer import AuditEvent, AuditWriter
from common.json_file_sink import JsonFileSink
from common.source_document import SourceDocument
from common.sync_models import SyncResult, SyncStatus
from db.repository import SyncRunRepository
from usep.core.ids import new_id
from usep.ingestion.cursor.manager import CursorManager
from usep.ingestion.raw.writer import Outcome, RawPayloadWriter

logger = structlog.get_logger(__name__)

_KEY_SAFE_SCOPE = re.compile(r"[A-Za-z0-9._/-]{1,80}")


def scope_id(scope: str) -> str:
    """The scope as it appears in object keys and the raw index.

    A repository path or space key is used as it is. A JQL query or a URL can be long and holds
    spaces and quotes, and an S3 key is limited to 1024 bytes, so those become a short stable hash.
    The readable scope stays in cursors, audit events and the run snapshot.
    """
    return scope if _KEY_SAFE_SCOPE.fullmatch(scope) else "s-" + hashlib.sha256(scope.encode()).hexdigest()[:16]


class SyncService:
    def __init__(
        self,
        connectors: dict[str, SourceConnector],
        cursor_manager: CursorManager,
        writer_factory: Callable[[UUID, AuditWriter], RawPayloadWriter],
        audit_writer_factory: Callable[[UUID], AuditWriter],
        sync_run_repository: SyncRunRepository | None = None,
        json_sink: JsonFileSink | None = None,
        record_snapshot: Callable[[UUID, str, list[str]], Awaitable[None]] | None = None,
    ) -> None:
        self._connectors = connectors
        self._cursor_manager = cursor_manager
        self._writer_factory = writer_factory  # the writer is bound to one run
        self._audit_writer_factory = audit_writer_factory  # one audit chain per run
        self._record_snapshot = record_snapshot
        self._sync_run_repository = sync_run_repository
        self._json_sink = json_sink
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    @property
    def available_sources(self) -> list[str]:
        return list(self._connectors.keys())

    def scopes(self, source: str) -> list[str]:
        return list(self._get_connector(source).scopes)

    @property
    def has_dynamic_scopes(self) -> bool:
        """True when some connector finds scopes on its own (GitLab member repositories)."""
        return any(hasattr(c, "refresh_scopes") for c in self._connectors.values())

    async def refresh_scopes(self) -> dict[str, str]:
        """Let connectors re-discover their scopes. A failure keeps the previous scopes and is logged.

        Returns the reason for each source that failed, so a caller that must not treat "could not look" as
        "found nothing" (a console configuration) can tell the difference.
        """
        failures: dict[str, str] = {}
        for source, connector in self._connectors.items():
            refresh = getattr(connector, "refresh_scopes", None)
            if refresh is None:
                continue
            try:
                await refresh()
            except Exception as exc:  # noqa: BLE001 -- the source may be down; the last known scopes stay
                logger.warning("sync.scope_refresh_failed", source=source, error=str(exc))
                failures[source] = error_detail(exc)
        return failures

    async def check_source(self, source: str) -> SourceCheck:
        """Ask the source whether the saved credentials and scopes work (read-only calls)."""
        connector = self._get_connector(source)
        check = getattr(connector, "check", None)
        if check is None:
            raise NotImplementedError(f"The {source} connector has no check")
        return await check()

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

    async def _audit(self, audit: AuditWriter, source: str, action: str, status: str, details: dict) -> None:
        try:
            await audit.record(AuditEvent(source=source, action=action, status=status, at=datetime.now(UTC), details=details))
        except Exception as exc:
            logger.warning("audit_writer.record_failed", source=source, action=action, error=str(exc))

    async def _land_raw(
        self, writer: RawPayloadWriter, fetched: ScopeFetch, scope: str
    ) -> tuple[ScopeFetch, list[SourceDocument], list[str]]:
        """Write each document. Returns (what to report, documents the cursor may pass, outcomes).

        A failed write becomes an object error and is not in the cursor list, so the cursor
        will not pass it. A quarantined document is resolved for the cursor but is left out of
        what is reported, because it may hold secrets or personal data.
        """
        reported: list[SourceDocument] = []
        resolved: list[SourceDocument] = []
        outcomes: list[str] = []
        errors = list(fetched.errors)
        for document in fetched.documents:
            payload = {
                **document.raw_payload,
                "_usep": {
                    "object_type": document.source_type,
                    "scope_id": scope_id(scope),
                    "checkpoint": document.source_version or document.retrieved_at.isoformat(),
                    "source_version": document.source_version,
                    "extracted_at": document.retrieved_at,
                    "acl": document.acl,
                },
            }
            try:
                result = await writer.write(document.source.value, document.source_object_id, payload)
                failure = f"raw payload write failed: {result.reason}" if result.outcome == Outcome.FAILED else None
            except Exception as exc:  # the writer's own contract was broken (for example no envelope)
                failure = f"raw payload write failed: {exc}"
            if failure:
                errors.append(
                    ObjectError(
                        scope=scope,
                        object_id=document.source_object_id,
                        source_version=document.source_version,
                        error=failure,
                    )
                )
                continue
            resolved.append(document)
            outcomes.append(result.outcome)
            if result.outcome != Outcome.QUARANTINED:
                reported.append(document)
        return ScopeFetch(documents=reported, errors=errors), resolved, outcomes

    async def _sync_scope(
        self, run_id: UUID, source: str, connector: SourceConnector, scope: str, writer: RawPayloadWriter,
        audit: AuditWriter,
    ) -> tuple[ScopeFetch, str | None, bool]:
        """Returns (fetched, new_cursor, scope_failed)."""
        batch = None
        try:
            batch = await self._cursor_manager.start_batch(source, scope)
            fetched = await connector.fetch_scope(scope, batch.fetch_from)
        except Exception as exc:  # the cursor or the scope itself could not be read
            logger.error("sync.scope_failed", source=source, scope=scope, run_id=str(run_id), error=str(exc))
            await self._audit(audit, source, "sync_scope", SyncStatus.FAILED.value, {"run_id": str(run_id), "scope": scope, "error": str(exc)})
            return ScopeFetch(errors=[ObjectError(scope=scope, error=str(exc))]), batch.cursor if batch else None, True

        fetched, resolved, outcomes = await self._land_raw(writer, fetched, scope)
        new_cursor = next_cursor(batch.cursor, ScopeFetch(documents=resolved, errors=fetched.errors))
        if new_cursor and new_cursor != batch.cursor:
            try:
                await self._cursor_manager.advance(batch, new_cursor, outcomes)
            except Exception as exc:  # data is stored; the next run fetches it again and the writer dedupes
                logger.error("sync.cursor_not_saved", source=source, scope=scope, run_id=str(run_id), error=str(exc))
                fetched.errors.append(ObjectError(scope=scope, error=f"cursor not saved: {exc}"))
                new_cursor = batch.cursor

        for error in fetched.errors:
            await self._audit(
                audit,
                source,
                "fetch_object",
                SyncStatus.FAILED.value,
                {"run_id": str(run_id), "scope": scope, "object_id": error.object_id, "error": error.error},
            )
        await self._audit(
            audit,
            source,
            "sync_scope",
            SyncStatus.PARTIAL.value if fetched.errors else SyncStatus.SUCCESS.value,
            {
                "run_id": str(run_id),
                "scope": scope,
                "documents_count": len(fetched.documents),
                "quarantined_count": len(resolved) - len(fetched.documents),
                "errors_count": len(fetched.errors),
                "cursor_before": batch.cursor,
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

        run_id = new_id()
        audit = self._audit_writer_factory(run_id)
        writer = self._writer_factory(run_id, audit)  # same audit writer, so the run has one hash chain
        started_at = datetime.now(UTC)
        if self._record_snapshot:
            try:
                await self._record_snapshot(run_id, source, target_scopes)
            except Exception as exc:  # provenance bookkeeping; the run still goes ahead
                logger.warning("run_snapshot.record_failed", source=source, run_id=str(run_id), error=str(exc))
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
                fetched, new_cursor, scope_failed = await self._sync_scope(run_id, source, connector, scope, writer, audit)
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
            run_id=str(run_id),
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
            audit,
            source,
            "sync",
            status.value,
            {"run_id": str(run_id), "documents_count": result.documents_count, "errors_count": len(object_errors), "skipped_scopes": skipped},
        )
        await self._record_run(result)
        logger.info("sync.completed", source=source, run_id=str(run_id), status=status.value, documents_count=result.documents_count)
        return result

    async def sync_all(self) -> list[SyncResult]:
        return list(await asyncio.gather(*(self.sync_source(source) for source in self._connectors)))
