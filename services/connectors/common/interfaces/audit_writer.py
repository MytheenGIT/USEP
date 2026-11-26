"""Contract for the Audit Writer.

Ownership: implemented elsewhere. This module defines the interface plus
a structlog-only default so the ingestion service is runnable standalone.
The default does not persist anything durable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

import structlog
from pydantic import BaseModel

logger = structlog.get_logger(__name__)


class AuditEvent(BaseModel):
    source: str
    action: str
    status: str
    at: datetime
    details: dict[str, Any] = {}


class AuditWriter(Protocol):
    async def record(self, event: AuditEvent) -> None:
        """Record one audit event.

        Must not raise because of the event's content: ``details`` accepts any
        value, so implementations have to cope with values that are not plain
        JSON (an exception object, for example). A durable implementation may
        raise when the event cannot be persisted; the caller then decides
        whether that fails the step it was auditing.
        """
        ...


class StructlogAuditWriter:
    """Default that only logs via structlog. Not a durable audit trail. Never raises."""

    async def record(self, event: AuditEvent) -> None:
        try:
            payload = event.model_dump(mode="json")
        except Exception:
            # ``details`` held something that is not JSON-serializable; log its repr instead.
            payload = event.model_dump(mode="python", exclude={"details"})
            payload["at"] = event.at.isoformat()
            payload["details"] = {str(k): repr(v) for k, v in event.details.items()}
        try:
            logger.info("audit_event", **payload)
        except Exception as exc:
            logger.warning("audit_event.log_failed", source=event.source, action=event.action, error=repr(exc))
