"""`QuarantinePort`, `DeadLetterPort` and `WorkItemPort`."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from usep.ingestion.domain.events import QuarantineRecord


class QuarantinePort(Protocol):
    async def quarantine(
        self,
        tenant_id: UUID,
        source: str,
        scope_id: str,
        object_type: str,
        object_id: str,
        record: QuarantineRecord,
    ) -> UUID: ...


class DeadLetterPort(Protocol):
    async def dead_letter(
        self,
        tenant_id: UUID,
        source: str,
        scope_id: str,
        object_type: str,
        object_id: str,
        reason: str,
    ) -> None: ...


class WorkItemPort(Protocol):
    async def upsert(
        self,
        tenant_id: UUID,
        source: str,
        scope_id: str,
        object_type: str,
        object_id: str,
        *,
        status: str,
        attempts: int,
        retry_at: datetime | None = None,
        last_reason: str = "",
    ) -> None: ...
