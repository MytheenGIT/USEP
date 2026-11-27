"""Ingestion's own bookkeeping of sync job executions.

This is distinct from the Sync Cursor Manager (resume position, owned
elsewhere) and the Audit Writer (compliance trail, owned elsewhere): it is
just an operational record of "what did this ingestion service run and
when", useful for the /sync status endpoint and for ops visibility.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, LargeBinary, String, Text, Uuid
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class SyncRunRecord(Base):
    __tablename__ = "ingestion_sync_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    documents_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # JSON object of scope -> cursor after the run.
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    errors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class RawObjectRow(Base):
    """Index of raw objects in the object store (``RawIndexPort``). One row per content version."""

    __tablename__ = "raw_object"

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    object_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    object_id: Mapped[str] = mapped_column(String(512), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    wrapped_dek: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)  # None once crypto-shredded
    kek_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tombstoned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_extra_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CursorRow(Base):
    """Resume position per tenant and ``<source>:<scope>:<lane>`` key (``CursorStorePort``)."""

    __tablename__ = "sync_cursor"

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    key: Mapped[str] = mapped_column(String(1024), primary_key=True)
    cursor: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class QuarantineRow(Base):
    """Objects withheld from the raw store (LLD Table 13). Holds counts and a reason, never the value."""

    __tablename__ = "quarantine_record"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_id: Mapped[str] = mapped_column(Text, nullable=False)
    object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    object_id: Mapped[str] = mapped_column(String(512), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(16), nullable=False)
    detector_counts: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditEventRow(Base):
    """Append-only audit trail (spec 7.5). Each row stores the hash of the previous row in its
    trace, so a changed or removed row breaks the chain. UPDATE and DELETE are blocked by a
    trigger on Postgres (see ``db.base.create_tables``)."""

    __tablename__ = "audit_event"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    trace_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    app_version: Mapped[str] = mapped_column(String(32), nullable=False)
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)


class RunSnapshotRow(Base):
    """The source configuration in effect for one run, so editing it later does not rewrite history."""

    __tablename__ = "run_snapshot"

    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
