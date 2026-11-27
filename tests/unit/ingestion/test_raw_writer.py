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
    assert ref1.outcome == "written" and ref1.object_key.startswith("raw/")
    assert ref2.outcome == "skipped_unchanged"
    assert ref2.object_key == ref1.object_key  # skipped_unchanged resolves to the same reference
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
    assert (ref.outcome, ref.reason) == ("quarantined", "Q-SCHEMA")
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
    assert (ref.outcome, ref.reason) == ("quarantined", "Q-PII")
    assert raw_index.all_refs() == []
    assert object_store.objects == {}
    assert event_bus.published == []
    assert quarantine.entries[0].record.detector_counts == {"Q-PII": 1}
    assert "4111" not in repr(audit.entries)
    assert "4111" not in repr(quarantine.entries)


@pytest.mark.asyncio
async def test_source_version_and_acl_go_on_the_event_and_default_to_owners_only() -> None:
    writer, raw_index, _, event_bus, *_ = _writer()
    envelope = _envelope()
    envelope["_usep"].update(source_version="2026-01-01T00:00:00Z", acl={"project_key": "ABC"})

    await writer.write("jira", "PROJ-1", {"summary": "s", **envelope})

    [event] = event_bus.published
    assert event.source_version == "2026-01-01T00:00:00Z"
    assert event.source_acl == {"project_key": "ABC"}
    assert event.acl_ref == "owners-only"  # LLD 4.4: unmapped permission is visible to owners only


async def _read_back(writer, raw_index, object_store) -> dict:
    import json

    from usep.ingestion.raw.crypto import decrypt, unpack

    [ref] = raw_index.all_refs()
    data_key = await writer._key_store.unwrap(TENANT, ref.wrapped_dek, ref.kek_id)
    aad = ref.object_key.encode() + str(TENANT).encode()
    return json.loads(decrypt(unpack(object_store.objects[ref.object_key]), data_key, aad=aad))


@pytest.mark.asyncio
async def test_retry_after_a_failed_put_reuses_the_stored_key_so_the_object_decrypts() -> None:
    writer, raw_index, object_store, *_ = _writer()
    real_put = object_store.put

    async def failing_put(key: str, data: bytes) -> None:
        raise OSError("object store down")

    object_store.put = failing_put  # type: ignore[method-assign]
    first = await writer.write("jira", "PROJ-1", {"summary": "s", **_envelope()})
    assert first.outcome == "failed" and object_store.objects == {}
    assert [r.published_at for r in raw_index.all_refs()] == [None]  # the key is already safe in the index

    object_store.put = real_put  # type: ignore[method-assign]
    second = await writer.write("jira", "PROJ-1", {"summary": "s", **_envelope()})

    assert second.outcome == "written"
    assert await _read_back(writer, raw_index, object_store) == {"summary": "s"}


@pytest.mark.asyncio
async def test_a_writer_that_loses_the_insert_race_uses_the_winners_key() -> None:
    import dataclasses

    from usep.ingestion.raw.crypto import generate_data_key

    writer, raw_index, object_store, *_ = _writer()
    real_insert = raw_index.insert_if_absent

    async def racing_insert(ref):  # a competing writer inserts its own row, with its own key, first
        wrapped, kek_id = await writer._key_store.wrap(TENANT, generate_data_key())
        await real_insert(dataclasses.replace(ref, wrapped_dek=wrapped, kek_id=kek_id))
        return False

    raw_index.insert_if_absent = racing_insert  # type: ignore[method-assign]
    result = await writer.write("jira", "PROJ-1", {"summary": "s", **_envelope()})

    assert result.outcome == "written"
    assert await _read_back(writer, raw_index, object_store) == {"summary": "s"}  # decrypts with the stored key


@pytest.mark.asyncio
async def test_a_failing_audit_sink_does_not_hide_a_failed_write() -> None:
    writer, _, object_store, _, _, audit = _writer()

    async def broken_put(key: str, data: bytes) -> None:
        raise OSError("down")

    async def broken_record(event) -> None:
        raise RuntimeError("audit down")

    object_store.put = broken_put  # type: ignore[method-assign]
    audit.record = broken_record  # type: ignore[method-assign]

    result = await writer.write("jira", "PROJ-1", {"summary": "s", **_envelope()})

    assert result.outcome == "failed"
