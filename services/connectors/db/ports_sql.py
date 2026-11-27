"""SQL implementations of the foundation's ``RawIndexPort``, ``CursorStorePort`` and
``QuarantinePort``. The tenant is bound at construction, as the ports document.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models import AuditEventRow, CursorRow, QuarantineRow, RawObjectRow, RunSnapshotRow
from usep.core.ids import new_id
from usep.ingestion.domain.events import QuarantineRecord
from usep.ingestion.domain.raw_object import RawObjectRef
from usep.ingestion.ports.audit import AuditEvent

SessionFactory = async_sessionmaker[AsyncSession]


def _insert(session: AsyncSession, model: type) -> Any:
    """An INSERT that supports ON CONFLICT, for the database this session is on."""
    return {"postgresql": pg_insert, "sqlite": sqlite_insert}[session.get_bind().dialect.name](model)


def _utc(value: datetime | None) -> datetime | None:
    # SQLite hands back naive datetimes; Postgres hands back aware ones.
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def _ref(row: RawObjectRow) -> RawObjectRef:
    return RawObjectRef(
        tenant_id=row.tenant_id,
        source=row.source,
        object_type=row.object_type,
        object_id=row.object_id,
        content_hash=row.content_hash,
        scope_id=row.scope_id,
        object_key=row.object_key,
        byte_size=row.byte_size,
        run_id=row.run_id,
        imported_at=_utc(row.imported_at),  # type: ignore[arg-type]
        published_at=_utc(row.published_at),
        wrapped_dek=row.wrapped_dek,
        kek_id=row.kek_id,
        tombstoned_at=_utc(row.tombstoned_at),
        first_seen_extra_at=_utc(row.first_seen_extra_at),
    )


def _key(ref: RawObjectRef) -> tuple:
    return (ref.tenant_id, ref.source, ref.object_type, ref.object_id, ref.content_hash)


class SqlRawIndex:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._sf = session_factory

    async def find(
        self, tenant_id: UUID, source: str, object_type: str, object_id: str, content_hash: str
    ) -> RawObjectRef | None:
        async with self._sf() as session:
            row = await session.get(RawObjectRow, (tenant_id, source, object_type, object_id, content_hash))
            return _ref(row) if row else None

    async def list_by_key(self, tenant_id: UUID, object_key: str) -> list[RawObjectRef]:
        """Index rows for one object key (inspection tools; not part of the port)."""
        async with self._sf() as session:
            rows = await session.scalars(
                select(RawObjectRow).where(RawObjectRow.tenant_id == tenant_id, RawObjectRow.object_key == object_key)
            )
            return [_ref(r) for r in rows]

    async def insert_if_absent(self, ref: RawObjectRef) -> bool:
        async with self._sf() as session:
            result = await session.execute(
                _insert(session, RawObjectRow)
                .values(
                    tenant_id=ref.tenant_id, source=ref.source, object_type=ref.object_type,
                    object_id=ref.object_id, content_hash=ref.content_hash, scope_id=ref.scope_id,
                    object_key=ref.object_key, byte_size=ref.byte_size, run_id=ref.run_id,
                    imported_at=ref.imported_at, published_at=ref.published_at,
                    wrapped_dek=ref.wrapped_dek, kek_id=ref.kek_id,
                )
                .on_conflict_do_nothing()
            )
            await session.commit()
            return result.rowcount == 1

    async def _update(self, ref: RawObjectRef, *extra_where, **values: object) -> None:
        t, s, ot, oid, h = _key(ref)
        async with self._sf() as session:
            await session.execute(
                update(RawObjectRow)
                .where(
                    RawObjectRow.tenant_id == t, RawObjectRow.source == s, RawObjectRow.object_type == ot,
                    RawObjectRow.object_id == oid, RawObjectRow.content_hash == h, *extra_where,
                )
                .values(**values)
            )
            await session.commit()

    async def mark_published(self, ref: RawObjectRef) -> None:
        await self._update(ref, RawObjectRow.published_at.is_(None), published_at=datetime.now(UTC))

    async def list_extant_by_scope(self, tenant_id: UUID, source: str, scope_id: str) -> list[RawObjectRef]:
        async with self._sf() as session:
            rows = await session.scalars(
                select(RawObjectRow).where(
                    RawObjectRow.tenant_id == tenant_id, RawObjectRow.source == source,
                    RawObjectRow.scope_id == scope_id, RawObjectRow.tombstoned_at.is_(None),
                )
            )
            return [_ref(r) for r in rows]

    async def mark_first_seen_extra(self, ref: RawObjectRef, *, at: datetime) -> None:
        await self._update(ref, RawObjectRow.first_seen_extra_at.is_(None), first_seen_extra_at=at)

    async def tombstone(self, ref: RawObjectRef, *, at: datetime) -> None:
        await self._update(ref, tombstoned_at=at, wrapped_dek=None)  # dropping the key shreds the object


class SqlCursorStore:
    def __init__(self, session_factory: SessionFactory, tenant_id: UUID) -> None:
        self._sf = session_factory
        self._tenant_id = tenant_id

    async def get_cursor(self, source: str) -> str | None:
        async with self._sf() as session:
            row = await session.get(CursorRow, (self._tenant_id, source))
            return row.cursor if row else None

    async def set_cursor(self, source: str, cursor: str) -> None:
        now = datetime.now(UTC)
        async with self._sf() as session:
            await session.execute(
                _insert(session, CursorRow)
                .values(tenant_id=self._tenant_id, key=source, cursor=cursor, updated_at=now)
                .on_conflict_do_update(
                    index_elements=[CursorRow.tenant_id, CursorRow.key], set_={"cursor": cursor, "updated_at": now}
                )
            )
            await session.commit()


class SqlQuarantine:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._sf = session_factory

    async def quarantine(
        self, tenant_id: UUID, source: str, scope_id: str, object_type: str, object_id: str,
        record: QuarantineRecord,
    ) -> UUID:
        row_id = new_id()
        async with self._sf() as session:
            session.add(
                QuarantineRow(
                    id=row_id, tenant_id=tenant_id, source=source, scope_id=scope_id, object_type=object_type,
                    object_id=object_id, reason_code=record.reason_code,
                    detector_counts=dict(record.detector_counts), created_at=datetime.now(UTC),
                )
            )
            await session.commit()
        return row_id


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


class SqlAuditWriter:
    """``AuditPort`` into the append-only ``audit_event`` table, hash-chained within one trace.

    Bind one instance to a run (``trace_id=run_id``) so every event of that run is chained in order.
    """

    def __init__(
        self, session_factory: SessionFactory, tenant_id: UUID, trace_id: UUID | None, app_version: str
    ) -> None:
        self._sf = session_factory
        self._tenant_id = tenant_id
        self._trace_id = trace_id
        self._app_version = app_version
        self._lock = asyncio.Lock()
        self._last_hash: str | None = None
        self._loaded = False

    async def _previous_hash(self, session: AsyncSession) -> str | None:
        if not self._loaded:
            query = select(AuditEventRow.hash).where(AuditEventRow.tenant_id == self._tenant_id)
            query = query.where(
                AuditEventRow.trace_id == self._trace_id if self._trace_id else AuditEventRow.trace_id.is_(None)
            )
            self._last_hash = await session.scalar(query.order_by(AuditEventRow.id.desc()).limit(1))
            self._loaded = True
        return self._last_hash

    async def record(self, event: AuditEvent) -> None:
        details = json.loads(_canonical(event.details))  # anything that is not plain JSON becomes its string form
        row_id = new_id()
        async with self._lock, self._sf() as session:
            prev = await self._previous_hash(session)
            body = {
                "id": str(row_id), "tenant_id": str(self._tenant_id),
                "trace_id": str(self._trace_id) if self._trace_id else None, "at": event.at.isoformat(),
                "source": event.source, "action": event.action, "status": event.status, "details": details,
                "app_version": self._app_version,
            }
            digest = hashlib.sha256(((prev or "") + _canonical(body)).encode()).hexdigest()
            session.add(
                AuditEventRow(
                    id=row_id, tenant_id=self._tenant_id, trace_id=self._trace_id, at=event.at, source=event.source,
                    action=event.action, status=event.status, details=details, app_version=self._app_version,
                    prev_hash=prev, hash=digest,
                )
            )
            await session.commit()
            self._last_hash = digest


async def verify_audit_chain(session_factory: SessionFactory, tenant_id: UUID, trace_id: UUID | None) -> bool:
    """True if every event of the trace still hashes to what is stored and links to the one before it."""
    async with session_factory() as session:
        query = select(AuditEventRow).where(AuditEventRow.tenant_id == tenant_id)
        query = query.where(AuditEventRow.trace_id == trace_id if trace_id else AuditEventRow.trace_id.is_(None))
        rows = list((await session.scalars(query.order_by(AuditEventRow.id))).all())
    prev: str | None = None
    for row in rows:
        body = {
            "id": str(row.id), "tenant_id": str(row.tenant_id), "trace_id": str(row.trace_id) if row.trace_id else None,
            "at": (_utc(row.at) or row.at).isoformat(), "source": row.source, "action": row.action,
            "status": row.status, "details": row.details, "app_version": row.app_version,
        }
        if row.prev_hash != prev or row.hash != hashlib.sha256(((prev or "") + _canonical(body)).encode()).hexdigest():
            return False
        prev = row.hash
    return True


_SECRET_WORDS = ("token", "secret", "password", "email")


def _without_secrets(config: dict[str, Any]) -> dict[str, Any]:
    return {
        k: _without_secrets(v) if isinstance(v, dict) else v
        for k, v in config.items()
        if not any(word in k.lower() for word in _SECRET_WORDS)
    }


class SqlRunSnapshots:
    def __init__(self, session_factory: SessionFactory, tenant_id: UUID) -> None:
        self._sf = session_factory
        self._tenant_id = tenant_id

    async def record(self, run_id: UUID, source: str, config: dict[str, Any]) -> None:
        safe = json.loads(_canonical(_without_secrets(config)))
        async with self._sf() as session:
            session.add(
                RunSnapshotRow(
                    run_id=run_id, tenant_id=self._tenant_id, source=source, taken_at=datetime.now(UTC),
                    config=safe, config_hash=hashlib.sha256(_canonical(safe).encode()).hexdigest(),
                )
            )
            await session.commit()
