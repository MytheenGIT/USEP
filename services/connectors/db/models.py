"""Ingestion's own bookkeeping of sync job executions.

This is distinct from the Sync Cursor Manager (resume position, owned
elsewhere) and the Audit Writer (compliance trail, owned elsewhere): it is
just an operational record of "what did this ingestion service run and
when", useful for the /sync status endpoint and for ops visibility.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class SyncRunRecord(Base):
    __tablename__ = "ingestion_sync_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    documents_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    errors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
