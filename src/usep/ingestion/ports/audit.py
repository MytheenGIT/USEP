"""`AuditPort`: records one audit event.

Matches the connectors branch's `AuditWriter` Protocol exactly: `record(event: AuditEvent) -> None`.
`tenant_id` and `run_id` (used as `trace_id`) are bound at adapter construction, not passed per
call.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel


class AuditEvent(BaseModel):
    """One audit record. `details` holds identifiers and counts only."""

    source: str
    action: str
    status: str
    at: datetime
    details: dict[str, Any] = {}


class AuditPort(Protocol):
    """Writes audit events."""

    async def record(self, event: AuditEvent) -> None:
        """Write one audit event; `details` holds counts and identifiers only.

        Never put matched sensitive values or secrets in `event.details`.
        """
        ...
