from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from usep.core.ids import new_id
from usep.ingestion.domain.events import QuarantineRecord


@dataclass(frozen=True, slots=True)
class QuarantineEntry:
    tenant_id: UUID
    source: str
    scope_id: str
    object_type: str
    object_id: str
    record: QuarantineRecord


class InMemoryQuarantine:
    """Fake `QuarantinePort`. Never imported from production code."""

    def __init__(self) -> None:
        self.entries: list[QuarantineEntry] = []

    async def quarantine(
        self,
        tenant_id: UUID,
        source: str,
        scope_id: str,
        object_type: str,
        object_id: str,
        record: QuarantineRecord,
    ) -> UUID:
        self.entries.append(QuarantineEntry(tenant_id, source, scope_id, object_type, object_id, record))
        return new_id()
