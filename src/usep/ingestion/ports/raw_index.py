"""`RawIndexPort`: the raw-object index, keyed by (tenant, source, object_type,
object_id, content_hash). Every row carries `tenant_id`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from usep.ingestion.domain.raw_object import RawObjectRef


class RawIndexPort(Protocol):
    async def find(
        self, tenant_id: UUID, source: str, object_type: str, object_id: str, content_hash: str
    ) -> RawObjectRef | None: ...

    async def insert_if_absent(self, ref: RawObjectRef) -> RawObjectRef:
        """Insert or fetch the row at this key. Returns the stored row: the input
        ref if inserted, the pre-existing row if one already existed. Used to resolve
        races: concurrent writes to the same object share the first writer's event_id."""
        ...

    async def mark_published(self, ref: RawObjectRef) -> None:
        """`UPDATE ... SET published_at = now() WHERE ... AND published_at IS NULL`."""
        ...

    async def list_extant_by_scope(self, tenant_id: UUID, source: str, scope_id: str) -> list[RawObjectRef]:
        """Every non-tombstoned object in this scope (for reconciliation)."""
        ...

    async def mark_first_seen_extra(self, ref: RawObjectRef, *, at: datetime) -> None: ...

    async def tombstone(self, ref: RawObjectRef, *, at: datetime) -> None:
        """Sets `tombstoned_at` and clears the wrapped data key — crypto-shred:
        once the wrapped key is gone, the stored ciphertext is permanently
        unreadable, without touching the tenant's key-encryption key."""
        ...
