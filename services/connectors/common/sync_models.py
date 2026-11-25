from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from common.source_document import SourceDocument, SourceType


class SyncStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class SyncResult(BaseModel):
    """Internal result of syncing a single source, used by SyncService/Scheduler."""

    source: SourceType
    status: SyncStatus
    started_at: datetime
    finished_at: datetime
    documents: list[SourceDocument] = []
    cursor: str | None = None
    errors: list[str] = []

    @property
    def documents_count(self) -> int:
        return len(self.documents)


class SyncResponse(BaseModel):
    """API-facing view of a SyncResult.

    ``documents`` is dumped as plain dicts (rather than typed as
    ``SourceDocument``) so each source's extra fields serialize as-is,
    without FastAPI/pydantic coercing subclass instances back to the base
    shape on the response path.
    """

    source: SourceType
    status: SyncStatus
    started_at: datetime
    finished_at: datetime
    documents_count: int
    cursor: str | None = None
    errors: list[str] = []
    documents: list[dict] = []

    @classmethod
    def from_result(cls, result: SyncResult, include_documents: bool = True) -> "SyncResponse":
        return cls(
            source=result.source,
            status=result.status,
            started_at=result.started_at,
            finished_at=result.finished_at,
            documents_count=result.documents_count,
            cursor=result.cursor,
            errors=result.errors,
            documents=[doc.model_dump(mode="json") for doc in result.documents] if include_documents else [],
        )
