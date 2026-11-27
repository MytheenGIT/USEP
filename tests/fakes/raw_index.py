from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from usep.ingestion.domain.raw_object import RawObjectRef


class InMemoryRawIndex:
    """Fake `RawIndexPort`. Never imported from production code."""

    def __init__(self) -> None:
        self._rows: dict[tuple[UUID, str, str, str, str], RawObjectRef] = {}

    @staticmethod
    def _key(tenant_id: UUID, source: str, object_type: str, object_id: str, content_hash: str) -> tuple:
        return (tenant_id, source, object_type, object_id, content_hash)

    async def find(
        self, tenant_id: UUID, source: str, object_type: str, object_id: str, content_hash: str
    ) -> RawObjectRef | None:
        return self._rows.get(self._key(tenant_id, source, object_type, object_id, content_hash))

    async def insert_if_absent(self, ref: RawObjectRef) -> RawObjectRef:
        key = self._key(ref.tenant_id, ref.source, ref.object_type, ref.object_id, ref.content_hash)
        if key in self._rows:
            return self._rows[key]
        self._rows[key] = ref
        return ref

    async def revive(self, ref: RawObjectRef) -> RawObjectRef:
        key = self._key(ref.tenant_id, ref.source, ref.object_type, ref.object_id, ref.content_hash)
        existing = self._rows.get(key)
        if existing is not None and existing.tombstoned_at is None:
            return existing
        self._rows[key] = ref
        return ref

    async def set_source_version(self, ref: RawObjectRef, source_version: str) -> None:
        key = self._key(ref.tenant_id, ref.source, ref.object_type, ref.object_id, ref.content_hash)
        existing = self._rows.get(key)
        if existing is not None:
            self._rows[key] = _replace(existing, source_version=source_version)

    async def mark_published(self, ref: RawObjectRef) -> None:
        key = self._key(ref.tenant_id, ref.source, ref.object_type, ref.object_id, ref.content_hash)
        existing = self._rows.get(key)
        if existing is not None and existing.published_at is None:
            self._rows[key] = _replace(existing, published_at=datetime.now(UTC))

    async def list_extant_by_scope(self, tenant_id: UUID, source: str, scope_id: str) -> list[RawObjectRef]:
        return [
            ref
            for ref in self._rows.values()
            if ref.tenant_id == tenant_id
            and ref.source == source
            and ref.scope_id == scope_id
            and ref.tombstoned_at is None
        ]

    async def mark_first_seen_extra(self, ref: RawObjectRef, *, at: datetime) -> None:
        key = self._key(ref.tenant_id, ref.source, ref.object_type, ref.object_id, ref.content_hash)
        existing = self._rows.get(key)
        if existing is not None and existing.first_seen_extra_at is None:
            self._rows[key] = _replace(existing, first_seen_extra_at=at)

    async def clear_first_seen_extra(self, ref: RawObjectRef) -> None:
        key = self._key(ref.tenant_id, ref.source, ref.object_type, ref.object_id, ref.content_hash)
        existing = self._rows.get(key)
        if existing is not None:
            self._rows[key] = _replace(existing, first_seen_extra_at=None)

    async def tombstone(self, ref: RawObjectRef, *, at: datetime) -> None:
        key = self._key(ref.tenant_id, ref.source, ref.object_type, ref.object_id, ref.content_hash)
        existing = self._rows.get(key)
        if existing is not None:
            self._rows[key] = _replace(existing, tombstoned_at=at, wrapped_dek=None)

    def all_refs(self) -> list[RawObjectRef]:
        return list(self._rows.values())


def _replace(ref: RawObjectRef, **changes: object) -> RawObjectRef:
    from dataclasses import replace

    return replace(ref, **changes)  # type: ignore[arg-type]
