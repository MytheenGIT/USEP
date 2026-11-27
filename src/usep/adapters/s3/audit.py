"""`AuditPort` into any object store (S3 in production): one small immutable object per event.

Objects are never rewritten, which fits S3 Object Lock. The key sorts by time, so listing a trace returns it in order:
``audit/<tenant>/<console|run id>/<time>-<event id>.json``. The chain is kept in memory for the writer's life.

shortcut: a new writer starts a new chain (it does not list the bucket to continue the old one); verify per writer
life, and add the listing when a retention and export design (D-09) is chosen.
"""

from __future__ import annotations

from uuid import UUID

from usep.ingestion import audit_chain
from usep.ingestion.ports.audit import AuditEvent
from usep.ingestion.ports.object_store import ObjectStorePort


class ObjectStoreAuditWriter:
    def __init__(self, store: ObjectStorePort, tenant_id: UUID, trace_id: UUID | None, app_version: str) -> None:
        self._store = store
        self._tenant_id, self._trace_id, self._app_version = tenant_id, trace_id, app_version
        self._last: str | None = None

    async def record(self, event: AuditEvent) -> None:
        record = audit_chain.seal(self._tenant_id, self._trace_id, event, self._app_version, self._last)
        stamp = event.at.strftime("%Y%m%dT%H%M%S%fZ")
        key = f"audit/{self._tenant_id}/{self._trace_id or 'console'}/{stamp}-{record['id']}.json"
        await self._store.put(key, audit_chain.canonical(record).encode())
        self._last = record["hash"]
