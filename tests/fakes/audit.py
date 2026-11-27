from __future__ import annotations

from usep.ingestion.ports.audit import AuditEvent


class InMemoryAudit:
    """Fake `AuditPort`. Never imported from production code."""

    def __init__(self) -> None:
        self.entries: list[AuditEvent] = []

    async def record(self, event: AuditEvent) -> None:
        self.entries.append(event)
