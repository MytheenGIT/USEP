"""`AuditPort` into JSON-lines files, for keeping and checking the audit trail in the repo before S3 or Postgres is chosen.

One file per trace: ``console.jsonl`` for what admins and the API do, ``runs/<run_id>.jsonl`` for each ingestion run.
Records are only ever appended, one line each, and hash-chained (see ``usep.ingestion.audit_chain``).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from uuid import UUID

from usep.ingestion import audit_chain
from usep.ingestion.ports.audit import AuditEvent


def trace_file(root: Path, trace_id: UUID | None) -> Path:
    return root / ("console.jsonl" if trace_id is None else f"runs/{trace_id}.jsonl")


def read_records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def verify_audit_file(path: Path) -> bool:
    return audit_chain.verify(read_records(path))


class FileAuditWriter:
    def __init__(self, root: Path, tenant_id: UUID, trace_id: UUID | None, app_version: str) -> None:
        self._path = trace_file(root, trace_id)
        self._tenant_id, self._trace_id, self._app_version = tenant_id, trace_id, app_version
        self._lock = asyncio.Lock()
        self._last: str | None = None
        self._loaded = False

    def _append(self, event: AuditEvent) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._loaded:  # continue the chain of an earlier process
            if self._path.exists() and (records := read_records(self._path)):
                self._last = records[-1]["hash"]
            self._loaded = True
        record = audit_chain.seal(self._tenant_id, self._trace_id, event, self._app_version, self._last)
        fd = os.open(self._path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(audit_chain.canonical(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._last = record["hash"]

    async def record(self, event: AuditEvent) -> None:
        async with self._lock:
            await asyncio.to_thread(self._append, event)
