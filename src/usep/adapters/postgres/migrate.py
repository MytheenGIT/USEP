"""Apply the SQL migrations in order, once each, in one transaction per file. Plain SQL, no framework."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

MIGRATIONS = Path(__file__).parent / "migrations"


def migrate(conn: Any) -> list[str]:
    """Apply pending migrations. Returns the names applied. Refuses a migration whose file changed after it was applied."""
    conn.execute("CREATE TABLE IF NOT EXISTS fabric_schema_migrations (name text PRIMARY KEY, sha256 text NOT NULL, "
                 "applied_at timestamptz NOT NULL DEFAULT now())")
    conn.commit()
    done = {(r["name"], r["sha256"]) if isinstance(r, dict) else tuple(r) for r in conn.execute(
        "SELECT name, sha256 FROM fabric_schema_migrations").fetchall()}
    done = dict(done)
    applied: list[str] = []
    for f in sorted(MIGRATIONS.glob("*.sql")):
        sql = f.read_bytes()
        digest = hashlib.sha256(sql.replace(b"\r\n", b"\n")).hexdigest()
        if f.name in done:
            if done[f.name] != digest:
                raise RuntimeError(f"migration {f.name} changed after it was applied; add a new migration instead")
            continue
        with conn.transaction():
            conn.execute(sql.decode("utf-8"))
            conn.execute("INSERT INTO fabric_schema_migrations (name, sha256) VALUES (%s, %s)", (f.name, digest))
        applied.append(f.name)
    return applied
