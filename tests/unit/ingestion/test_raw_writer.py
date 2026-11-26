from __future__ import annotations

from uuid import uuid4

import pytest
from tests.fakes.audit import InMemoryAudit
from tests.fakes.clock import FakeClock
from tests.fakes.event_bus import InMemoryEventBus
from tests.fakes.key_store import InMemoryKeyEncryption
from tests.fakes.object_store import InMemoryObjectStore
from tests.fakes.quarantine import InMemoryQuarantine
from tests.fakes.raw_index import InMemoryRawIndex

from usep.ingestion.raw.writer import EnvelopeError, RawPayloadWriter

TENANT = uuid4()
RUN = uuid4()


def _envelope(object_type: str = "issue", scope_id: str = "PROJ", checkpoint: str = "c1") -> dict:
    return {"_usep": {"object_type": object_type, "scope_id": scope_id, "checkpoint": checkpoint}}


def _writer() -> tuple[
    RawPayloadWriter,
    InMemoryRawIndex,
    InMemoryObjectStore,
    InMemoryEventBus,
    InMemoryQuarantine,
    InMemoryAudit,
]:
    raw_index = InMemoryRawIndex()
    object_store = InMemoryObjectStore()
    event_bus = InMemoryEventBus()
    quarantine = InMemoryQuarantine()
    audit = InMemoryAudit()
    writer = RawPayloadWriter(
        raw_index,
        object_store,
        InMemoryKeyEncryption(),
        event_bus,
        quarantine,
        audit,
        FakeClock(),
        TENANT,
        RUN,
    )
    return writer, raw_index, object_store, event_bus, quarantine, audit


@pytest.mark.asyncio
async def test_overlap_window_single_write_after_dedupe() -> None:
    writer, raw_index, *_ = _writer()
    payload = {"summary": "Example", **_envelope()}
    ref1 = await writer.write("jira", "PROJ-1", payload)
    ref2 = await writer.write("jira", "PROJ-1", payload)
    assert ref1.startswith("raw/")
    assert ref2 == ref1  # skipped_unchanged resolves to the same reference
    assert len(raw_index.all_refs()) == 1


@pytest.mark.asyncio
async def test_out_of_order_events_are_idempotent() -> None:
    writer, raw_index, _, event_bus, *_ = _writer()
    payload = {"summary": "Example", **_envelope(object_type="commit", scope_id="grp/proj")}

    await writer.write("gitlab", "abc123", payload)
    await writer.write("gitlab", "abc123", payload)
    assert len(raw_index.all_refs()) == 1
    assert len(event_bus.published) == 1  # same event_id both times; not duplicated


@pytest.mark.asyncio
async def test_schema_drift_quarantined_not_dropped() -> None:
    writer, _, object_store, event_bus, quarantine, audit = _writer()

    class NotJsonSerializable:
        pass

    ref = await writer.write("jira", "PROJ-2", {"bad": NotJsonSerializable(), **_envelope()})
    assert ref.startswith("quarantined://Q-SCHEMA")
    assert quarantine.entries[0].record.reason_code == "Q-SCHEMA"
    assert object_store.objects == {}
    assert event_bus.published == []
    assert audit.entries[-1].status == "Q-SCHEMA"


@pytest.mark.asyncio
async def test_envelope_missing_is_rejected() -> None:
    writer, *_ = _writer()
    with pytest.raises(EnvelopeError):
        await writer.write("jira", "PROJ-9", {"summary": "no envelope"})


@pytest.mark.asyncio
async def test_envelope_incomplete_is_rejected() -> None:
    writer, *_ = _writer()
    with pytest.raises(EnvelopeError):
        await writer.write("jira", "PROJ-9", {"summary": "x", "_usep": {"object_type": "issue"}})


@pytest.mark.asyncio
async def test_metadata_only_change_does_not_create_a_new_version() -> None:
    """The _usep envelope is stripped before hashing, so a changed checkpoint
    alone is not a new content version."""
    writer, raw_index, *_ = _writer()
    await writer.write("jira", "PROJ-1", {"summary": "same", **_envelope(checkpoint="c1")})
    await writer.write("jira", "PROJ-1", {"summary": "same", **_envelope(checkpoint="c2")})
    assert len(raw_index.all_refs()) == 1


@pytest.mark.asyncio
async def test_publish_reference_only_no_payload_bytes() -> None:
    writer, _, _, event_bus, *_ = _writer()
    await writer.write(
        "confluence",
        "123",
        {"title": "Doc", "body": "content", **_envelope(object_type="page", scope_id="SPACE")},
    )
    assert len(event_bus.published) == 1
    event = event_bus.published[0]
    from dataclasses import fields

    field_names = {f.name for f in fields(event)}
    assert field_names.isdisjoint({"raw_payload", "payload", "body", "content"})
    assert isinstance(event.object_key, str)
    assert isinstance(event.content_hash, str)
    assert event.checkpoint == "c1"


@pytest.mark.asyncio
async def test_pii_payload_quarantined_before_any_write() -> None:
    writer, raw_index, object_store, event_bus, quarantine, audit = _writer()
    ref = await writer.write(
        "jira", "PROJ-3", {"summary": "Card on file: 4111 1111 1111 1111", **_envelope()}
    )
    assert ref.startswith("quarantined://Q-PII")
    assert raw_index.all_refs() == []
    assert object_store.objects == {}
    assert event_bus.published == []
    assert quarantine.entries[0].record.detector_counts == {"Q-PII": 1}
    assert "4111" not in repr(audit.entries)
    assert "4111" not in repr(quarantine.entries)
