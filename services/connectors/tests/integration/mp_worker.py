"""One process of the multi-process check: syncs one scope against a shared Postgres and a shared
file store, then prints a one-line JSON summary. Run by test_postgres.py; not a test itself."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from common.connector_base import ScopeFetch
from common.source_document import SourceDocument, SourceType
from db.base import create_engine, create_session_factory
from db.ports_sql import SqlAuditWriter, SqlCursorStore, SqlQuarantine, SqlRawIndex
from sync_service import SyncService
from usep.adapters.local_files.object_store import FileObjectStore
from usep.adapters.local_kek.key_store import LocalKeyEncryption
from usep.core.clock import SystemClock
from usep.ingestion.cursor.manager import CursorManager
from usep.ingestion.raw.writer import RawPayloadWriter
from usep.ingestion.runtime.observer import NoOpObserver  # noqa: F401  (import check only)


class Connector:
    source = SourceType.JIRA
    scopes = ["ENG"]

    def __init__(self, count: int) -> None:
        self._count = count

    async def fetch_scope(self, scope: str, cursor: str | None) -> ScopeFetch:
        docs = [
            SourceDocument(
                source=SourceType.JIRA, source_type="issue", source_object_id=f"ENG-{i}", source_url="https://x/browse",
                retrieved_at=datetime.now(UTC), raw_payload={"key": f"ENG-{i}", "summary": f"issue {i}"},
                source_version=f"2026-01-01T00:00:{i:02d}.000Z", title="t",
            )
            for i in range(self._count)
        ]
        await asyncio.sleep(0.05)  # let the other processes get to the same objects
        return ScopeFetch(documents=docs)


async def main() -> None:
    tenant = UUID(os.environ["TENANT"])
    engine = create_engine(os.environ["DATABASE_URL"])
    sf = create_session_factory(engine)
    index, store = SqlRawIndex(sf), FileObjectStore(Path(os.environ["STORE_DIR"]))
    keys = LocalKeyEncryption(base64.b64decode(os.environ["KEK_B64"]))
    quarantine = SqlQuarantine(sf)
    service = SyncService(
        connectors={"jira": Connector(int(os.environ["DOC_COUNT"]))},
        cursor_manager=CursorManager(SqlCursorStore(sf, tenant), overlap_seconds=0),
        writer_factory=lambda run_id, audit: RawPayloadWriter(
            index, store, keys, _Log(), quarantine, audit, SystemClock(), tenant, run_id
        ),
        audit_writer_factory=lambda run_id: SqlAuditWriter(sf, tenant, run_id, "mp"),
    )
    result = await service.sync_source("jira")
    await engine.dispose()
    print(json.dumps({"run_id": result.run_id, "status": result.status.value, "documents": result.documents_count, "errors": result.errors}))


class _Log:
    async def publish_raw(self, event) -> None:
        return None


if __name__ == "__main__":
    asyncio.run(main())
