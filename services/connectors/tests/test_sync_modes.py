"""Backfill start, per-run cap, full refresh and the object index, over a connector that honours the cursor."""
from __future__ import annotations
import pytest

pytest.skip("Branch serverless path: needs porting onto main's ingestion layer (docs/review/lambda-path-port.md)", allow_module_level=True)


import pytest

from common.connector_base import ScopeFetch
from common.interfaces.cursor_manager import InMemoryCursorManager
from common.interfaces.object_index import InMemoryObjectIndex
from common.interfaces.raw_payload_writer import NullRawPayloadWriter
from common.source_document import SourceType
from common.sync_models import SyncStatus
from sync_service import SyncService
from tests.conftest import make_source_document


class CursorAwareConnector:
    """Returns objects whose version is >= the cursor, like every real connector."""
    source = SourceType.JIRA
    scopes = ["s"]

    def __init__(self, versions: dict[str, str]) -> None:
        self.versions, self.calls = versions, []

    async def fetch_scope(self, scope, cursor):
        self.calls.append(cursor)
        docs = [make_source_document(source_object_id=i, source_version=v) for i, v in self.versions.items()
                if not cursor or v >= cursor]
        return ScopeFetch(documents=docs)


def service(connector, audit, cursors=None, **kw):
    return SyncService({"jira": connector}, cursors or InMemoryCursorManager(), NullRawPayloadWriter(), audit, **kw)


V = {f"A-{i}": f"2026-01-0{i}T00:00:00.000Z" for i in range(1, 6)}      # five objects, one per day


@pytest.mark.asyncio
async def test_backfill_start_is_used_only_when_no_cursor_is_stored(audit_writer):
    c = CursorAwareConnector(V)
    cursors = InMemoryCursorManager()
    svc = service(c, audit_writer, cursors, initial_cursor="2026-01-03T00:00:00.000Z")
    first = await svc.sync_source("jira")
    assert c.calls == ["2026-01-03T00:00:00.000Z"] and first.documents_count == 3
    await svc.sync_source("jira")
    assert c.calls[1] == "2026-01-05T00:00:00.000Z"                     # the stored cursor wins from now on


@pytest.mark.asyncio
async def test_cap_lands_oldest_first_and_the_next_runs_finish_the_backfill(audit_writer):
    c = CursorAwareConnector(V)
    svc = service(c, audit_writer, max_documents_per_scope=2)
    seen: list[str] = []
    for _ in range(6):
        r = await svc.sync_source("jira")
        seen += [d.source_object_id for d in r.documents]
        if not r.truncated_scopes:
            break
    assert r.status == SyncStatus.SUCCESS and not r.truncated_scopes
    assert set(seen) == set(V)                                          # everything landed eventually
    assert seen[:2] == ["A-1", "A-2"]                                   # oldest first


@pytest.mark.asyncio
async def test_truncated_run_is_partial_and_reports_the_scope(audit_writer):
    r = await service(CursorAwareConnector(V), audit_writer, max_documents_per_scope=2).sync_source("jira")
    assert r.status == SyncStatus.PARTIAL and r.truncated_scopes == ["s"]
    assert r.documents_count == 2 and r.cursors["s"] == "2026-01-02T00:00:00.000Z"


@pytest.mark.asyncio
async def test_full_refresh_reads_everything_ignores_the_cap_and_never_moves_the_cursor_back(audit_writer):
    c = CursorAwareConnector(V)
    cursors = InMemoryCursorManager()
    svc = service(c, audit_writer, cursors, max_documents_per_scope=2)
    await svc.sync_source("jira")
    await cursors.set_cursor("jira:s", "2026-01-05T00:00:00.000Z")
    r = await svc.sync_source("jira", full=True)
    assert c.calls[-1] is None and r.documents_count == 5 and not r.truncated_scopes
    assert await cursors.get_cursor("jira:s") == "2026-01-05T00:00:00.000Z"


@pytest.mark.asyncio
async def test_landed_ids_are_indexed_per_scope(audit_writer):
    idx = InMemoryObjectIndex()
    svc = service(CursorAwareConnector(V), audit_writer, object_index=idx)
    await svc.sync_source("jira")
    assert await idx.get("jira:s") == set(V)


@pytest.mark.asyncio
async def test_failed_landing_is_not_indexed(audit_writer):
    class Failing(NullRawPayloadWriter):
        async def write(self, source, source_object_id, raw_payload):
            if source_object_id == "A-2":
                raise RuntimeError("boom")
            return await super().write(source, source_object_id, raw_payload)

    idx = InMemoryObjectIndex()
    svc = SyncService({"jira": CursorAwareConnector(V)}, InMemoryCursorManager(), Failing(), audit_writer, object_index=idx)
    r = await svc.sync_source("jira")
    assert r.status == SyncStatus.PARTIAL and "A-2" not in await idx.get("jira:s")
