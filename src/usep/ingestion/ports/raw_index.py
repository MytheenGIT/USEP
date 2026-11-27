"""`RawIndexPort`: the raw-object index, keyed by object identity and content hash.

The key is (tenant, source, object_type, object_id, content_hash).

Every row carries `tenant_id`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from usep.ingestion.domain.raw_object import RawObjectRef


class RawIndexPort(Protocol):
    """The tenant-scoped index of stored raw objects."""

    async def find(
        self, tenant_id: UUID, source: str, object_type: str, object_id: str, content_hash: str
    ) -> RawObjectRef | None:
        """Return the row for this exact key, or `None` if there is none.

        A tombstoned row is returned too; `revive` and the writer rely on seeing it.
        """

    async def insert_if_absent(self, ref: RawObjectRef) -> RawObjectRef:
        """Insert or fetch the row at this key.

        Returns the stored row: the input ref if inserted, the pre-existing row if one already
        existed. Used to resolve races: concurrent writes to the same object share the first
        writer's event_id.
        """
        ...

    async def revive(self, ref: RawObjectRef) -> RawObjectRef:
        """Replace the tombstoned row at this key with `ref`.

        The revived row has a new wrapped key and event ID, no tombstone or absence marker, and is
        unpublished.

        Returns the stored row: `ref` if revived, the existing row if another writer revived it
        first.
        """
        ...

    async def set_source_version(self, ref: RawObjectRef, source_version: str) -> None:
        """Record the source's own version string for a row.

        Used after the source changed its version without the content changing.
        """
        ...

    async def mark_published(self, ref: RawObjectRef) -> None:
        """`UPDATE ... SET published_at = now() WHERE ... AND published_at IS NULL`."""
        ...

    async def list_extant_by_scope(self, tenant_id: UUID, source: str, scope_id: str) -> list[RawObjectRef]:
        """Every non-tombstoned object in this scope (for reconciliation)."""
        ...

    async def mark_first_seen_extra(self, ref: RawObjectRef, *, at: datetime) -> None:
        """Record when an object was first found stored but absent from the source."""

    async def clear_first_seen_extra(self, ref: RawObjectRef) -> None:
        """Forget an earlier absence of an object that is back in the source.

        The two-sighting rule starts over if the object disappears again.
        """
        ...

    async def tombstone(self, ref: RawObjectRef, *, at: datetime) -> None:
        """Crypto-shred a row: mark it tombstoned and clear its wrapped data key.

        Sets `tombstoned_at` and clears the wrapped data key. Once the key is gone the stored
        ciphertext is permanently unreadable, without touching the tenant's key-encryption key.
        """
        ...
