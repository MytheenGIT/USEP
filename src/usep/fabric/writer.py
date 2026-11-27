"""Fabric writer (C-04): one bus event in, one atomic commit out. Rules only; storage is behind `FabricStore`.

Decisions are in docs/adr/ADR-21-fabric-writer-and-postgres-commit-point.md. In short: idempotent on the event's key,
newest `(valid_from, source_version)` wins for state, history is append-only, an identity is never re-typed, an edge whose
end is not known yet waits and is linked when the node commits, and everything that changed leaves through the outbox.
"""
from __future__ import annotations

from typing import Any

from usep.core.ids import uuid7
from usep.fabric.model import (
    COMMIT_EDGE_TOPIC,
    COMMIT_ENTITY_TOPIC,
    Applied,
    Assertion,
    EdgeCandidate,
    EdgeRecord,
    EntityState,
    NodeCandidate,
    RejectedEvent,
    Retraction,
    edge_key,
    parse_ts,
    ref_identity,
)
from usep.ports.event_bus import Event
from usep.ports.fabric_store import FabricStore, FabricTx

_RETRACTION_TOPIC = "retraction"


def parse_event(event: Event) -> NodeCandidate | EdgeCandidate | Retraction:
    """Turn a bus event into a candidate or raise `RejectedEvent`. Never reads outside the event."""
    p = event.payload
    try:
        if event.topic == _RETRACTION_TOPIC:
            return Retraction(event.tenant_id, tuple(p["source_systems"]), str(p["source_id"]), str(p.get("scope", "")),
                              str(p.get("reason", "")), parse_ts(p["detected_at"]), str(p["idempotency_key"]))
        if not event.topic.startswith("entity."):
            raise RejectedEvent("unknown_topic", f"the writer does not read {event.topic}")
        domain, kind = event.topic.split(".", 1)[1], p["kind"]
        common: dict[str, Any] = dict(
            tenant_id=event.tenant_id, domain=domain, type=str(p["type"]), attributes=dict(p.get("attributes") or {}),
            labels=dict(p.get("labels") or {}), evidence_ref=str(p.get("evidence_ref") or ""),
            snapshot_ref=str(p.get("snapshot_ref") or ""), ontology=str(p.get("ontology") or ""),
            idempotency_key=str(p["idempotency_key"]))
        if kind == "node":
            a = common["attributes"]
            if not a.get("source_system") or not a.get("source_id"):
                raise RejectedEvent("no_identity", "node has no source_system or source_id")
            return NodeCandidate(source_system=str(a["source_system"]), source_id=str(a["source_id"]),
                                 source_version=str(a.get("source_version") or ""),
                                 valid_from=parse_ts(a.get("valid_from")), **common)
        if kind == "edge":
            return EdgeCandidate(from_ref=dict(p["from"]), to_ref=dict(p["to"]), **common)
        raise RejectedEvent("unknown_kind", f"kind {kind!r} is not node or edge")
    except RejectedEvent:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise RejectedEvent("malformed", f"missing or invalid field: {exc}") from exc


def _version_key(v: str) -> tuple[int, int | str]:
    return (0, int(v)) if v.isdigit() else (1, v)


def _newer(cand: NodeCandidate, cur: EntityState) -> bool:
    """Evidence-contract rule: newest event time, then highest source version. Equal means nothing changed."""
    if cand.valid_from != cur.valid_from:
        return cand.valid_from > cur.valid_from
    return _version_key(cand.source_version) > _version_key(cur.source_version)


class FabricWriter:
    def __init__(self, store: FabricStore) -> None:
        self._store = store

    def handle(self, event: Event) -> Applied:
        """Commit one event. Bad input is parked in `fabric_rejected` and reported as `rejected`; a storage error raises,
        so the event is delivered again."""
        try:
            cand = parse_event(event)
        except RejectedEvent as exc:
            return self._park(event, exc)
        try:
            with self._store.transaction(event.tenant_id) as tx:
                if isinstance(cand, NodeCandidate):
                    return self._node(tx, cand)
                if isinstance(cand, EdgeCandidate):
                    return self._edge(tx, cand)
                return self._retract(tx, cand)
        except _Conflict as exc:                     # the transaction rolled back; record the refusal on its own
            return self._park(event, RejectedEvent(exc.code, exc.reason))

    # ------------------------------------------------------------------ node
    def _node(self, tx: FabricTx, c: NodeCandidate) -> Applied:
        if not tx.claim(c.idempotency_key, "node"):
            return Applied("duplicate")
        eid = tx.find_entity(c.source_system, c.source_id)
        if eid is None:
            eid = uuid7()
            tx.create_entity(eid, c.type, c.domain, c.source_system, c.source_id)
        elif (t := tx.entity_type(eid)) != c.type:
            raise _Conflict("type_conflict", f"{c.source_system}:{c.source_id} is a {t}, the event says {c.type}")
        cur = tx.get_state(eid)
        applies = cur is None or (_revives(c, cur) if cur.retracted else _newer(c, cur))
        if not applies:
            self._assert(tx, "node", eid, c, applied=False, reason="stale")
            return Applied("stale", entity_id=eid)
        labels = dict(c.labels)
        if cur is not None:                                          # sensitivity only ever goes up (evidence contract)
            labels["sensitivity"] = max(int(labels.get("sensitivity") or 0), int(cur.labels.get("sensitivity") or 0))
        state = EntityState(eid, c.type, c.domain, c.attributes, labels, c.source_version, c.valid_from, c.evidence_ref,
                            c.snapshot_ref, c.ontology, (cur.row_version + 1) if cur else 1)
        tx.put_state(state)
        self._assert(tx, "node", eid, c, applied=True)
        n = self._emit_entity(tx, state, "committed")
        for edge in tx.link_pending(eid, c.type, c.source_system, c.source_id):
            n += self._emit_edge(tx, edge, "committed")
        return Applied("committed", entity_id=eid, outbox=n)

    # ------------------------------------------------------------------ edge
    def _edge(self, tx: FabricTx, c: EdgeCandidate) -> Applied:
        if not tx.claim(c.idempotency_key, "edge"):
            return Applied("duplicate")
        ends: list[Any] = []
        for ref in (c.from_ref, c.to_ref):
            eid = tx.find_entity(str(ref.get("source_system") or ""), str(ref.get("source_id") or ref.get("repository_ref") or ""))
            if eid is not None and ref.get("type") and tx.entity_type(eid) != ref["type"]:
                raise _Conflict("type_conflict", f"edge end {ref_identity(ref)} is not a {ref['type']}")
            ends.append(eid)
        key = edge_key(c.tenant_id, c.type, c.from_ref, c.to_ref)
        cur = tx.get_edge(key)
        rec = EdgeRecord(cur.edge_id if cur else uuid7(), key, c.type, c.domain, c.from_ref, c.to_ref, ends[0], ends[1],
                         c.attributes, c.labels, c.evidence_ref, c.snapshot_ref, c.ontology, (cur.row_version + 1) if cur else 1)
        tx.put_edge(rec)
        tx.add_assertion(Assertion(uuid7(), "edge", rec.edge_id, c.type, c.attributes, c.labels, c.evidence_ref,
                                   c.snapshot_ref, "", None, c.ontology, c.idempotency_key, True))
        n = self._emit_edge(tx, rec, "committed")
        return Applied("committed" if not rec.pending else "pending", edge_id=rec.edge_id, outbox=n)

    # ------------------------------------------------------------------ retraction
    def _retract(self, tx: FabricTx, c: Retraction) -> Applied:
        if not tx.claim(c.idempotency_key, "retraction"):
            return Applied("duplicate")
        states, edges = tx.retract(c.source_systems, c.source_id, c.detected_at)
        tx.add_assertion(Assertion(uuid7(), "retraction", None, "retraction", {"source_id": c.source_id, "scope": c.scope},
                                   {}, "", "", "", c.detected_at, "", c.idempotency_key, True, c.reason))
        n = sum(self._emit_entity(tx, s, "retracted") for s in states) + sum(self._emit_edge(tx, e, "retracted") for e in edges)
        return Applied("retracted", outbox=n, extra={"entities": len(states), "edges": len(edges)})

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _assert(tx: FabricTx, kind: str, subject: Any, c: NodeCandidate, applied: bool, reason: str = "") -> None:
        tx.add_assertion(Assertion(uuid7(), kind, subject, c.type, c.attributes, c.labels, c.evidence_ref, c.snapshot_ref,
                                   c.source_version, c.valid_from, c.ontology, c.idempotency_key, applied, reason))

    @staticmethod
    def _emit_entity(tx: FabricTx, s: EntityState, change: str) -> int:
        tx.enqueue(COMMIT_ENTITY_TOPIC, str(s.entity_id), f"entity.{change}",
                         {"entity_id": str(s.entity_id), "type": s.type, "domain": s.domain, "row_version": s.row_version,
                          "change": change, "attributes": dict(s.attributes), "labels": dict(s.labels),
                          "evidence_ref": s.evidence_ref, "ontology": s.ontology, "source_version": s.source_version,
                          "valid_from": s.valid_from.isoformat()})
        return 1

    @staticmethod
    def _emit_edge(tx: FabricTx, e: EdgeRecord, change: str) -> int:
        tx.enqueue(COMMIT_EDGE_TOPIC, str(e.edge_id), f"edge.{change}",
                         {"edge_id": str(e.edge_id), "type": e.type, "domain": e.domain, "row_version": e.row_version,
                          "change": change, "from_entity_id": str(e.from_entity_id) if e.from_entity_id else None,
                          "to_entity_id": str(e.to_entity_id) if e.to_entity_id else None, "from_ref": dict(e.from_ref),
                          "to_ref": dict(e.to_ref), "pending": e.pending, "attributes": dict(e.attributes),
                          "labels": dict(e.labels), "evidence_ref": e.evidence_ref, "ontology": e.ontology})
        return 1

    def _park(self, event: Event, exc: RejectedEvent) -> Applied:
        with self._store.transaction(event.tenant_id) as tx:
            tx.reject(event.event_id, event.topic, exc.code, exc.reason)
        return Applied("rejected", detail=exc.code)


def _revives(c: NodeCandidate, cur: EntityState) -> bool:
    """After a retraction only something observed later than it can bring the entity back."""
    return cur.retracted_at is not None and c.valid_from > cur.retracted_at


class _Conflict(Exception):
    """Raised inside a transaction to roll it back and park the event."""

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason
