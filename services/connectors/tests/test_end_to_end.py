"""Connector -> SyncService -> foundation writer -> encrypted object in S3 (mocked), with the
real SQL index, cursor store and quarantine on SQLite, and the real key wrapping."""

from __future__ import annotations

import json
import os
from uuid import uuid4

import boto3
import pytest
from moto import mock_aws

from common.event_publisher import LogEventPublisher
from common.source_document import SourceType
from common.sync_models import SyncStatus
from db.base import create_engine, create_session_factory, create_tables
from db.ports_sql import SqlCursorStore, SqlQuarantine, SqlRawIndex
from sqlalchemy import func, select
from db.models import QuarantineRow
from sync_service import SyncService, scope_id
from db.models import AuditEventRow, RunSnapshotRow
from db.ports_sql import SqlAuditWriter, SqlRunSnapshots, verify_audit_chain
from tests.conftest import FakeConnector, RecordingAuditWriter, make_source_document
from usep.adapters.local_kek.key_store import LocalKeyEncryption
from usep.adapters.s3.object_store import S3ObjectStore
from usep.core.clock import SystemClock
from usep.ingestion.cursor.manager import CursorManager
from usep.ingestion.raw.crypto import decrypt, unpack
from usep.ingestion.raw.writer import RawPayloadWriter

TENANT = uuid4()
SCOPE = "project = A"


class Stack:
    def __init__(self, session_factory, s3, connector, store=None) -> None:
        self.session_factory = session_factory
        self.s3 = s3
        self.index = SqlRawIndex(session_factory)
        self.keys = LocalKeyEncryption(os.urandom(32))
        self.cursors = SqlCursorStore(session_factory, TENANT)
        quarantine = SqlQuarantine(session_factory)
        store = store or S3ObjectStore(s3, "raw")
        self.store = store
        self.service = SyncService(
            connectors={"jira": connector},
            cursor_manager=CursorManager(self.cursors, overlap_seconds=0),
            writer_factory=lambda run_id, audit: RawPayloadWriter(
                self.index, store, self.keys, LogEventPublisher(), quarantine, audit, SystemClock(), TENANT, run_id
            ),
            audit_writer_factory=lambda run_id: SqlAuditWriter(session_factory, TENANT, run_id, "test"),
            record_snapshot=lambda run_id, source, scopes: SqlRunSnapshots(session_factory, TENANT).record(
                run_id, source, {"scopes": scopes, "base_url": "https://x", "api_token": "SECRET", "email": "a@b.c"}
            ),
        )

    def object_keys(self) -> list[str]:
        return [o["Key"] for o in self.s3.list_objects_v2(Bucket="raw").get("Contents", [])]


@pytest.fixture
async def make_stack(tmp_path):
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/ingest.db")
    await create_tables(engine)
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="raw")
        yield lambda connector, store=None: Stack(create_session_factory(engine), s3, connector, store)
    await engine.dispose()


def _doc(object_id="ABC-1", version="2026-01-01T00:00:00.000Z", **payload):
    doc = make_source_document(source_object_id=object_id, source_version=version)
    doc.raw_payload = {"key": object_id, **payload}
    return doc


async def test_document_lands_encrypted_in_s3_and_can_be_read_back(make_stack) -> None:
    stack = make_stack(FakeConnector(SourceType.JIRA, [_doc(summary="Checkout is slow")], scopes=[SCOPE]))

    result = await stack.service.sync_source("jira")

    assert result.status == SyncStatus.SUCCESS and result.documents_count == 1
    [key] = stack.object_keys()
    assert key.startswith(f"raw/{TENANT}/jira/{scope_id(SCOPE)}/issue/ABC-1/") and key.endswith(".json")
    blob = await stack.store.get(key)
    assert b"Checkout is slow" not in blob  # ciphertext only

    [ref] = await stack.index.list_extant_by_scope(TENANT, "jira", scope_id(SCOPE))
    assert ref.published_at is not None and ref.object_key == key
    data_key = await stack.keys.unwrap(TENANT, ref.wrapped_dek, ref.kek_id)
    plain = decrypt(unpack(blob), data_key, aad=key.encode() + str(TENANT).encode())
    assert json.loads(plain) == {"key": "ABC-1", "summary": "Checkout is slow"}  # the envelope is not stored

    assert await stack.cursors.get_cursor(f"jira:{SCOPE}:live") == "2026-01-01T00:00:00.000Z"


async def test_second_run_with_unchanged_data_writes_nothing_new(make_stack) -> None:
    stack = make_stack(FakeConnector(SourceType.JIRA, [_doc(summary="same")], scopes=[SCOPE]))

    await stack.service.sync_source("jira")
    keys_after_first = stack.object_keys()
    second = await stack.service.sync_source("jira")

    assert second.status == SyncStatus.SUCCESS
    assert stack.object_keys() == keys_after_first
    assert len(await stack.index.list_extant_by_scope(TENANT, "jira", scope_id(SCOPE))) == 1


async def test_changed_document_gets_a_new_object_and_keeps_the_old_one(make_stack) -> None:
    connector = FakeConnector(SourceType.JIRA, [_doc(summary="v1")], scopes=[SCOPE])
    stack = make_stack(connector)
    await stack.service.sync_source("jira")

    connector._documents = [_doc(version="2026-01-02T00:00:00.000Z", summary="v2")]
    await stack.service.sync_source("jira")

    assert len(stack.object_keys()) == 2
    assert await stack.cursors.get_cursor(f"jira:{SCOPE}:live") == "2026-01-02T00:00:00.000Z"


async def test_personal_data_is_quarantined_not_stored_or_reported(make_stack) -> None:
    doc = _doc(description="card on file 4111 1111 1111 1111")
    stack = make_stack(FakeConnector(SourceType.JIRA, [doc], scopes=[SCOPE]))

    result = await stack.service.sync_source("jira")

    assert result.documents_count == 0 and result.errors == []
    assert stack.object_keys() == []
    async with stack.session_factory() as session:
        row = (await session.scalars(select(QuarantineRow))).one()
    assert (row.reason_code, row.object_id) == ("Q-PII", "ABC-1")
    assert "4111" not in json.dumps(row.detector_counts)
    assert await stack.cursors.get_cursor(f"jira:{SCOPE}:live") == "2026-01-01T00:00:00.000Z"


async def test_s3_failure_holds_the_cursor_so_the_object_is_retried(make_stack) -> None:
    stack = make_stack(FakeConnector(SourceType.JIRA, [_doc(summary="x")], scopes=[SCOPE]))
    real_put = stack.store.put

    async def broken_put(key, data):
        raise OSError("s3 unavailable")

    stack.store.put = broken_put
    first = await stack.service.sync_source("jira")
    assert first.status == SyncStatus.PARTIAL and first.documents_count == 0
    # The cursor is held at the failed object's own version, so the next run fetches it again.
    assert await stack.cursors.get_cursor(f"jira:{SCOPE}:live") == "2026-01-01T00:00:00.000Z"
    assert stack.object_keys() == []

    stack.store.put = real_put
    second = await stack.service.sync_source("jira")
    assert second.documents_count == 1 and len(stack.object_keys()) == 1


async def test_every_run_has_a_verifiable_hash_chained_audit_trail(make_stack) -> None:
    stack = make_stack(FakeConnector(SourceType.JIRA, [_doc(summary="x")], scopes=[SCOPE]))

    result = await stack.service.sync_source("jira")

    from uuid import UUID

    run_id = UUID(result.run_id)
    async with stack.session_factory() as session:
        rows = list((await session.scalars(select(AuditEventRow).where(AuditEventRow.trace_id == run_id).order_by(AuditEventRow.id))).all())
    actions = [r.action for r in rows]
    assert "object.imported" in actions and actions[-1] == "sync"  # writer events and sync events share one chain
    assert rows[0].prev_hash is None and all(r.prev_hash == p.hash for p, r in zip(rows, rows[1:]))
    assert await verify_audit_chain(stack.session_factory, TENANT, run_id)

    async with stack.session_factory() as session:  # tamper with the first event
        first = await session.get(AuditEventRow, rows[0].id)
        first.status = "tampered"
        await session.commit()
    assert not await verify_audit_chain(stack.session_factory, TENANT, run_id)


async def test_run_snapshot_keeps_config_but_never_secrets(make_stack) -> None:
    stack = make_stack(FakeConnector(SourceType.JIRA, [], scopes=[SCOPE]))

    result = await stack.service.sync_source("jira")

    from uuid import UUID

    async with stack.session_factory() as session:
        snap = await session.get(RunSnapshotRow, UUID(result.run_id))
    assert snap.config == {"scopes": [SCOPE], "base_url": "https://x"}
    assert snap.config_hash


async def test_read_raw_tool_decrypts_a_landed_object(make_stack) -> None:
    from tools.read_raw import read_raw_object

    stack = make_stack(FakeConnector(SourceType.JIRA, [_doc(summary="visible in the demo")], scopes=[SCOPE]))
    await stack.service.sync_source("jira")
    [key] = stack.object_keys()

    assert await read_raw_object(stack.index, stack.store, stack.keys, TENANT, key) == {"key": "ABC-1", "summary": "visible in the demo"}
    with pytest.raises(LookupError):
        await read_raw_object(stack.index, stack.store, stack.keys, TENANT, "raw/nope")


def test_scope_id_is_key_safe_and_stable() -> None:
    assert scope_id("group/project") == "group/project"
    assert scope_id("ENG") == "ENG"
    hashed = scope_id('project = "A B" AND updated > -30d ORDER BY updated ASC')
    assert hashed.startswith("s-") and len(hashed) == 18 and hashed == scope_id('project = "A B" AND updated > -30d ORDER BY updated ASC')
    assert len(scope_id("x" * 5000)) == 18  # long scopes cannot push the key past the S3 limit


async def test_tombstone_shreds_only_the_chosen_version(make_stack) -> None:
    import dataclasses
    from datetime import UTC, datetime

    from usep.ingestion.domain.raw_object import RawObjectRef

    stack = make_stack(FakeConnector(SourceType.JIRA, [], scopes=[SCOPE]))
    now = datetime.now(UTC)

    def ref(content_hash: str) -> RawObjectRef:
        return RawObjectRef(
            tenant_id=TENANT, source="jira", object_type="issue", object_id="ABC-1", content_hash=content_hash,
            scope_id="s", object_key=f"raw/{content_hash}", byte_size=1, run_id=uuid4(), imported_at=now,
            published_at=now, wrapped_dek=b"key-" + content_hash.encode(), kek_id="k",
        )

    old, new = ref("a" * 64), ref("b" * 64)
    assert await stack.index.insert_if_absent(old) and await stack.index.insert_if_absent(new)
    assert not await stack.index.insert_if_absent(dataclasses.replace(old, byte_size=9))  # a second insert is refused

    await stack.index.mark_first_seen_extra(old, at=now)
    await stack.index.mark_first_seen_extra(old, at=datetime(2030, 1, 1, tzinfo=UTC))  # only the first sighting counts
    await stack.index.tombstone(old, at=now)

    shredded = await stack.index.find(TENANT, "jira", "issue", "ABC-1", old.content_hash)
    kept = await stack.index.find(TENANT, "jira", "issue", "ABC-1", new.content_hash)
    assert shredded.wrapped_dek is None and shredded.tombstoned_at is not None
    assert shredded.first_seen_extra_at == now
    assert kept.wrapped_dek == new.wrapped_dek and kept.tombstoned_at is None
    assert [r.content_hash for r in await stack.index.list_extant_by_scope(TENANT, "jira", "s")] == [new.content_hash]


async def test_audit_writer_copes_with_details_that_are_not_json(make_stack) -> None:
    from datetime import UTC, datetime

    from usep.ingestion.ports.audit import AuditEvent

    stack = make_stack(FakeConnector(SourceType.JIRA, [], scopes=[SCOPE]))
    writer = SqlAuditWriter(stack.session_factory, TENANT, None, "test")

    await writer.record(
        AuditEvent(source="jira", action="sync", status="failed", at=datetime.now(UTC), details={"error": RuntimeError("boom"), "obj": object()})
    )

    assert await verify_audit_chain(stack.session_factory, TENANT, None)


async def test_objects_land_as_files_in_the_repo_folder_with_the_same_keys_as_s3(make_stack, tmp_path) -> None:
    from tools.read_raw import read_raw_object
    from usep.adapters.local_files.object_store import FileObjectStore

    stack = make_stack(FakeConnector(SourceType.JIRA, [_doc(summary="in a file")], scopes=[SCOPE]), FileObjectStore(tmp_path / "raw"))

    result = await stack.service.sync_source("jira")

    assert result.status == SyncStatus.SUCCESS
    [path] = [p for p in (tmp_path / "raw").rglob("*.json")]
    key = path.relative_to(tmp_path / "raw").as_posix()
    assert key.startswith(f"raw/{TENANT}/jira/") and key.endswith(".json")
    assert b"in a file" not in path.read_bytes()  # encrypted on disk, exactly as it will be in S3
    assert await read_raw_object(stack.index, stack.store, stack.keys, TENANT, key) == {"key": "ABC-1", "summary": "in a file"}
    assert stack.object_keys() == []  # nothing went to the (mocked) S3 bucket
