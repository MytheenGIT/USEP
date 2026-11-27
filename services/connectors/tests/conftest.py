from __future__ import annotations

from datetime import UTC, datetime

import pytest

from common.connector_base import ObjectError, ScopeFetch
from common.interfaces.audit_writer import AuditEvent, AuditWriter
from usep.ingestion.cursor.manager import CursorManager
from usep.ingestion.raw.writer import Outcome, WriteResult
from common.source_document import SourceDocument, SourceType


class FakeConnector:
    """Deterministic stand-in for a real connector; used to unit test SyncService."""

    def __init__(
        self,
        source: SourceType,
        documents: list[SourceDocument],
        raises: bool = False,
        scopes: list[str] | None = None,
        errors: list[ObjectError] | None = None,
    ) -> None:
        self.source = source
        self._documents = documents
        self._raises = raises
        self._scopes = scopes or ["default"]
        self._errors = errors or []
        self.calls: list[tuple[str, str | None]] = []

    @property
    def scopes(self) -> list[str]:
        return self._scopes

    async def fetch_scope(self, scope: str, cursor: str | None) -> ScopeFetch:
        self.calls.append((scope, cursor))
        if self._raises:
            raise RuntimeError("boom")
        return ScopeFetch(documents=self._documents, errors=self._errors)


class RecordingAuditWriter(AuditWriter):
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def record(self, event: AuditEvent) -> None:
        self.events.append(event)


def make_source_document(
    source: SourceType = SourceType.JIRA, source_object_id: str = "ABC-1", source_version: str | None = "2026-01-01T00:00:00.000Z"
) -> SourceDocument:
    return SourceDocument(
        source_version=source_version,
        source=source,
        source_type="issue",
        source_object_id=source_object_id,
        source_url="https://example.atlassian.net/browse/ABC-1",
        retrieved_at=datetime.now(UTC),
        raw_payload={"key": source_object_id},
        title="Example",
        content="Example content",
        metadata={},
    )


class InMemoryCursorStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get_cursor(self, source: str) -> str | None:
        return self.values.get(source)

    async def set_cursor(self, source: str, cursor: str) -> None:
        self.values[source] = cursor


class RecordingWriter:
    """Stands in for the foundation's RawPayloadWriter: records calls, returns a chosen outcome."""

    def __init__(self, outcome: str = Outcome.WRITTEN) -> None:
        self.outcome = outcome
        self.calls: list[tuple[str, str, dict]] = []

    async def write(self, source: str, source_object_id: str, raw_payload: dict) -> WriteResult:
        self.calls.append((source, source_object_id, raw_payload))
        return WriteResult(self.outcome, object_key=f"raw/{source}/{source_object_id}", reason="test")


@pytest.fixture
def cursor_store() -> InMemoryCursorStore:
    return InMemoryCursorStore()


@pytest.fixture
def cursor_manager(cursor_store: InMemoryCursorStore) -> CursorManager:
    return CursorManager(cursor_store, overlap_seconds=0)


@pytest.fixture
def raw_payload_writer() -> RecordingWriter:
    return RecordingWriter()


@pytest.fixture
def audit_writer() -> RecordingAuditWriter:
    return RecordingAuditWriter()


@pytest.fixture(autouse=True)
def _no_ingestion_settings_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's real USEP_INGESTION_* variables must not change what the tests see."""
    import os

    for name in [n for n in os.environ if n.startswith("USEP_INGESTION_")]:
        monkeypatch.delenv(name)
