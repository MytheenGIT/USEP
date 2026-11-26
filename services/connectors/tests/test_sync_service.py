from __future__ import annotations

import asyncio

import pytest

from common.connector_base import ObjectError, ScopeFetch, next_cursor
from common.source_document import SourceType
from common.sync_models import SyncStatus
from sync_service import SyncService, cursor_key
from tests.conftest import FakeConnector, make_source_document


def _service(connectors, cursor_manager, raw_payload_writer, audit_writer) -> SyncService:
    return SyncService(
        connectors=connectors,
        cursor_manager=cursor_manager,
        raw_payload_writer=raw_payload_writer,
        audit_writer=audit_writer,
    )


async def test_sync_source_success_persists_cursor_per_scope(cursor_manager, raw_payload_writer, audit_writer) -> None:
    connector = FakeConnector(SourceType.JIRA, [make_source_document()], scopes=["project = A", "project = B"])
    service = _service({"jira": connector}, cursor_manager, raw_payload_writer, audit_writer)

    result = await service.sync_source("jira")

    assert result.status == SyncStatus.SUCCESS
    assert result.run_id
    assert result.documents_count == 2
    assert await cursor_manager.get_cursor(cursor_key("jira", "project = A")) == "2026-01-01T00:00:00.000Z"
    assert await cursor_manager.get_cursor(cursor_key("jira", "project = B")) == "2026-01-01T00:00:00.000Z"
    assert [e.action for e in audit_writer.events] == ["sync_scope", "sync_scope", "sync"]
    assert all(e.details["run_id"] == result.run_id for e in audit_writer.events)


async def test_sync_only_requested_scope(cursor_manager, raw_payload_writer, audit_writer) -> None:
    connector = FakeConnector(SourceType.JIRA, [make_source_document()], scopes=["a", "b"])
    service = _service({"jira": connector}, cursor_manager, raw_payload_writer, audit_writer)

    await service.sync_source("jira", scopes=["b"])

    assert [scope for scope, _ in connector.calls] == ["b"]
    with pytest.raises(ValueError):
        await service.sync_source("jira", scopes=["nope"])


async def test_scope_failure_is_captured_not_raised(cursor_manager, raw_payload_writer, audit_writer) -> None:
    service = _service({"jira": FakeConnector(SourceType.JIRA, [], raises=True)}, cursor_manager, raw_payload_writer, audit_writer)

    result = await service.sync_source("jira")

    assert result.status == SyncStatus.FAILED
    assert result.errors == ["default: boom"]
    assert await cursor_manager.get_cursor(cursor_key("jira", "default")) is None


async def test_object_error_gives_partial_and_holds_cursor_at_failed_version(cursor_manager, raw_payload_writer, audit_writer) -> None:
    error = ObjectError(scope="default", object_id="ABC-2", source_version="2025-12-31T00:00:00.000Z", error="bad")
    connector = FakeConnector(SourceType.JIRA, [make_source_document()], errors=[error])
    service = _service({"jira": connector}, cursor_manager, raw_payload_writer, audit_writer)

    result = await service.sync_source("jira")

    assert result.status == SyncStatus.PARTIAL
    assert result.documents_count == 1
    assert await cursor_manager.get_cursor(cursor_key("jira", "default")) == "2025-12-31T00:00:00.000Z"


async def test_raw_write_failure_does_not_advance_cursor(cursor_manager, audit_writer) -> None:
    class FailingWriter:
        async def write(self, source, source_object_id, raw_payload):
            raise OSError("disk full")

    service = _service({"jira": FakeConnector(SourceType.JIRA, [make_source_document()])}, cursor_manager, FailingWriter(), audit_writer)

    result = await service.sync_source("jira")

    assert result.status == SyncStatus.PARTIAL
    assert result.documents_count == 0
    assert await cursor_manager.get_cursor(cursor_key("jira", "default")) == "2026-01-01T00:00:00.000Z"


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
