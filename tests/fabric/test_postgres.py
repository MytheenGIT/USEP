"""PostgreSQL-only behaviour: row-level security, migrations, concurrent relays."""
import threading

import psycopg
import pytest

from tests.fabric.helpers import node
from usep.adapters.postgres import migrate
from usep.adapters.postgres.migrate import MIGRATIONS
from usep.fabric import FabricWriter, OutboxRelay


def test_row_level_security_isolates_tenants_for_a_non_owner_role(pg_store, pg_dsn):
    w = FabricWriter(pg_store)
    w.handle(node(tenant="t1")); w.handle(node(tenant="t2", sid="X-1"))
    with psycopg.connect(pg_dsn, autocommit=True) as admin:
        admin.execute("DROP ROLE IF EXISTS fabric_reader")
        admin.execute("CREATE ROLE fabric_reader NOLOGIN")
        admin.execute("GRANT SELECT ON fabric_entity_state, fabric_edge, fabric_assertion TO fabric_reader")
    with psycopg.connect(pg_dsn) as c:
        c.execute("SET ROLE fabric_reader")
        c.execute("SELECT set_config('app.tenant_id', 't1', true)")
        assert [r[0] for r in c.execute("SELECT tenant_id FROM fabric_entity_state").fetchall()] == ["t1"]
        c.execute("SELECT set_config('app.tenant_id', '', true)")
        assert c.execute("SELECT count(*) FROM fabric_entity_state").fetchone()[0] == 0     # no tenant set: nothing visible
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("INSERT INTO fabric_entity_state (tenant_id) VALUES ('t1')")


def test_a_write_for_another_tenant_is_refused_by_the_database(pg_store, pg_dsn):
    with psycopg.connect(pg_dsn) as c:
        c.execute("DROP ROLE IF EXISTS fabric_writer_r")
        c.execute("CREATE ROLE fabric_writer_r NOLOGIN")
        c.execute("GRANT INSERT, SELECT ON fabric_entity TO fabric_writer_r")
        c.commit()
        c.execute("SET ROLE fabric_writer_r")
        c.execute("SELECT set_config('app.tenant_id', 't1', true)")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):   # row-level security: WITH CHECK fails
            c.execute("INSERT INTO fabric_entity (tenant_id, entity_id, type, domain) VALUES "
                      "('t2', gen_random_uuid(), 'Issue', 'engineering')")


def test_migrations_are_applied_once_and_a_changed_file_is_refused(pg_dsn, tmp_path, monkeypatch):
    with psycopg.connect(pg_dsn) as c:
        assert migrate(c) == []                                    # already applied by the fixture
    d = tmp_path / "m"
    d.mkdir()
    (d / "0001_fabric.sql").write_text((MIGRATIONS / "0001_fabric.sql").read_text() + "\n-- edited\n")
    import sys
    m = sys.modules["usep.adapters.postgres.migrate"]       # the package re-exports the function under the same name
    monkeypatch.setattr(m, "MIGRATIONS", d)
    with psycopg.connect(pg_dsn) as c, pytest.raises(RuntimeError, match="changed after it was applied"):
        m.migrate(c)


def test_two_relays_never_publish_the_same_row_twice_at_once(pg_store):
    w = FabricWriter(pg_store)
    for i in range(20):
        w.handle(node(sid=f"A-{i}"))
    got, lock = [], threading.Lock()

    class Bus:
        def publish(self, topic, key, type, tenant_id, payload, headers=None):
            with lock:
                got.append(payload["idempotency_key"])

    def run():
        OutboxRelay(pg_store, Bus(), batch_size=5).drain()

    ts = [threading.Thread(target=run) for _ in range(2)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert sorted(got) == sorted(set(got)) and len(got) == 20 and pg_store.outbox_status().pending == 0
