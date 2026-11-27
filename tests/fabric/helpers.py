from __future__ import annotations

from usep.core.ids import utc_now_iso, uuid7
from usep.ports.event_bus import Event

T = "tenant-a"


def ev(topic: str, payload: dict, tenant: str = T) -> Event:
    return Event(str(uuid7()), topic, "k", tenant, "x", 1, utc_now_iso(), payload)


def node(sid="ABC-1", system="jira", type="Issue", valid_from="2026-01-01T00:00:00Z", version="1", sens=1, key=None,
         tenant=T, name="n", acl_state="known"):
    return ev("entity.engineering", {
        "kind": "node", "type": type, "evidence_ref": f"s3://b/evidence/{sid}.json", "snapshot_ref": "s3://b/raw/x",
        "ontology": "d1", "idempotency_key": key or f"{system}|{sid}|{valid_from}|{version}|{sens}|{type}",
        "attributes": {"source_system": system, "source_id": sid, "source_version": version, "valid_from": valid_from,
                       "name": name},
        "labels": {"sensitivity": sens, "acl_state": acl_state, "owners_only": False, "acl": {"known": True}},
    }, tenant)


def edge(frm, to, rel="references", key=None, tenant=T):
    return ev("entity.engineering", {
        "kind": "edge", "type": rel, "evidence_ref": "s3://b/evidence/e.json", "snapshot_ref": "s3://b/raw/e",
        "ontology": "d1", "idempotency_key": key or f"edge|{rel}|{frm}|{to}", "attributes": {"confidence": 0.9},
        "from": frm, "to": to, "labels": {}}, tenant)


def ref(sid, system="jira", type=None):
    r = {"source_system": system, "source_id": sid}
    if type:
        r["type"] = type
    return r


def retraction(sid="ABC-1", systems=("jira",), at="2026-02-01T00:00:00Z", key=None, tenant=T):
    return ev("retraction", {"source_family": "jira", "source_systems": list(systems), "source_id": sid, "scope": "",
                             "reason": "deleted", "detected_at": at, "idempotency_key": key or f"r|{sid}|{at}"}, tenant)
