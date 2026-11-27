"""The audit trail in files (default), in an object store (S3) and its use by the service."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from tests.test_console_api import _auth, _make_client
from usep.adapters.local_files.audit import FileAuditWriter, read_records, trace_file, verify_audit_file
from usep.adapters.local_files.object_store import FileObjectStore
from usep.adapters.s3.audit import ObjectStoreAuditWriter
from usep.ingestion import audit_chain
from usep.ingestion.ports.audit import AuditEvent

TENANT = uuid.uuid4()


def _event(n: int) -> AuditEvent:
    return AuditEvent(source="jira", action=f"a{n}", status="success", at=datetime.now(UTC), details={"n": n})


async def test_file_trail_is_chained_continues_after_restart_and_shows_tampering(tmp_path) -> None:
    run = uuid.uuid4()
    for n in range(2):
        await FileAuditWriter(tmp_path, TENANT, run, "t").record(_event(n))  # a new writer = a restarted process
    await FileAuditWriter(tmp_path, TENANT, run, "t").record(_event(2))
    path = trace_file(tmp_path, run)
    records = read_records(path)
    assert [r["action"] for r in records] == ["a0", "a1", "a2"] and verify_audit_file(path)
    assert all(r["tenant_id"] == str(TENANT) and r["trace_id"] == str(run) and r["app_version"] == "t" for r in records)
    path.write_text(path.read_text().replace('"n":1', '"n":9'))
    assert not verify_audit_file(path)


async def test_object_store_trail_writes_one_chained_object_per_event(tmp_path) -> None:
    store = FileObjectStore(tmp_path)
    writer = ObjectStoreAuditWriter(store, TENANT, None, "t")
    for n in range(3):
        await writer.record(_event(n))
    files = sorted((tmp_path / "audit" / str(TENANT) / "console").iterdir())
    records = [json.loads(f.read_text()) for f in files]
    assert [r["action"] for r in records] == ["a0", "a1", "a2"] and audit_chain.verify(records)


def test_every_call_to_the_service_is_in_the_audit_trail_without_secrets(tmp_path, monkeypatch) -> None:
    with _make_client(tmp_path, monkeypatch) as c:
        c.post("/api/auth/login", json={"username": "admin", "password": "wrong-password-xyz"})
        headers = _auth(c)
        c.get("/api/configurations", headers=headers)
        c.get("/api/configurations", headers={"Authorization": "Bearer nope"})
        c.get("/health")
    path = tmp_path / "audit" / "console.jsonl"
    records = read_records(path)
    assert verify_audit_file(path)
    http = [r for r in records if r["action"] == "http.request"]
    assert {"actor", "request_id", "method", "path", "status_code", "duration_ms", "client_ip"} <= set(http[0]["details"])
    assert any(r["details"]["path"] == "/api/configurations" and r["details"]["actor"] == "admin" for r in http)
    assert any(r["details"]["status_code"] == 401 and r["status"] == "denied" for r in http)
    assert not any(r["details"]["path"] == "/health" for r in http)
    actions = {r["action"] for r in records}
    assert {"service.start", "auth.login", "service.stop"} <= actions
    text = path.read_text()
    assert "wrong-password-xyz" not in text and "s3cret-test" not in text and "Bearer" not in text


def test_a_processed_configuration_leaves_a_chained_trail_per_run_and_console_events(tmp_path, monkeypatch) -> None:
    from tests.test_console_api import JIRA, _only, _wait_done

    with _make_client(tmp_path, monkeypatch) as c:
        headers = _auth(c)
        created = c.post("/api/configurations", json=_only(jira=JIRA), headers=headers)
        _wait_done(c, headers, created.json()["id"])
    runs = list((tmp_path / "audit" / "runs").glob("*.jsonl"))
    assert runs and all(verify_audit_file(p) for p in runs)
    assert "sync_scope" in {r["action"] for p in runs for r in read_records(p)}
    console = read_records(tmp_path / "audit" / "console.jsonl")
    assert {"configuration.create", "http.request"} <= {r["action"] for r in console}
