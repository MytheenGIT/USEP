from __future__ import annotations

from datetime import UTC, datetime

import pytest

from common.interfaces.audit_writer import AuditEvent, AuditWriter
from common.interfaces.cursor_manager import InMemoryCursorManager
from common.interfaces.raw_payload_writer import NullRawPayloadWriter
from common.source_document import SourceDocument, SourceType


class FakeConnector:
    """Deterministic stand-in for a real connector; used to unit test SyncService."""

    def __init__(self, source: SourceType, documents: list[SourceDocument], raises: bool = False) -> None:
        self.source = source
        self._documents = documents
        self._raises = raises

    async def fetch(self, cursor: str | None):
        if self._raises:
            raise RuntimeError("boom")
        return self._documents, "cursor-2"


class RecordingAuditWriter(AuditWriter):
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def record(self, event: AuditEvent) -> None:
        self.events.append(event)


def make_source_document(source: SourceType = SourceType.JIRA, source_object_id: str = "ABC-1") -> SourceDocument:
    return SourceDocument(
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


@pytest.fixture
def cursor_manager() -> InMemoryCursorManager:
    return InMemoryCursorManager()


@pytest.fixture
def raw_payload_writer() -> NullRawPayloadWriter:
    return NullRawPayloadWriter()


@pytest.fixture
def audit_writer() -> RecordingAuditWriter:
    return RecordingAuditWriter()
