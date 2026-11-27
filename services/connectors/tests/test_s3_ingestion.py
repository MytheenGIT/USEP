from __future__ import annotations

import json

import pytest

from common.checksum import payload_checksum
from common.s3.cursor_manager import S3CursorManager
from common.s3.raw_event_publisher import S3RawEventPublisher
from common.s3.raw_payload_writer import S3RawPayloadWriter
from common.source_document import SourceType
from common.sync_models import SyncStatus
from sync_service import SyncService
from tests.conftest import FakeConnector, make_source_document
from tests.fake_s3 import FakeS3

TENANT = "0190aaaa-0000-7000-8000-000000000001"


def build(s3: FakeS3, connector, audit_writer):
    cursors = S3CursorManager(s3, "b")
    service = SyncService(
        connectors={"jira": connector}, cursor_manager=cursors,
        raw_payload_writer=S3RawPayloadWriter(s3, "b"),
        raw_event_publisher=S3RawEventPublisher(s3, "b", TENANT, partitions=4),
        audit_writer=audit_writer,
    )
    return service, cursors


def keys(s3: FakeS3, prefix: str) -> list[str]:
    return sorted(k for k in s3.objects if k.startswith(prefix))


@pytest.mark.asyncio
async def test_snapshot_then_event_then_cursor(audit_writer) -> None:
    s3, doc = FakeS3(), make_source_document(source_object_id="ABC-1")
    service, cursors = build(s3, FakeConnector(SourceType.JIRA, [doc]), audit_writer)

    result = await service.sync_source("jira")

    assert result.status == SyncStatus.SUCCESS
    checksum = payload_checksum(doc.raw_payload)
    assert keys(s3, "raw/") == [f"raw/jira/ABC-1/{checksum}.json"]
    (event_key,) = keys(s3, "bus/raw.jira/")
    envelope = json.loads(s3.objects[event_key])
    assert envelope["tenant_id"] == TENANT and envelope["key"] == "ABC-1"
    assert envelope["payload"]["snapshot_ref"] == f"s3://b/raw/jira/ABC-1/{checksum}.json"
    assert envelope["payload"]["checksum"] == checksum
    assert "raw_payload" not in envelope["payload"]            # events carry references, never the payload
    assert await cursors.get_cursor("jira:default") == doc.source_version       # cursors are per scope


@pytest.mark.asyncio
async def test_publish_failure_is_an_object_error_and_pins_the_cursor(audit_writer) -> None:
    s3 = FakeS3()
    s3.fail_put_prefix = "bus/"
    doc = make_source_document()
    service, cursors = build(s3, FakeConnector(SourceType.JIRA, [doc]), audit_writer)

    result = await service.sync_source("jira")

    assert result.status == SyncStatus.PARTIAL and result.documents_count == 0
    (err,) = result.object_errors
    assert err.object_id == "ABC-1" and "raw landing failed" in err.error
    # The cursor stops at the failed object's own version, and fetches are ">= cursor", so the next run retries it.
    assert await cursors.get_cursor("jira:default") == doc.source_version
    assert len(keys(s3, "raw/")) == 1                          # the snapshot was already durable


@pytest.mark.asyncio
async def test_rerun_does_not_duplicate_snapshots(audit_writer) -> None:
    s3, doc = FakeS3(), make_source_document()
    service, _ = build(s3, FakeConnector(SourceType.JIRA, [doc]), audit_writer)
    await service.sync_source("jira")
    await service.sync_source("jira")
    assert len(keys(s3, "raw/")) == 1                          # same checksum, same key
    assert len(keys(s3, "bus/raw.jira/")) == 2                 # at least once: consumers dedupe on (ref, checksum)


@pytest.mark.asyncio
async def test_source_id_with_slashes_is_one_key_segment(audit_writer) -> None:
    s3, doc = FakeS3(), make_source_document(source_object_id="grp/proj!45")
    service, _ = build(s3, FakeConnector(SourceType.JIRA, [doc]), audit_writer)
    await service.sync_source("jira")
    assert keys(s3, "raw/")[0].startswith("raw/jira/grp%2Fproj%2145/")


def test_publisher_requires_tenant() -> None:
    with pytest.raises(ValueError):
        S3RawEventPublisher(FakeS3(), "b", "")


@pytest.mark.asyncio
async def test_cursor_key_with_a_jql_scope_is_a_safe_s3_key() -> None:
    s3 = FakeS3()
    cursors = S3CursorManager(s3, "b")
    await cursors.set_cursor("jira:project = ABC AND type in (Story, Bug)", "2026-01-01T00:00:00.000Z")
    (key,) = keys(s3, "state/connectors/")
    assert key.count("/") == 2 and " " not in key and "(" not in key          # one segment, nothing needing escapes
    assert await cursors.get_cursor("jira:project = ABC AND type in (Story, Bug)") == "2026-01-01T00:00:00.000Z"


@pytest.mark.asyncio
async def test_raw_event_carries_scope_version_and_acl_but_not_content(audit_writer) -> None:
    s3 = FakeS3()
    doc = make_source_document()
    doc.scope, doc.acl = "project = ABC", {"project_key": "ABC", "security_level": "Finance"}
    service, _ = build(s3, FakeConnector(SourceType.JIRA, [doc]), audit_writer)
    await service.sync_source("jira")
    (event_key,) = keys(s3, "bus/raw.jira/")
    payload = json.loads(s3.objects[event_key])["payload"]
    assert payload["scope"] == "project = ABC" and payload["source_version"] == doc.source_version
    assert payload["acl"] == {"project_key": "ABC", "security_level": "Finance"}
    assert "raw_payload" not in payload and "content" not in payload
