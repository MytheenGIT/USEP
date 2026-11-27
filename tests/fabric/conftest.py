import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # tests/ on the path for fake_s3

from tests.fabric.memory_store import MemoryFabricStore

TABLES = ("fabric_applied fabric_assertion fabric_edge fabric_entity_state fabric_source_identity fabric_entity "
          "fabric_rejected fabric_outbox")


@pytest.fixture(scope="session")
def pg_dsn(tmp_path_factory):
    """A real PostgreSQL: USEP_TEST_PG_DSN if set, else an embedded server (pixeltable-pgserver) if installed."""
    import os
    dsn = os.environ.get("USEP_TEST_PG_DSN")
    server = None
    if not dsn:
        try:
            import pixeltable_pgserver
            server = pixeltable_pgserver.get_server(tmp_path_factory.mktemp("pg"))
            dsn = server.get_uri()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"no PostgreSQL for tests: {exc}")
    import psycopg

    from usep.adapters.postgres import migrate
    with psycopg.connect(dsn) as c:
        migrate(c)
    yield dsn
    if server is not None:
        server.cleanup()


@pytest.fixture
def pg_store(pg_dsn):
    import psycopg

    from usep.adapters.postgres import PostgresFabricStore
    with psycopg.connect(pg_dsn, autocommit=True) as c:
        c.execute(f"TRUNCATE {TABLES.replace(' ', ', ')} RESTART IDENTITY")
    return PostgresFabricStore(pg_dsn)


@pytest.fixture(params=["memory", "postgres"])
def store(request):
    """Every behaviour test runs against the in-memory store and a real PostgreSQL."""
    if request.param == "memory":
        return MemoryFabricStore()
    return request.getfixturevalue("pg_store")
