"""The audit record and its hash chain, shared by every audit backend (files, S3, Postgres use the same scheme).

Each event is sealed with the hash of the event before it in the same trace, so a changed, removed or reordered
event breaks the chain from that point on.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from usep.core.ids import new_id
from usep.ingestion.ports.audit import AuditEvent


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def seal(tenant_id: UUID, trace_id: UUID | None, event: AuditEvent, app_version: str, prev_hash: str | None) -> dict[str, Any]:
    """The full record to store: provenance (who, which run, which version, when) plus the chain links."""
    body = {
        "id": str(new_id()), "tenant_id": str(tenant_id), "trace_id": str(trace_id) if trace_id else None,
        "at": event.at.isoformat(), "source": event.source, "action": event.action, "status": event.status,
        "details": json.loads(canonical(event.details)),  # anything that is not plain JSON becomes its string form
        "app_version": app_version,
    }
    return {**body, "prev_hash": prev_hash, "hash": hashlib.sha256(((prev_hash or "") + canonical(body)).encode()).hexdigest()}


def verify(records: Iterable[dict[str, Any]]) -> bool:
    """True if the records, in order, each hash to what they say and link to the one before."""
    prev: str | None = None
    for record in records:
        body = {k: v for k, v in record.items() if k not in ("prev_hash", "hash")}
        if record.get("prev_hash") != prev or record.get("hash") != hashlib.sha256(((prev or "") + canonical(body)).encode()).hexdigest():
            return False
        prev = record["hash"]
    return True
