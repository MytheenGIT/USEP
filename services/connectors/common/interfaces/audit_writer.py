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
    async def record(self, event: AuditEvent) -> None: ...


class StructlogAuditWriter:
    """Default that only logs via structlog. Not a durable audit trail."""

    async def record(self, event: AuditEvent) -> None:
        logger.info("audit_event", **event.model_dump(mode="json"))
