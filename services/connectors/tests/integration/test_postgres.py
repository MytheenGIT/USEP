"""Checks that need a real Postgres. Skipped unless USEP_TEST_DATABASE_URL is set, e.g.

    docker run -d --name usep-pg -e POSTGRES_USER=usep -e POSTGRES_PASSWORD=usep -e POSTGRES_DB=usep_check -p 55432:5432 postgres:16
    USEP_TEST_DATABASE_URL=postgresql+asyncpg://usep:usep@localhost:55432/usep_check pytest tests/integration
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from db.base import create_engine, create_session_factory, create_tables
from db.models import AuditEventRow, CursorRow, RawObjectRow
from db.ports_sql import SqlAuditWriter, SqlRawIndex, verify_audit_chain
from usep.adapters.local_files.object_store import FileObjectStore
from usep.adapters.local_kek.key_store import LocalKeyEncryption
from usep.ingestion.ports.audit import AuditEvent
from usep.ingestion.raw.crypto import decrypt, unpack

URL = os.environ.get("USEP_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="needs USEP_TEST_DATABASE_URL (a real Postgres)")


@pytest.fixture
async def engine():
    engine = create_engine(URL)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await create_tables(engine)
    yield engine
    await engine.dispose()


async def test_tables_are_created_and_creating_them_twice_is_harmless(engine) -> None:
    await create_tables(engine)
    async with engine.connect() as conn:
        names = {r[0] for r in await conn.execute(text("select tablename from pg_tables where schemaname='public'"))}
    assert {"raw_object", "sync_cursor", "quarantine_record", "audit_event", "run_snapshot", "ingestion_sync_runs"} <= names


async def test_audit_events_can_be_added_but_never_changed_or_removed(engine) -> None:
    from datetime import UTC, datetime

    tenant, trace = uuid4(), uuid4()
    sf = create_session_factory(engine)
    await SqlAuditWriter(sf, tenant, trace, "t").record(AuditEvent(source="jira", action="a", status="ok", at=datetime.now(UTC)))
    assert await verify_audit_chain(sf, tenant, trace)

    for statement in ("UPDATE audit_event SET status = 'x'", "DELETE FROM audit_event"):
        with pytest.raises(DBAPIError) as caught:
            async with engine.begin() as conn:
                await conn.execute(text(statement))
        assert "append-only" in str(caught.value)
    async with sf() as session:
        assert await session.scalar(select(func.count()).select_from(AuditEventRow)) == 1


async def test_several_processes_syncing_the_same_scope_at_once(engine, tmp_path) -> None:
    processes, docs = 6, 20
    tenant = uuid4()
    kek = base64.b64encode(os.urandom(32)).decode()
    env = {
        **os.environ, "TENANT": str(tenant), "DATABASE_URL": URL, "STORE_DIR": str(tmp_path / "raw"),
        "KEK_B64": kek, "DOC_COUNT": str(docs), "PYTHONPATH": os.pathsep.join(sys.path),
    }
    worker = Path(__file__).with_name("mp_worker.py")
    running = [subprocess.Popen([sys.executable, str(worker)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(processes)]
    outputs = [p.communicate(timeout=120) for p in running]
    assert all(p.returncode == 0 for p in running), [o[1][-600:] for o in outputs]
    results = [json.loads(out.strip().splitlines()[-1]) for out, _ in outputs]

    sf = create_session_factory(engine)
    async with sf() as session:
        rows = list((await session.scalars(select(RawObjectRow))).all())
        cursor = await session.scalar(select(CursorRow.cursor).where(CursorRow.tenant_id == tenant))
    # one index row and one readable object per document, however many processes raced on it
    assert sorted(r.object_id for r in rows) == sorted(f"ENG-{i}" for i in range(docs))
    assert all(r.published_at is not None for r in rows), "some rows were never marked published"
    keys = LocalKeyEncryption(base64.b64decode(kek))
    store = FileObjectStore(tmp_path / "raw")
    for row in rows:
        data_key = await keys.unwrap(tenant, row.wrapped_dek, row.kek_id)
        plain = decrypt(unpack(await store.get(row.object_key)), data_key, aad=row.object_key.encode() + str(tenant).encode())
        assert json.loads(plain)["key"] == row.object_id
    assert [f for f in (tmp_path / "raw").rglob(".part-*")] == []  # no half-written files left
    # every run has its own intact audit chain, and nothing failed
    for result in results:
        assert result["status"] == "success", result
        assert await verify_audit_chain(sf, tenant, UUID(result["run_id"]))
    assert cursor == f"2026-01-01T00:00:{docs - 1:02d}.000Z"
