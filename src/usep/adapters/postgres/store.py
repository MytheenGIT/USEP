"""PostgreSQL adapter for the fabric store port (ADR-21). psycopg 3, plain SQL. The only module that imports a driver.

`transaction(tenant_id)` opens one connection and one transaction, sets `app.tenant_id` for row-level security, and commits
when the block exits cleanly. Any exception rolls everything back, including the idempotency claim.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from usep.fabric.model import Assertion, EdgeRecord, EntityState
from usep.ports.fabric_store import OutboxRow, OutboxStatus


def _state(r: Mapping[str, Any]) -> EntityState:
    return EntityState(r["entity_id"], r["type"], r["domain"], r["attributes"], r["labels"], r["source_version"],
                       r["valid_from"], r["evidence_ref"], r["snapshot_ref"], r["ontology"], r["row_version"], r["retracted_at"])


def _edge(r: Mapping[str, Any]) -> EdgeRecord:
    return EdgeRecord(r["edge_id"], r["edge_key"], r["type"], r["domain"], r["from_ref"], r["to_ref"], r["from_entity_id"],
                      r["to_entity_id"], r["attributes"], r["labels"], r["evidence_ref"], r["snapshot_ref"], r["ontology"],
                      r["row_version"], r["retracted"])


class _Tx:
    def __init__(self, conn: Any, tenant_id: str) -> None:
        self._c, self._t = conn, tenant_id

    def _one(self, sql: str, args: tuple) -> Any:
        return self._c.execute(sql, args).fetchone()

    def claim(self, idempotency_key: str, outcome: str) -> bool:
        cur = self._c.execute("INSERT INTO fabric_applied (tenant_id, idempotency_key, outcome) VALUES (%s, %s, %s) "
                              "ON CONFLICT DO NOTHING", (self._t, idempotency_key, outcome))
        return cur.rowcount == 1

    def find_entity(self, source_system: str, source_id: str) -> uuid.UUID | None:
        r = self._one("SELECT entity_id FROM fabric_source_identity WHERE tenant_id=%s AND source_system=%s AND source_id=%s",
                      (self._t, source_system, source_id))
        return r["entity_id"] if r else None

    def entity_type(self, entity_id: uuid.UUID) -> str | None:
        r = self._one("SELECT type FROM fabric_entity WHERE tenant_id=%s AND entity_id=%s", (self._t, entity_id))
        return r["type"] if r else None

    def create_entity(self, entity_id: uuid.UUID, type: str, domain: str, source_system: str, source_id: str) -> None:
        self._c.execute("INSERT INTO fabric_entity (tenant_id, entity_id, type, domain) VALUES (%s,%s,%s,%s)",
                        (self._t, entity_id, type, domain))
        self._c.execute("INSERT INTO fabric_source_identity (tenant_id, source_system, source_id, entity_id) "
                        "VALUES (%s,%s,%s,%s)", (self._t, source_system, source_id, entity_id))

    def get_state(self, entity_id: uuid.UUID) -> EntityState | None:
        r = self._one("SELECT * FROM fabric_entity_state WHERE tenant_id=%s AND entity_id=%s", (self._t, entity_id))
        return _state(r) if r else None

    def put_state(self, s: EntityState) -> None:
        self._c.execute(
            "INSERT INTO fabric_entity_state (tenant_id, entity_id, type, domain, attributes, labels, sensitivity, "
            "source_version, valid_from, evidence_ref, snapshot_ref, ontology, row_version, retracted_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (tenant_id, entity_id) DO UPDATE SET type=EXCLUDED.type, domain=EXCLUDED.domain, "
            "attributes=EXCLUDED.attributes, labels=EXCLUDED.labels, sensitivity=EXCLUDED.sensitivity, "
            "source_version=EXCLUDED.source_version, valid_from=EXCLUDED.valid_from, evidence_ref=EXCLUDED.evidence_ref, "
            "snapshot_ref=EXCLUDED.snapshot_ref, ontology=EXCLUDED.ontology, row_version=EXCLUDED.row_version, "
            "retracted_at=EXCLUDED.retracted_at, updated_at=now()",
            (self._t, s.entity_id, s.type, s.domain, Jsonb(dict(s.attributes)), Jsonb(dict(s.labels)),
             int(s.labels.get("sensitivity") or 0), s.source_version, s.valid_from, s.evidence_ref, s.snapshot_ref,
             s.ontology, s.row_version, s.retracted_at))

    def add_assertion(self, a: Assertion) -> None:
        self._c.execute(
            "INSERT INTO fabric_assertion (tenant_id, assertion_id, subject_kind, subject_id, type, attributes, labels, "
            "evidence_ref, snapshot_ref, source_version, valid_from, ontology, idempotency_key, applied, reason) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (self._t, a.assertion_id, a.subject_kind, a.subject_id, a.type, Jsonb(dict(a.attributes)), Jsonb(dict(a.labels)),
             a.evidence_ref, a.snapshot_ref, a.source_version, a.valid_from, a.ontology, a.idempotency_key, a.applied, a.reason))

    def get_edge(self, edge_key: str) -> EdgeRecord | None:
        r = self._one("SELECT * FROM fabric_edge WHERE tenant_id=%s AND edge_key=%s", (self._t, edge_key))
        return _edge(r) if r else None

    def put_edge(self, e: EdgeRecord) -> None:
        self._c.execute(
            "INSERT INTO fabric_edge (tenant_id, edge_id, edge_key, type, domain, from_ref, to_ref, from_entity_id, "
            "to_entity_id, attributes, labels, evidence_ref, snapshot_ref, ontology, row_version, retracted) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (tenant_id, edge_key) DO UPDATE SET from_entity_id=EXCLUDED.from_entity_id, "
            "to_entity_id=EXCLUDED.to_entity_id, attributes=EXCLUDED.attributes, labels=EXCLUDED.labels, "
            "evidence_ref=EXCLUDED.evidence_ref, snapshot_ref=EXCLUDED.snapshot_ref, ontology=EXCLUDED.ontology, "
            "row_version=EXCLUDED.row_version, retracted=EXCLUDED.retracted, updated_at=now()",
            (self._t, e.edge_id, e.edge_key, e.type, e.domain, Jsonb(dict(e.from_ref)), Jsonb(dict(e.to_ref)),
             e.from_entity_id, e.to_entity_id, Jsonb(dict(e.attributes)), Jsonb(dict(e.labels)), e.evidence_ref,
             e.snapshot_ref, e.ontology, e.row_version, e.retracted))

    def link_pending(self, entity_id: uuid.UUID, type: str, source_system: str, source_id: str) -> list[EdgeRecord]:
        out: dict[uuid.UUID, EdgeRecord] = {}
        for end in ("from", "to"):
            rows = self._c.execute(
                f"UPDATE fabric_edge SET {end}_entity_id=%s, row_version=row_version+1, updated_at=now() "
                f"WHERE tenant_id=%s AND {end}_entity_id IS NULL AND NOT retracted AND {end}_ref->>'source_system'=%s "
                f"AND coalesce({end}_ref->>'source_id', {end}_ref->>'repository_ref')=%s "
                f"AND ({end}_ref->>'type' IS NULL OR {end}_ref->>'type'=%s) RETURNING *",
                (entity_id, self._t, source_system, source_id, type)).fetchall()
            for r in rows:
                out[r["edge_id"]] = _edge(r)
        return list(out.values())

    def retract(self, source_systems: tuple[str, ...], source_id: str, at: Any) -> tuple[list[EntityState], list[EdgeRecord]]:
        ids = [r["entity_id"] for r in self._c.execute(
            "SELECT entity_id FROM fabric_source_identity WHERE tenant_id=%s AND source_system = ANY(%s) AND source_id=%s",
            (self._t, list(source_systems), source_id)).fetchall()]
        states = [_state(r) for r in self._c.execute(
            "UPDATE fabric_entity_state SET retracted_at=%s, row_version=row_version+1, updated_at=now() "
            "WHERE tenant_id=%s AND entity_id = ANY(%s) AND retracted_at IS NULL RETURNING *", (at, self._t, ids)).fetchall()]
        edges = [_edge(r) for r in self._c.execute(
            "UPDATE fabric_edge SET retracted=true, row_version=row_version+1, updated_at=now() "
            "WHERE tenant_id=%s AND NOT retracted AND (from_entity_id = ANY(%s) OR to_entity_id = ANY(%s) "
            "OR (from_ref->>'source_system' = ANY(%s) AND coalesce(from_ref->>'source_id', from_ref->>'repository_ref')=%s) "
            "OR (to_ref->>'source_system' = ANY(%s) AND coalesce(to_ref->>'source_id', to_ref->>'repository_ref')=%s)) "
            "RETURNING *", (self._t, ids, ids, list(source_systems), source_id, list(source_systems), source_id)).fetchall()]
        return states, edges

    def reject(self, event_id: str, topic: str, code: str, reason: str) -> None:
        self._c.execute("INSERT INTO fabric_rejected (tenant_id, event_id, topic, code, reason) VALUES (%s,%s,%s,%s,%s) "
                        "ON CONFLICT DO NOTHING", (self._t, event_id, topic, code, reason[:500]))

    def enqueue(self, topic: str, key: str, type: str, payload: Mapping[str, Any]) -> int:
        return self._one("INSERT INTO fabric_outbox (tenant_id, topic, key, type, payload) VALUES (%s,%s,%s,%s,%s) "
                         "RETURNING outbox_id", (self._t, topic, key, type, Jsonb(dict(payload))))["outbox_id"]


class _Batch:
    def __init__(self, conn: Any, rows: list[OutboxRow], max_attempts: int) -> None:
        self._c, self.rows, self._max = conn, rows, max_attempts

    def mark_published(self, outbox_id: int) -> None:
        self._c.execute("UPDATE fabric_outbox SET published_at=now(), last_error=NULL WHERE outbox_id=%s", (outbox_id,))

    def mark_failed(self, outbox_id: int, error: str) -> None:
        self._c.execute("UPDATE fabric_outbox SET attempts=attempts+1, last_error=%s, "
                        "dead_at=CASE WHEN attempts+1 >= %s THEN now() END WHERE outbox_id=%s", (error, self._max, outbox_id))


class PostgresFabricStore:
    def __init__(self, connect: Callable[[], Any] | str) -> None:
        """`connect` is a DSN or a zero-argument callable returning a new psycopg connection."""
        if isinstance(connect, str):
            import psycopg
            dsn = connect
            connect = lambda: psycopg.connect(dsn, row_factory=dict_row)
        self._connect = connect

    @contextmanager
    def transaction(self, tenant_id: str) -> Iterator[_Tx]:
        if not tenant_id:
            raise ValueError("tenant_id is required")
        conn = self._connect()
        try:
            with conn.transaction():
                conn.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
                yield _Tx(conn, tenant_id)
        finally:
            conn.close()

    @contextmanager
    def claim_outbox(self, limit: int, max_attempts: int) -> Iterator[_Batch]:
        conn = self._connect()
        try:
            with conn.transaction():
                rows = [OutboxRow(r["outbox_id"], r["tenant_id"], r["topic"], r["key"], r["type"], r["payload"], r["attempts"])
                        for r in conn.execute(
                            "SELECT * FROM fabric_outbox WHERE published_at IS NULL AND dead_at IS NULL "
                            "ORDER BY outbox_id LIMIT %s FOR UPDATE SKIP LOCKED", (limit,)).fetchall()]
                yield _Batch(conn, rows, max_attempts)
        finally:
            conn.close()

    def outbox_status(self) -> OutboxStatus:
        conn = self._connect()
        try:
            r = conn.execute(
                "SELECT count(*) FILTER (WHERE published_at IS NULL AND dead_at IS NULL) AS pending, "
                "count(*) FILTER (WHERE dead_at IS NOT NULL) AS dead, "
                "extract(epoch FROM now() - min(created_at) FILTER (WHERE published_at IS NULL AND dead_at IS NULL)) AS age, "
                "coalesce(max(outbox_id), 0) AS last FROM fabric_outbox").fetchone()
            return OutboxStatus(int(r["pending"]), int(r["dead"]), float(r["age"]) if r["age"] is not None else None, int(r["last"]))
        finally:
            conn.close()
