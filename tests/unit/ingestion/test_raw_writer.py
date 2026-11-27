from __future__ import annotations

import datetime as dt
import logging
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from tests.fakes.audit import InMemoryAudit
from tests.fakes.clock import FakeClock
from tests.fakes.event_bus import InMemoryEventBus
from tests.fakes.key_store import InMemoryKeyEncryption
from tests.fakes.object_store import InMemoryObjectStore
from tests.fakes.quarantine import InMemoryQuarantine
from tests.fakes.raw_index import InMemoryRawIndex

from usep.core.errors import UsepError
from usep.core.ids import new_id
from usep.ingestion.domain.raw_object import RawObjectRef, canonicalize, content_hash, object_key
from usep.ingestion.ports.audit import AuditEvent
from usep.ingestion.raw.crypto import decrypt, encrypt, generate_data_key, pack, unpack
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


class _FindMissesOnce(InMemoryRawIndex):
    """Simulates the race window: the first `find()` sees no row even though another
    writer has already inserted one."""

    def __init__(self) -> None:
        super().__init__()
        self._find_called = False

    async def find(
        self, tenant_id: UUID, source: str, object_type: str, object_id: str, content_hash: str
    ) -> RawObjectRef | None:
        if not self._find_called:
            self._find_called = True
            return None
        return await super().find(tenant_id, source, object_type, object_id, content_hash)


async def _lost_race() -> tuple[
    RawPayloadWriter, InMemoryObjectStore, InMemoryEventBus, RawObjectRef, bytes, bytes
]:
    """A writer that loses the insert race to a writer whose row and ciphertext already exist."""
    raw_index = _FindMissesOnce()
    object_store = InMemoryObjectStore()
    key_store = InMemoryKeyEncryption()
    event_bus = InMemoryEventBus()
    writer = RawPayloadWriter(
        raw_index,
        object_store,
        key_store,
        event_bus,
        InMemoryQuarantine(),
        InMemoryAudit(),
        FakeClock(),
        TENANT,
        RUN,
    )
    payload = {"summary": "v1", **_envelope()}
    stripped, object_type, scope_id, _ = _extract_envelope(payload)
    canonical = canonicalize(stripped)
    digest = content_hash(canonical)
    key = object_key(TENANT, "jira", scope_id, object_type, "PROJ-1", digest)
    aad = key.encode("utf-8") + str(TENANT).encode("utf-8")

    winner_key = generate_data_key()
    wrapped, kek_id = await key_store.wrap(TENANT, winner_key)
    object_store.objects[key] = pack(encrypt(canonical, winner_key, aad=aad))
    winner_row = RawObjectRef(
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
        wrapped_dek=wrapped,
        kek_id=kek_id,
        event_id=new_id(),
    )
    raw_index._rows[(TENANT, "jira", object_type, "PROJ-1", digest)] = winner_row
    return writer, object_store, event_bus, winner_row, winner_key, aad


@pytest.mark.asyncio
async def test_race_publishes_the_stored_event_id() -> None:
    writer, _, event_bus, winner_row, _, _ = await _lost_race()

    result = await writer.write("jira", "PROJ-1", {"summary": "v1", **_envelope()})

    assert result.startswith("raw/")
    assert event_bus.published[0].event_id == winner_row.event_id


@pytest.mark.asyncio
async def test_race_loser_leaves_ciphertext_readable_with_the_stored_key() -> None:
    writer, object_store, _, winner_row, winner_key, aad = await _lost_race()

    await writer.write("jira", "PROJ-1", {"summary": "v1", **_envelope()})

    stored = unpack(object_store.objects[winner_row.object_key])
    assert decrypt(stored, winner_key, aad=aad) == canonicalize({"summary": "v1"})


@pytest.mark.asyncio
async def test_object_restored_after_tombstone_is_readable_and_published_again() -> None:
    raw_index, object_store, key_store = InMemoryRawIndex(), InMemoryObjectStore(), InMemoryKeyEncryption()
    event_bus = InMemoryEventBus()
    writer = RawPayloadWriter(
        raw_index,
        object_store,
        key_store,
        event_bus,
        InMemoryQuarantine(),
        InMemoryAudit(),
        FakeClock(),
        TENANT,
        RUN,
    )
    payload = {"summary": "v1", **_envelope()}
    await writer.write("jira", "PROJ-1", payload)
    await raw_index.tombstone(raw_index.all_refs()[0], at=dt.datetime.now(dt.UTC))

    await writer.write("jira", "PROJ-1", payload)

    row = raw_index.all_refs()[0]
    assert row.tombstoned_at is None
    assert row.wrapped_dek is not None
    data_key = await key_store.unwrap(TENANT, row.wrapped_dek, row.kek_id)
    aad = row.object_key.encode("utf-8") + str(TENANT).encode("utf-8")
    assert decrypt(unpack(object_store.objects[row.object_key]), data_key, aad=aad) == canonicalize(
        {"summary": "v1"}
    )
    assert len(event_bus.published) == 2
    assert event_bus.published[0].event_id != event_bus.published[1].event_id


class _FirstFindSeesStaleRow(InMemoryRawIndex):
    """The first `find()` returns a row as it was before another writer changed it."""

    def __init__(self) -> None:
        super().__init__()
        self.stale_row: RawObjectRef | None = None

    async def find(
        self, tenant_id: UUID, source: str, object_type: str, object_id: str, content_hash: str
    ) -> RawObjectRef | None:
        if self.stale_row is not None:
            row, self.stale_row = self.stale_row, None
            return row
        return await super().find(tenant_id, source, object_type, object_id, content_hash)


@pytest.mark.asyncio
async def test_restore_race_loser_leaves_ciphertext_readable_with_the_stored_key() -> None:
    raw_index, object_store, key_store = (
        _FirstFindSeesStaleRow(),
        InMemoryObjectStore(),
        InMemoryKeyEncryption(),
    )
    writer = RawPayloadWriter(
        raw_index,
        object_store,
        key_store,
        InMemoryEventBus(),
        InMemoryQuarantine(),
        InMemoryAudit(),
        FakeClock(),
        TENANT,
        RUN,
    )
    payload = {"summary": "v1", **_envelope()}
    await writer.write("jira", "PROJ-1", payload)
    await raw_index.tombstone(raw_index.all_refs()[0], at=dt.datetime.now(dt.UTC))
    tombstoned = raw_index.all_refs()[0]
    raw_index.stale_row = tombstoned  # our writer sees the tombstoned row...

    # ...but another writer revives it first, with its own key and ciphertext.
    winner_key = generate_data_key()
    aad = tombstoned.object_key.encode("utf-8") + str(TENANT).encode("utf-8")
    wrapped, kek_id = await key_store.wrap(TENANT, winner_key)
    object_store.objects[tombstoned.object_key] = pack(
        encrypt(canonicalize({"summary": "v1"}), winner_key, aad=aad)
    )
    await raw_index.revive(
        replace(tombstoned, wrapped_dek=wrapped, kek_id=kek_id, event_id=new_id(), tombstoned_at=None)
    )

    await writer.write("jira", "PROJ-1", payload)

    stored = raw_index.all_refs()[0]
    assert stored.wrapped_dek == wrapped
    blob = unpack(object_store.objects[stored.object_key])
    assert decrypt(blob, winner_key, aad=aad) == canonicalize({"summary": "v1"})


@pytest.mark.asyncio
async def test_race_against_a_tombstoned_row_fails_instead_of_unwrapping_nothing() -> None:
    writer, _, event_bus, winner_row, _, _ = await _lost_race()
    writer._raw_index._rows[  # type: ignore[attr-defined]
        (TENANT, "jira", winner_row.object_type, "PROJ-1", winner_row.content_hash)
    ] = replace(winner_row, wrapped_dek=None, tombstoned_at=dt.datetime.now(dt.UTC))

    result = await writer.write("jira", "PROJ-1", {"summary": "v1", **_envelope()})

    assert result == "failed://RawStorageError"
    assert event_bus.published == []


@pytest.mark.parametrize("bad_value", [5, "", None, ["issue"]])
def test_envelope_field_must_be_a_non_empty_string(bad_value: object) -> None:
    payload = {"summary": "v1", "_usep": {"object_type": bad_value, "scope_id": "PROJ", "checkpoint": "c1"}}

    with pytest.raises(EnvelopeError, match="object_type"):
        _extract_envelope(payload)


def test_envelope_error_is_a_usep_error_and_a_value_error() -> None:
    assert issubclass(EnvelopeError, UsepError)
    assert issubclass(EnvelopeError, ValueError)


class _AuditDownOnFailures(InMemoryAudit):
    async def record(self, event: AuditEvent) -> None:
        if event.status == "failed":
            raise ConnectionError("audit store unreachable")
        await super().record(event)


_ECHOED_SECRET = "secret glpat-abcdefghijklmnopqrstuvwxyz"  # SYNTHETIC


class _BrokenObjectStore(InMemoryObjectStore):
    async def put(self, key: str, data: bytes) -> None:
        raise RuntimeError(f"storage said: {_ECHOED_SECRET}")


def _failing_writer(audit: InMemoryAudit) -> RawPayloadWriter:
    return RawPayloadWriter(
        InMemoryRawIndex(),
        _BrokenObjectStore(),
        InMemoryKeyEncryption(),
        InMemoryEventBus(),
        InMemoryQuarantine(),
        audit,
        FakeClock(),
        TENANT,
        RUN,
    )


@pytest.mark.asyncio
async def test_storage_failure_is_logged_with_type_and_frames_but_not_the_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    writer = _failing_writer(InMemoryAudit())

    with caplog.at_level(logging.ERROR, logger="usep.ingestion.raw.writer"):
        result = await writer.write("jira", "PROJ-1", {"summary": "v1", **_envelope()})

    assert result == "failed://RuntimeError"
    record = next(r for r in caplog.records if r.getMessage() == "raw object write failed")
    assert record.exception_type == "RuntimeError"  # type: ignore[attr-defined]
    assert "put" in record.frames  # type: ignore[attr-defined]
    assert "glpat" not in caplog.text
    assert "glpat" not in record.frames  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_audit_outage_does_not_turn_a_failed_write_into_a_raised_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    writer = _failing_writer(_AuditDownOnFailures())

    with caplog.at_level(logging.ERROR, logger="usep.ingestion.raw.writer"):
        result = await writer.write("jira", "PROJ-1", {"summary": "v1", **_envelope()})

    assert result == "failed://RuntimeError"
    assert "audit record failed while reporting a failure" in caplog.text


@pytest.mark.asyncio
async def test_audit_outage_does_not_replace_the_envelope_error() -> None:
    writer = _failing_writer(_AuditDownOnFailures())

    with pytest.raises(EnvelopeError):
        await writer.write("jira", "PROJ-1", {"summary": "no envelope"})
