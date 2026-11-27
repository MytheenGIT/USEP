"""`QuarantinePort`, `DeadLetterPort` and `WorkItemPort`."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from usep.ingestion.domain.events import QuarantineRecord


class QuarantinePort(Protocol):
    """Holds objects that failed a rule."""

    async def quarantine(
        self,
        tenant_id: UUID,
        source: str,
        scope_id: str,
        object_type: str,
        object_id: str,
        record: QuarantineRecord,
    ) -> UUID:
        """Record a quarantined object and return the ID of the new entry."""


class DeadLetterPort(Protocol):
    """Holds objects whose retries were exhausted."""

    async def dead_letter(
        self,
        tenant_id: UUID,
        source: str,
        scope_id: str,
        object_type: str,
        object_id: str,
        reason: str,
    ) -> None:
        """Record an object as dead-lettered, with the reason."""


class WorkItemPort(Protocol):
    """Tracks the retry state of each object."""

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
    ) -> None:
        """Create or update the retry state of an object."""
