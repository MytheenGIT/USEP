"""In-memory FabricStore for tests. Same contract as the PostgreSQL adapter; the behaviour tests run against both."""
from __future__ import annotations

import copy
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from usep.fabric.model import Assertion, EdgeRecord, EntityState
from usep.ports.fabric_store import OutboxRow, OutboxStatus


class _Data:
    def __init__(self) -> None:
        self.entities: dict[tuple, tuple[str, str]] = {}
        self.identity: dict[tuple, Any] = {}
        self.state: dict[tuple, EntityState] = {}
        self.edges: dict[tuple, EdgeRecord] = {}
        self.assertions: list[tuple[str, Assertion]] = []
        self.applied: set[tuple] = set()
        self.rejected: dict[tuple, tuple] = {}
        self.outbox: list[dict] = []


def _end_matches(ref: Mapping[str, Any], systems: tuple[str, ...], sid: str) -> bool:
    return ref.get("source_system") in systems and (ref.get("source_id") or ref.get("repository_ref")) == sid


class _Tx:
    def __init__(self, d: _Data, t: str) -> None:
        self.d, self.t = d, t

    def claim(self, key: str, outcome: str) -> bool:
        if (self.t, key) in self.d.applied:
            return False
        self.d.applied.add((self.t, key))
        return True

    def find_entity(self, system: str, sid: str):
        return self.d.identity.get((self.t, system, sid))

    def entity_type(self, eid):
        e = self.d.entities.get((self.t, eid))
        return e[0] if e else None

    def create_entity(self, eid, type, domain, system, sid) -> None:
        self.d.entities[(self.t, eid)] = (type, domain)
        self.d.identity[(self.t, system, sid)] = eid

    def get_state(self, eid):
        return self.d.state.get((self.t, eid))

    def put_state(self, s: EntityState) -> None:
        self.d.state[(self.t, s.entity_id)] = s

    def add_assertion(self, a: Assertion) -> None:
        self.d.assertions.append((self.t, a))

    def get_edge(self, key: str):
        return next((e for (t, k), e in self.d.edges.items() if t == self.t and k == key), None)

    def put_edge(self, e: EdgeRecord) -> None:
        self.d.edges[(self.t, e.edge_key)] = e

    def link_pending(self, eid, type, system, sid) -> list[EdgeRecord]:
        out: dict = {}
        for (t, k), e in list(self.d.edges.items()):
            if t != self.t or e.retracted:
                continue
            for end in ("from", "to"):
                ref, cur = getattr(e, f"{end}_ref"), getattr(e, f"{end}_entity_id")
                if cur is None and _end_matches(ref, (system,), sid) and ref.get("type") in (None, type):
                    e = e.with_(**{f"{end}_entity_id": eid}, row_version=e.row_version + 1)
                    self.d.edges[(t, k)] = e
                    out[e.edge_id] = e
        return list(out.values())

    def retract(self, systems, sid, at):
        ids = {eid for (t, s, i), eid in self.d.identity.items() if t == self.t and s in systems and i == sid}
        states = []
        for (t, eid), st in list(self.d.state.items()):
            if t == self.t and eid in ids and st.retracted_at is None:
                st = st.with_(retracted_at=at, row_version=st.row_version + 1)
                self.d.state[(t, eid)] = st
                states.append(st)
        edges = []
        for (t, k), e in list(self.d.edges.items()):
            if t != self.t or e.retracted:
                continue
            if (e.from_entity_id in ids or e.to_entity_id in ids or _end_matches(e.from_ref, systems, sid)
                    or _end_matches(e.to_ref, systems, sid)):
                e = e.with_(retracted=True, row_version=e.row_version + 1)
                self.d.edges[(t, k)] = e
                edges.append(e)
        return states, edges

    def reject(self, event_id, topic, code, reason) -> None:
        self.d.rejected.setdefault((self.t, event_id), (topic, code, reason))

    def enqueue(self, topic, key, type, payload) -> int:
        oid = len(self.d.outbox) + 1
        self.d.outbox.append({"id": oid, "tenant": self.t, "topic": topic, "key": key, "type": type,
                              "payload": copy.deepcopy(dict(payload)), "published": False, "dead": False, "attempts": 0,
                              "created": datetime.now(UTC)})
        return oid


class _Batch:
    def __init__(self, rows: list[dict], d: _Data, max_attempts: int) -> None:
        self._d, self._max = d, max_attempts
        self.rows = [OutboxRow(r["id"], r["tenant"], r["topic"], r["key"], r["type"], r["payload"], r["attempts"]) for r in rows]

    def _row(self, oid: int) -> dict:
        return self._d.outbox[oid - 1]

    def mark_published(self, oid: int) -> None:
        self._row(oid)["published"] = True

    def mark_failed(self, oid: int, error: str) -> None:
        r = self._row(oid)
        r["attempts"] += 1
        r["dead"] = r["attempts"] >= self._max


class MemoryFabricStore:
    def __init__(self) -> None:
        self.d = _Data()

    @contextmanager
    def transaction(self, tenant_id: str) -> Iterator[_Tx]:
        if not tenant_id:
            raise ValueError("tenant_id is required")
        snapshot = copy.deepcopy(self.d)
        try:
            yield _Tx(self.d, tenant_id)
        except BaseException:
            self.d = snapshot                                  # roll back everything, including the idempotency claim
            raise

    @contextmanager
    def claim_outbox(self, limit: int, max_attempts: int) -> Iterator[_Batch]:
        rows = [r for r in self.d.outbox if not r["published"] and not r["dead"]][:limit]
        yield _Batch(rows, self.d, max_attempts)

    def outbox_status(self) -> OutboxStatus:
        pend = [r for r in self.d.outbox if not r["published"] and not r["dead"]]
        age = (datetime.now(UTC) - min(r["created"] for r in pend)).total_seconds() if pend else None
        return OutboxStatus(len(pend), sum(r["dead"] for r in self.d.outbox), age, len(self.d.outbox))

    # test helpers
    def states(self, tenant: str) -> list[EntityState]:
        return [s for (t, _), s in self.d.state.items() if t == tenant]
