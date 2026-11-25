from __future__ import annotations

import pytest

from common.source_document import SourceType
from common.sync_models import SyncStatus
from sync_service import SyncService
from tests.conftest import FakeConnector, make_source_document


@pytest.mark.asyncio
async def test_sync_source_success_persists_cursor_and_records_audit(cursor_manager, raw_payload_writer, audit_writer) -> None:
    documents = [make_source_document()]
    connector = FakeConnector(SourceType.JIRA, documents)
    service = SyncService(
        connectors={"jira": connector},
        cursor_manager=cursor_manager,
        raw_payload_writer=raw_payload_writer,
        audit_writer=audit_writer,
    )

    result = await service.sync_source("jira")

    assert result.status == SyncStatus.SUCCESS
    assert result.documents_count == 1
    assert await cursor_manager.get_cursor("jira") == "cursor-2"
    assert len(audit_writer.events) == 1
    assert audit_writer.events[0].status == SyncStatus.SUCCESS.value


@pytest.mark.asyncio
async def test_sync_source_failure_is_captured_not_raised(cursor_manager, raw_payload_writer, audit_writer) -> None:
    connector = FakeConnector(SourceType.JIRA, [], raises=True)
    service = SyncService(
        connectors={"jira": connector},
        cursor_manager=cursor_manager,
        raw_payload_writer=raw_payload_writer,
        audit_writer=audit_writer,
    )

    result = await service.sync_source("jira")

    assert result.status == SyncStatus.FAILED
    assert result.errors == ["boom"]
    assert await cursor_manager.get_cursor("jira") is None


@pytest.mark.asyncio
async def test_sync_source_unknown_source_raises(cursor_manager, raw_payload_writer, audit_writer) -> None:
    service = SyncService(
        connectors={},
        cursor_manager=cursor_manager,
        raw_payload_writer=raw_payload_writer,
        audit_writer=audit_writer,
    )

    with pytest.raises(ValueError):
        await service.sync_source("jira")


@pytest.mark.asyncio
async def test_sync_all_runs_every_connector(cursor_manager, raw_payload_writer, audit_writer) -> None:
    service = SyncService(
        connectors={
            "jira": FakeConnector(SourceType.JIRA, [make_source_document()]),
            "gitlab": FakeConnector(SourceType.GITLAB, [make_source_document(SourceType.GITLAB, "1!1")]),
        },
        cursor_manager=cursor_manager,
        raw_payload_writer=raw_payload_writer,
        audit_writer=audit_writer,
    )

    results = await service.sync_all()

    assert {r.source for r in results} == {SourceType.JIRA, SourceType.GITLAB}
    assert all(r.status == SyncStatus.SUCCESS for r in results)
