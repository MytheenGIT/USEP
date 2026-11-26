"""`AuditPort`: records one audit event. Matches the connectors branch's
`AuditWriter` Protocol exactly: `record(event: AuditEvent) -> None`. `tenant_id`
and `run_id` (used as `trace_id`) are bound at adapter construction, not passed
per call.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel


class AuditEvent(BaseModel):
    source: str
    action: str
    status: str
    at: datetime
    details: dict[str, Any] = {}


class AuditPort(Protocol):
    async def record(self, event: AuditEvent) -> None:
        """`event.details` holds counts and identifiers only — never matched
        sensitive values or secrets."""
        ...
