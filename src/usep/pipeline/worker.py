"""C-02 acquisition worker: raw.<family> event in, entity.<domain> / quarantine events out.

Steps per snapshot (diagram B4 then C): parse and normalize, redact, classify (label), map to the ontology, gate G1,
write evidence, publish. Nothing is dropped: a record that cannot become a valid candidate is written to quarantine
with a reason code and where it was found (field names, never values) and announced on the `quarantine` topic.

Idempotency. The same raw event may arrive twice (at-least-once). Evidence and quarantine objects are keyed by the
snapshot checksum and written once, and every entity event carries an `idempotency_key` the fabric writer dedupes on.
Failures that are not the record's fault (store unreachable, bus rejects) raise PipelineError so the event is delivered
again; failures that are the record's fault are quarantined and the event is considered handled.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from usep.core.errors import PipelineError
from usep.core.ids import to_iso, utc_now_iso
from usep.ontology.gate import Candidate, Q_SCHEMA, Quarantine
from usep.ontology.model import OntologyBundle
from usep.pipeline.classify import ClassificationPolicy, classify
from usep.pipeline.links import extract as extract_links, refs_for_evidence
from usep.pipeline.mapping import to_candidate, validate_with_common
from usep.pipeline.normalize import Record, normalize
from usep.pipeline.redact import RedactionReport, redact_text, redact_value
from usep.pipeline.topics import QUARANTINE_TOPIC, entity_topic
from usep.ports.event_bus import Event, EventBus
from usep.ports.object_store import ObjectStore

Q_PARSE = "Q-PARSE"        # the snapshot is not the shape the parser expects (schema drift at the source)


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()


def _iso_utc(value: str, fallback: str) -> str:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return to_iso(dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))
    except (TypeError, ValueError):
        return fallback


@dataclass
class Outcome:
    entities: int = 0
    edges: int = 0
    links: int = 0
    evidence_only: int = 0
    quarantined: int = 0
    reasons: list[str] = field(default_factory=list)

    def add(self, other: "Outcome") -> None:
        self.entities += other.entities
        self.edges += other.edges
        self.links += other.links
        self.evidence_only += other.evidence_only
        self.quarantined += other.quarantined
        self.reasons += other.reasons


class AcquisitionWorker:
    def __init__(self, bus: EventBus, store: ObjectStore, ontology: Callable[[], OntologyBundle],
                 policy: ClassificationPolicy | None = None, evidence_prefix: str = "evidence",
                 quarantine_prefix: str = "quarantine", repo_hosts: tuple[str, ...] = (),
                 project_keys: tuple[str, ...] = ()) -> None:
        self._pkeys = tuple(project_keys)
        self._hosts = tuple(h.lower() for h in repo_hosts)
        self._bus, self._store, self._ontology = bus, store, ontology
        self._policy = policy or ClassificationPolicy()
        self._ev, self._q = evidence_prefix.strip("/"), quarantine_prefix.strip("/")

    # ------------------------------------------------------------------ entry
    def handle(self, event: Event) -> Outcome:
        p = event.payload
        source, ref, snapshot_ref, checksum = p["source"], p["source_ref"], p["snapshot_ref"], p["checksum"]
        bundle = self._ontology()                       # one bundle for the whole snapshot (finish under start version)
        raw = json.loads(self._store.get(snapshot_ref))
        out = Outcome()
        try:
            records = normalize(source, ref, raw)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            out.add(self._quarantine(event, bundle, source, ref, Quarantine(
                Q_PARSE, f"snapshot does not match the {source} parser: {type(exc).__name__}", (source,))))
            return out
        for rec in records:
            out.add(self._record(event, bundle, rec))
        return out

    # ------------------------------------------------------------------ one record
    def _record(self, event: Event, bundle: OntologyBundle, rec: Record) -> Outcome:
        p, out = event.payload, Outcome()
        # 1. redact before anything is stored or leaves for a model
        text, report = redact_text(rec.text)
        title, r = redact_text(rec.title)
        report.merge(r)
        scope, r = redact_value(rec.scope)
        report.merge(r)
        # 2. label
        labels = classify(rec.labels, rec.acl, report, self._policy)
        redacted = Record(rec.source_system, rec.source_object, rec.source_id, rec.source_version, rec.event_time,
                          title, text, rec.acl, rec.labels, scope, rec.links, link_fields=rec.link_fields,
                          parent_id=rec.parent_id)
        # 3. map and 4. gate
        mapped = to_candidate(bundle, rec.source_system, rec.source_object, redacted.mapping_payload())
        if not mapped.ok:
            return self._quarantine(event, bundle, rec.source_system, rec.source_id, mapped.quarantine)
        cand = mapped.candidate
        evidence_ref = self._write_evidence(p, redacted, labels, report)
        if cand.kind == "evidence":
            out.evidence_only = 1
            return out
        now, retrieved = utc_now_iso(), _iso_utc(p["retrieved_at"], utc_now_iso())
        attrs: dict[str, Any] = dict(cand.attributes)
        if cand.kind == "node":
            concept = bundle.concepts[cand.type]
            common = {
                "tenant_id": event.tenant_id, "domain": concept.domain, "sensitivity": labels.sensitivity,
                "source_system": rec.source_system, "source_id": rec.source_id, "source_version": rec.source_version or p["checksum"][:16],
                "valid_from": _iso_utc(rec.event_time, retrieved), "recorded_at": now,
                "acl_state": labels.acl_state, "name": title or rec.source_id,
            }
            if labels.acl_ref:
                common["acl_ref"] = labels.acl_ref
            gate = validate_with_common(bundle, cand, common)
            if not gate.ok:
                return self._quarantine(event, bundle, rec.source_system, rec.source_id, gate.quarantine)
            attrs = {**{k: v for k, v in gate.candidate.attributes.items() if k != "entity_id"}}
            domain, from_ref, to_ref = concept.domain, None, None
            out.entities = 1
        else:
            from_id, to_id = (rec.links[0]["from"], rec.links[0]["to"]) if rec.links else ("", "")
            attrs.update({"source_system": rec.source_system, "evidence_ref": evidence_ref})
            gate = validate_with_common(bundle, Candidate("edge", cand.type, attrs, cand.from_type, cand.to_type), {})
            if not gate.ok:
                return self._quarantine(event, bundle, rec.source_system, rec.source_id, gate.quarantine)
            if not from_id or not to_id:
                return self._quarantine(event, bundle, rec.source_system, rec.source_id,
                                        Quarantine(Q_SCHEMA, "edge has no endpoints", ("links",)))
            domain = bundle.concepts[cand.from_type].domain
            from_ref = {"type": cand.from_type, "source_system": rec.source_system, "source_id": from_id}
            to_ref = {"type": cand.to_type, "source_system": rec.source_system, "source_id": to_id}
            out.edges = 1
        payload = {
            "kind": cand.kind, "type": cand.type, "attributes": attrs, "evidence_ref": evidence_ref,
            "labels": {"sensitivity": labels.sensitivity, "acl_state": labels.acl_state,
                       "owners_only": labels.owners_only, "reasons": list(labels.reasons),
                       "redaction": report.as_dict()},
            "idempotency_key": hashlib.sha256(
                f"{event.tenant_id}|{rec.source_system}|{rec.source_id}|{cand.kind}|{cand.type}|{p['checksum']}".encode()
            ).hexdigest(),
            "ontology": bundle.release.digest, "snapshot_ref": p["snapshot_ref"],
        }
        if from_ref:
            payload["from"], payload["to"] = from_ref, to_ref
        self._publish(entity_topic(domain), rec.source_id, f"entity.{cand.kind}_candidate", event.tenant_id, payload,
                      {"idempotency_key": payload["idempotency_key"], "ontology_digest": bundle.release.digest})
        if cand.kind == "node":
            out.links += self._publish_links(event, bundle, rec, cand.type, domain, evidence_ref)
        return out

    def _publish_links(self, event: Event, bundle: OntologyBundle, rec: Record, concept: str, domain: str,
                       evidence_ref: str) -> int:
        """Rule-based cross-system edges (links.py). Published pending resolution: the target's type is not known here."""
        n = 0
        for ln in extract_links(bundle, rec, concept, self._hosts, self._pkeys):
            to = {**ln.to, "pending_resolution": True}
            if "type" not in to:
                to["type"] = None
            payload = {
                "kind": "edge", "type": ln.rel,
                "attributes": {"source_system": rec.source_system, "evidence_ref": evidence_ref,
                               "confidence": ln.confidence},
                "from": {"type": concept, "source_system": rec.source_system, "source_id": rec.source_id}, "to": to,
                "provenance": ln.provenance, "pending_resolution": True, "evidence_ref": evidence_ref,
                "labels": {}, "ontology": bundle.release.digest, "snapshot_ref": event.payload["snapshot_ref"],
                "idempotency_key": hashlib.sha256("|".join([
                    event.tenant_id, rec.source_system, rec.source_id, ln.rel, to.get("source_id") or to["repository_ref"],
                    event.payload["checksum"]]).encode()).hexdigest(),
            }
            self._publish(entity_topic(domain), rec.source_id, "entity.edge_candidate", event.tenant_id, payload,
                          {"idempotency_key": payload["idempotency_key"], "ontology_digest": bundle.release.digest})
            n += 1
        return n

    # ------------------------------------------------------------------ writes
    def _write_evidence(self, p: dict[str, Any], rec: Record, labels: Any, report: RedactionReport) -> str:
        """Normalized, redacted text with provenance, keyed by snapshot checksum. Evidence is by reference: the
        entity event carries the ref, never the text (HLD 4.1: every hit resolves to an entity or evidence)."""
        body = {"source_system": rec.source_system, "source_object": rec.source_object, "source_id": rec.source_id,
                "source_version": rec.source_version, "source_url": p["source_url"], "snapshot_ref": p["snapshot_ref"],
                "checksum": p["checksum"], "title": rec.title, "text": rec.text, "labels": rec.labels,
                "sensitivity": labels.sensitivity, "acl_state": labels.acl_state, "owners_only": labels.owners_only,
                "redaction": report.as_dict(), "refs": refs_for_evidence(rec, self._hosts, self._pkeys)}
        key = f"{self._ev}/{rec.source_system}/{_seg(rec.source_object)}/{_seg(rec.source_id)}/{p['checksum']}.json"
        return self._store.put_if_absent(key, _canonical(body))

    def _quarantine(self, event: Event, bundle: OntologyBundle, system: str, source_id: str, q: Quarantine) -> Outcome:
        p = event.payload
        body = {"reason_code": q.reason_code, "reason": q.reason, "location": list(q.location),
                "source_system": system, "source_ref": source_id, "snapshot_ref": p["snapshot_ref"],
                "checksum": p["checksum"], "ontology": bundle.release.digest, "quarantined_at": utc_now_iso()}
        key = f"{self._q}/{system}/{_seg(source_id)}/{p['checksum']}.json"
        self._store.put_if_absent(key, _canonical(body))
        self._publish(QUARANTINE_TOPIC, source_id, "record.quarantined", event.tenant_id,
                      {k: body[k] for k in ("reason_code", "reason", "location", "source_system", "source_ref",
                                            "snapshot_ref")},
                      {"ontology_digest": bundle.release.digest})
        return Outcome(quarantined=1, reasons=[q.reason_code])

    def _publish(self, topic: str, key: str, type: str, tenant: str, payload: dict[str, Any], headers: dict[str, str]) -> None:
        try:
            self._bus.publish(topic, key, type, tenant, payload, headers)
        except PipelineError:
            raise
        except Exception as exc:                                   # noqa: BLE001
            raise PipelineError(f"publish to {topic} failed: {exc}") from exc


def _seg(value: str) -> str:
    from urllib.parse import quote
    return quote(value, safe="")
