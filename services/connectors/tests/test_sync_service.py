from __future__ import annotations

import asyncio

import pytest

from common.connector_base import ObjectError, ScopeFetch, next_cursor
from common.source_document import SourceType
from common.sync_models import SyncStatus
from sync_service import SyncService, scope_id
from tests.conftest import FakeConnector, RecordingWriter, make_source_document
from usep.ingestion.raw.writer import Outcome


def cursor_key(source: str, scope: str) -> str:
    return f"{source}:{scope}:live"


def _service(connectors, cursor_manager, raw_payload_writer, audit_writer) -> SyncService:
    return SyncService(
        connectors=connectors,
        cursor_manager=cursor_manager,
        writer_factory=lambda _run_id, _audit: raw_payload_writer,
        audit_writer_factory=lambda _run_id: audit_writer,
    )


async def test_sync_source_success_persists_cursor_per_scope(cursor_manager, raw_payload_writer, audit_writer, cursor_store) -> None:
    connector = FakeConnector(SourceType.JIRA, [make_source_document()], scopes=["project = A", "project = B"])
    service = _service({"jira": connector}, cursor_manager, raw_payload_writer, audit_writer)

    result = await service.sync_source("jira")

    assert result.status == SyncStatus.SUCCESS
    assert result.run_id
    assert result.documents_count == 2
    assert await cursor_store.get_cursor(cursor_key("jira", "project = A")) == "2026-01-01T00:00:00.000Z"
    assert await cursor_store.get_cursor(cursor_key("jira", "project = B")) == "2026-01-01T00:00:00.000Z"
    assert [e.action for e in audit_writer.events] == ["sync_scope", "sync_scope", "sync"]
    assert all(e.details["run_id"] == result.run_id for e in audit_writer.events)


async def test_sync_only_requested_scope(cursor_manager, raw_payload_writer, audit_writer) -> None:
    connector = FakeConnector(SourceType.JIRA, [make_source_document()], scopes=["a", "b"])
    service = _service({"jira": connector}, cursor_manager, raw_payload_writer, audit_writer)

    await service.sync_source("jira", scopes=["b"])

    assert [scope for scope, _ in connector.calls] == ["b"]
    with pytest.raises(ValueError):
        await service.sync_source("jira", scopes=["nope"])


async def test_scope_failure_is_captured_not_raised(cursor_manager, raw_payload_writer, audit_writer, cursor_store) -> None:
    service = _service({"jira": FakeConnector(SourceType.JIRA, [], raises=True)}, cursor_manager, raw_payload_writer, audit_writer)

    result = await service.sync_source("jira")

    assert result.status == SyncStatus.FAILED
    assert result.errors == ["default: boom"]
    assert await cursor_store.get_cursor(cursor_key("jira", "default")) is None


async def test_object_error_gives_partial_and_holds_cursor_at_failed_version(cursor_manager, raw_payload_writer, audit_writer, cursor_store) -> None:
    error = ObjectError(scope="default", object_id="ABC-2", source_version="2025-12-31T00:00:00.000Z", error="bad")
    connector = FakeConnector(SourceType.JIRA, [make_source_document()], errors=[error])
    service = _service({"jira": connector}, cursor_manager, raw_payload_writer, audit_writer)

    result = await service.sync_source("jira")

    assert result.status == SyncStatus.PARTIAL
    assert result.documents_count == 1
    assert await cursor_store.get_cursor(cursor_key("jira", "default")) == "2025-12-31T00:00:00.000Z"


async def test_raw_write_failure_does_not_advance_cursor(cursor_manager, audit_writer, cursor_store) -> None:
    class FailingWriter:
        async def write(self, source, source_object_id, raw_payload):
            raise OSError("disk full")

    service = _service({"jira": FakeConnector(SourceType.JIRA, [make_source_document()])}, cursor_manager, FailingWriter(), audit_writer)

    result = await service.sync_source("jira")

    assert result.status == SyncStatus.PARTIAL
    assert result.documents_count == 0
    assert await cursor_store.get_cursor(cursor_key("jira", "default")) == "2026-01-01T00:00:00.000Z"


async def test_failed_write_outcome_holds_the_cursor_back(cursor_manager, cursor_store, audit_writer) -> None:
    older = make_source_document(source_object_id="ABC-1", source_version="2026-01-01T00:00:00.000Z")
    newer = make_source_document(source_object_id="ABC-2", source_version="2026-01-02T00:00:00.000Z")

    class FailsOnSecond(RecordingWriter):
        async def write(self, source, source_object_id, raw_payload):
            self.outcome = Outcome.FAILED if source_object_id == "ABC-1" else Outcome.WRITTEN
            return await super().write(source, source_object_id, raw_payload)

    service = _service({"jira": FakeConnector(SourceType.JIRA, [older, newer])}, cursor_manager, FailsOnSecond(), audit_writer)

    result = await service.sync_source("jira")

    assert result.status == SyncStatus.PARTIAL
    assert [d.source_object_id for d in result.documents] == ["ABC-2"]
    assert result.errors == ["default/ABC-1: raw payload write failed: test"]
    assert await cursor_store.get_cursor(cursor_key("jira", "default")) == "2026-01-01T00:00:00.000Z"


async def test_quarantined_document_moves_the_cursor_but_is_not_reported(cursor_manager, cursor_store, audit_writer) -> None:
    writer = RecordingWriter(Outcome.QUARANTINED)
    service = _service({"jira": FakeConnector(SourceType.JIRA, [make_source_document()])}, cursor_manager, writer, audit_writer)

    result = await service.sync_source("jira")

    assert result.documents_count == 0 and result.errors == []
    assert await cursor_store.get_cursor(cursor_key("jira", "default")) == "2026-01-01T00:00:00.000Z"


async def test_writer_receives_the_usep_envelope(cursor_manager, raw_payload_writer, audit_writer) -> None:
    service = _service({"jira": FakeConnector(SourceType.JIRA, [make_source_document()], scopes=["project = A"])}, cursor_manager, raw_payload_writer, audit_writer)

    await service.sync_source("jira")

    source, object_id, payload = raw_payload_writer.calls[0]
    assert (source, object_id) == ("jira", "ABC-1")
    envelope = payload["_usep"]
    assert (envelope["object_type"], envelope["scope_id"], envelope["checkpoint"]) == ("issue", scope_id("project = A"), "2026-01-01T00:00:00.000Z")
    assert envelope["source_version"] == "2026-01-01T00:00:00.000Z" and envelope["extracted_at"] is not None
    assert envelope["acl"] == {}
    assert payload["key"] == "ABC-1"


async def test_cursor_store_failure_fails_the_scope_not_the_run(cursor_manager, audit_writer, raw_payload_writer) -> None:
    class BrokenStore:
        async def get_cursor(self, key):
            raise ConnectionError("db down")

        async def set_cursor(self, key, cursor):
            raise ConnectionError("db down")

    from usep.ingestion.cursor.manager import CursorManager

    service = _service({"jira": FakeConnector(SourceType.JIRA, [make_source_document()])}, CursorManager(BrokenStore()), raw_payload_writer, audit_writer)

    result = await service.sync_source("jira")

    assert result.status == SyncStatus.FAILED
    assert raw_payload_writer.calls == []


async def test_concurrent_run_of_same_scope_is_skipped(cursor_manager, raw_payload_writer, audit_writer) -> None:
    started, release = asyncio.Event(), asyncio.Event()

    class SlowConnector(FakeConnector):
        async def fetch_scope(self, scope, cursor):
            started.set()
            await release.wait()
            return ScopeFetch()

    service = _service({"jira": SlowConnector(SourceType.JIRA, [])}, cursor_manager, raw_payload_writer, audit_writer)
    first = asyncio.create_task(service.sync_source("jira"))
    await started.wait()
    second = await service.sync_source("jira")
    release.set()
    await first

    assert second.skipped_scopes == ["default"]
    assert second.status == SyncStatus.PARTIAL


async def test_sync_source_unknown_source_raises(cursor_manager, raw_payload_writer, audit_writer) -> None:
    with pytest.raises(ValueError):
        await _service({}, cursor_manager, raw_payload_writer, audit_writer).sync_source("jira")


async def test_sync_all_runs_every_connector(cursor_manager, raw_payload_writer, audit_writer) -> None:
    service = _service(
        {
            "jira": FakeConnector(SourceType.JIRA, [make_source_document()]),
            "gitlab": FakeConnector(SourceType.GITLAB, [make_source_document(SourceType.GITLAB, "1!1")]),
        },
        cursor_manager,
        raw_payload_writer,
        audit_writer,
    )

    results = await service.sync_all()

    assert {r.source for r in results} == {SourceType.JIRA, SourceType.GITLAB}
    assert all(r.status == SyncStatus.SUCCESS for r in results)


def test_next_cursor_rules() -> None:
    doc = make_source_document(source_version="2026-01-02T00:00:00.000Z")
    assert next_cursor(None, ScopeFetch(documents=[doc])) == "2026-01-02T00:00:00.000Z"
    assert next_cursor("2026-01-05T00:00:00.000Z", ScopeFetch(documents=[doc])) == "2026-01-05T00:00:00.000Z"
    assert next_cursor("2026-01-01T00:00:00.000Z", ScopeFetch()) == "2026-01-01T00:00:00.000Z"
    unknown = ObjectError(scope="s", error="x")
    assert next_cursor("2026-01-01T00:00:00.000Z", ScopeFetch(documents=[doc], errors=[unknown])) == "2026-01-01T00:00:00.000Z"
