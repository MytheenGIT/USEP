from __future__ import annotations

import datetime as dt
from uuid import uuid4

import pytest
from tests.fakes.audit import InMemoryAudit
from tests.fakes.clock import FakeClock
from tests.fakes.event_bus import InMemoryEventBus
from tests.fakes.key_store import InMemoryKeyEncryption
from tests.fakes.object_store import InMemoryObjectStore
from tests.fakes.quarantine import InMemoryQuarantine
from tests.fakes.raw_index import InMemoryRawIndex

from usep.core.ids import new_id
from usep.ingestion.domain.raw_object import RawObjectRef, canonicalize, content_hash, object_key
from usep.ingestion.raw.writer import EnvelopeError, RawPayloadWriter, _extract_envelope

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


@pytest.mark.asyncio
async def test_distinct_objects_get_distinct_event_ids() -> None:
    writer, _, _, event_bus, *_ = _writer()
    payload1 = {"summary": "v1", **_envelope()}
    payload2 = {"summary": "v2", **_envelope()}

    await writer.write("jira", "PROJ-1", payload1)
    await writer.write("jira", "PROJ-2", payload2)
    assert len(event_bus.published) == 2
    assert event_bus.published[0].event_id != event_bus.published[1].event_id


@pytest.mark.asyncio
async def test_retry_reuses_event_id_and_publishes_once() -> None:
    writer, raw_index, _, event_bus, *_ = _writer()
    payload = {"summary": "v1", **_envelope()}

    event_bus.fail_next = True
    await writer.write("jira", "PROJ-1", payload)
    first_event_id = raw_index.all_refs()[0].event_id

    event_bus.fail_next = False
    await writer.write("jira", "PROJ-1", payload)
    assert len(event_bus.published) == 1
    assert event_bus.published[0].event_id == first_event_id


@pytest.mark.asyncio
async def test_event_id_is_uuid_v7() -> None:
    writer, raw_index, *_ = _writer()
    await writer.write("jira", "PROJ-1", {"summary": "v1", **_envelope()})
    event_id = raw_index.all_refs()[0].event_id
    assert event_id.version == 7


class _RaceSimulatingRawIndex(InMemoryRawIndex):
    """Test double: simulates a race where concurrent writer inserts between find() and insert_if_absent().
    - find() returns None on first call (simulating no row yet).
    - insert_if_absent() finds and returns the pre-existing row (another writer inserted in the meantime).
    This forces the writer to use the pre-existing row's event_id, not its own newly-created one."""

    def __init__(self):
        super().__init__()
        self._find_called = False

    async def find(
        self, tenant_id, source: str, object_type: str, object_id: str, content_hash: str
    ) -> RawObjectRef | None:
        if not self._find_called:
            self._find_called = True
            return None  # First call: simulates no row yet (race condition)
        return await super().find(tenant_id, source, object_type, object_id, content_hash)

    async def insert_if_absent(self, ref: RawObjectRef) -> RawObjectRef:
        key = self._key(ref.tenant_id, ref.source, ref.object_type, ref.object_id, ref.content_hash)
        if key in self._rows:
            return self._rows[key]  # Return the pre-existing row (with its event_id), not the input ref
        self._rows[key] = ref
        return ref


@pytest.mark.asyncio
async def test_race_publishes_the_stored_event_id() -> None:
    """Race: concurrent insert after find() returns None; writer uses pre-inserted event_id."""
    # Create writer with race-simulating index.
    race_index = _RaceSimulatingRawIndex()
    writer = RawPayloadWriter(
        race_index,
        InMemoryObjectStore(),
        InMemoryKeyEncryption(),
        InMemoryEventBus(),
        InMemoryQuarantine(),
        InMemoryAudit(),
        FakeClock(),
        TENANT,
        RUN,
    )
    payload = {"summary": "v1", **_envelope()}

    # Pre-insert a row with a known event_id (simulating another writer's insert).
    stripped, object_type, scope_id, _ = _extract_envelope(payload)
    canonical = canonicalize(stripped)
    digest = content_hash(canonical)
    key = object_key(TENANT, "jira", scope_id, object_type, "PROJ-1", digest)
    preinserted_event_id = new_id()
    preseed = RawObjectRef(
        tenant_id=TENANT,
        source="jira",
        object_type=object_type,
        object_id="PROJ-1",
        content_hash=digest,
        scope_id=scope_id,
        object_key=key,
        byte_size=len(canonical),
        run_id=RUN,
        imported_at=dt.datetime.now(dt.UTC),
        published_at=None,
        wrapped_dek=b"wrapped",
        kek_id="kek-1",
        event_id=preinserted_event_id,
    )
    race_index._rows[(TENANT, "jira", object_type, "PROJ-1", digest)] = preseed

    # Write: find() returns None (race), then insert_if_absent() returns the pre-inserted ref.
    result = await writer.write("jira", "PROJ-1", payload)
    assert result.startswith("raw/")
    assert len(race_index.all_refs()) == 1
    # The published event must use the pre-inserted event_id, not a new one.
    # If the fix is broken, published[0].event_id will be a different UUID than preinserted_event_id.
    assert writer._event_bus.published[0].event_id == preinserted_event_id, \
        f"Expected {preinserted_event_id}, got {writer._event_bus.published[0].event_id}"

