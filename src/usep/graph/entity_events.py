"""Pipeline `entity.<domain>` events -> labelled records and relationship claims for GraphProjectionService.

The acquisition pipeline (C-02) stops at candidates: nodes carry source keys, not entity ids, and cross-system edges are
published `pending_resolution` with no target type. This adapter is a stand-in for the entity resolver (step 6) for the
graph only. It does exactly one thing: it matches an edge end to a node by (source_system, source_id), and by concept
when the end names one. An end with no node, or with more than one matching node, is returned as unresolved, never
guessed. Entity ids are derived from the natural key (`derive_entity_id`), so projecting the same events twice adds nothing.
It is not the resolver: it never merges two source records into one entity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from usep.graph.projection import GraphProjectionService, ProjectionResult, RelationshipClaim
from usep.labelling.labeller import derive_entity_id
from usep.labelling.model import LABELLED, LabelledRecord
from usep.ontology.view import OntologyView

_COMMON = {"tenant_id", "domain", "sensitivity", "source_system", "source_id", "source_version", "valid_from",
           "recorded_at", "acl_state", "acl_ref", "name", "entity_id", "evidence_ref"}


@dataclass(frozen=True, slots=True)
class Unresolved:
    reason: str            # no_node | ambiguous | cross_tenant
    subject: str


@dataclass(slots=True)
class EventGraph:
    result: ProjectionResult
    unresolved: list[Unresolved] = field(default_factory=list)


def _get(event: Any, name: str) -> Any:
    return event.get(name) if isinstance(event, Mapping) else getattr(event, name)


def build_graph(view: OntologyView, tenant_id: str, events: Iterable[Any]) -> EventGraph:
    """Project node and edge candidates of one tenant. Events of other tenants are ignored, never projected.
    A retraction event removes the node it names (and so every edge that touched it) unless the node was recorded after it."""
    nodes: dict[str, LabelledRecord] = {}
    edge_events: list[Mapping[str, Any]] = []
    gone: list[tuple[tuple[str, ...], str, str]] = []                 # (source_systems, source_id, detected_at)
    for ev in events:
        if _get(ev, "tenant_id") != tenant_id:
            continue
        p = _get(ev, "payload")
        if not isinstance(p, Mapping):
            continue
        if p.get("kind") == "node":
            rec = _node(view, tenant_id, p)
            if rec.entity_id not in nodes or (rec.recorded_at or "") >= (nodes[rec.entity_id].recorded_at or ""):
                nodes[rec.entity_id] = rec                      # events are unordered: the newest record wins
        elif p.get("kind") == "edge":
            edge_events.append(p)
        elif "source_systems" in p and "detected_at" in p:           # a retraction: the object is gone at the source
            gone.append((tuple(p["source_systems"]), str(p["source_id"]), str(p["detected_at"])))
    for systems, sid, at in gone:                                    # a node recorded after the deletion came back: keep it
        for eid in [i for i, r in nodes.items() if r.source_system in systems and r.source_id == sid
                    and (r.recorded_at or "") <= at]:
            del nodes[eid]

    index: dict[tuple[str, str], list[LabelledRecord]] = {}
    for r in nodes.values():
        index.setdefault((r.source_system, r.source_id or ""), []).append(r)

    claims: list[RelationshipClaim] = []
    unresolved: list[Unresolved] = []
    for p in edge_events:
        a, b = p.get("from") or {}, p.get("to") or {}
        subject = f"{a.get('source_system')}:{a.get('source_id')} -{p.get('type')}-> {b.get('source_system')}:{b.get('source_id')}"
        ends = []
        for ref in (a, b):
            hits = [r for r in index.get((ref.get("source_system"), ref.get("source_id")), [])
                    if not ref.get("type") or r.concept == ref["type"]]
            if len(hits) != 1:
                unresolved.append(Unresolved("no_node" if not hits else "ambiguous", subject))
                break
            ends.append(hits[0].entity_id)
        else:
            attrs = p.get("attributes") or {}
            conf = float(attrs.get("confidence", 1.0))
            claims.append(RelationshipClaim(tenant_id, ends[0], ends[1], str(p.get("type")), p.get("evidence_ref"),
                                            attrs.get("source_system") or a.get("source_system"), conf, conf < 1.0))
    result = GraphProjectionService(view).project(tenant_id, nodes.values(), claims, dry_run=False)
    return EventGraph(result, unresolved)


def _node(view: OntologyView, tenant_id: str, p: Mapping[str, Any]) -> LabelledRecord:
    attrs = dict(p.get("attributes") or {})
    labels = p.get("labels") or {}
    concept, system, sid = str(p.get("type")), str(attrs.get("source_system")), str(attrs.get("source_id"))
    c = view.bundle.concepts.get(concept)
    return LabelledRecord(
        tenant_id=tenant_id, entity_id=derive_entity_id(tenant_id, concept, system, sid), concept=concept,
        ontology_level=getattr(c, "level", None), ontology_pack_id=None, ontology_pack_version=None,
        ontology_version=view.bundle.pins.core_version, domain=attrs.get("domain"), source_system=system,
        source_type=system, source_id=sid, source_version=attrs.get("source_version"), name=attrs.get("name"),
        properties={k: v for k, v in attrs.items() if k not in _COMMON}, sensitivity=labels.get("sensitivity"),
        acl_ref=attrs.get("acl_ref"), acl_state=labels.get("acl_state"), owners_only=labels.get("owners_only"),
        valid_from=attrs.get("valid_from"), recorded_at=attrs.get("recorded_at"), evidence_ref=p.get("evidence_ref"),
        processing_status=LABELLED)
