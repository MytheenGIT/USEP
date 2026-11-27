"""GraphProjectionService: labelled records and relationship claims -> a tenant-scoped KnowledgeGraph.

The graph is a rebuildable projection of claims (the fabric/PostgreSQL stays authoritative; nothing here
persists). Rules: one tenant per call; only status `labelled` records become nodes; every edge must name a
relationship in the active ontology, join nodes of the allowed concepts, stay in one tenant, and be unique.
Node and edge ids are deterministic (uuid5), so projecting the same input twice, or into an existing graph,
adds nothing. Errors are returned, never raised, so a bad edge does not hide a good one. `dry_run` only
labels the result as a preview; the function has no side effects either way.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from usep.graph.model import GraphEdge, GraphNode, KnowledgeGraph
from usep.labelling.model import LABELLED, LabelledRecord
from usep.ontology.view import OntologyView

_EDGE_NS = uuid.UUID("c2d4b1aa-5a5e-4f7a-9c61-7b1e0c3a9e22")


@dataclass(frozen=True, slots=True)
class RelationshipClaim:
    tenant_id: str
    source_entity_id: str
    target_entity_id: str
    relation: str
    evidence_ref: str | None = None
    source_system: str | None = None
    confidence: float = 1.0
    inferred: bool = False
    valid_from: str | None = None
    valid_to: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectionError:
    code: str          # unknown_relationship | endpoint_type | missing_node | cross_tenant | not_labelled | bad_confidence
    subject: str
    message: str


@dataclass(slots=True)
class ProjectionResult:
    graph: KnowledgeGraph
    nodes_added: int = 0
    nodes_updated: int = 0
    edges_added: int = 0
    edges_skipped_duplicate: int = 0
    errors: list[ProjectionError] = field(default_factory=list)
    dry_run: bool = True

    @property
    def ok(self) -> bool:
        return not self.errors


def edge_id(tenant_id: str, source: str, relation: str, target: str) -> str:
    return str(uuid.uuid5(_EDGE_NS, f"{tenant_id}|{source}|{relation}|{target}"))


class GraphProjectionService:
    def __init__(self, view: OntologyView) -> None:
        self.view = view

    def project(self, tenant_id: str, records: Iterable[LabelledRecord], claims: Iterable[RelationshipClaim] = (),
                existing: KnowledgeGraph | None = None, *, dry_run: bool = True) -> ProjectionResult:
        res = ProjectionResult(KnowledgeGraph(), dry_run=dry_run)
        nodes: dict[str, GraphNode] = {n.entity_id: n for n in (existing.nodes if existing else [])}
        edges: dict[str, GraphEdge] = {e.edge_id or edge_id(tenant_id, e.source, e.relation, e.target): e for e in (existing.edges if existing else [])}
        if existing and any(n.tenant_id not in (None, tenant_id) for n in existing.nodes):
            res.errors.append(ProjectionError("cross_tenant", tenant_id, "existing graph belongs to another tenant"))
            res.graph = existing
            return res
        for r in records:
            if r.tenant_id != tenant_id:
                res.errors.append(ProjectionError("cross_tenant", r.entity_id or r.source_id or "?", "record belongs to another tenant; not projected"))
                continue
            if r.processing_status != LABELLED or not r.entity_id or not r.concept:
                res.errors.append(ProjectionError("not_labelled", r.entity_id or r.source_id or "?", f"status {r.processing_status}: only labelled records become nodes"))
                continue
            node = self._node(r)
            if r.entity_id in nodes:
                res.nodes_updated += nodes[r.entity_id] != node
            else:
                res.nodes_added += 1
            nodes[r.entity_id] = node
        concept_of = {i: n.concept for i, n in nodes.items()}
        for c in claims:
            subject = f"{c.source_entity_id} -{c.relation}-> {c.target_entity_id}"
            if c.tenant_id != tenant_id:
                res.errors.append(ProjectionError("cross_tenant", subject, "relationship belongs to another tenant; not projected"))
                continue
            if c.source_entity_id not in nodes or c.target_entity_id not in nodes:
                missing = c.source_entity_id if c.source_entity_id not in nodes else c.target_entity_id
                res.errors.append(ProjectionError("missing_node", subject, f"no node {missing} in this tenant's graph"))
                continue
            if c.relation not in self.view.relationship_rules:
                res.errors.append(ProjectionError("unknown_relationship", subject,
                                                  f"{c.relation} is not in the active ontology (propose an ontology change; it is not invented)"))
                continue
            why = self.view.endpoint_ok(c.relation, concept_of[c.source_entity_id], concept_of[c.target_entity_id])
            if why:
                res.errors.append(ProjectionError("endpoint_type", subject, why))
                continue
            if not 0 <= c.confidence <= 1:
                res.errors.append(ProjectionError("bad_confidence", subject, "confidence must be between 0 and 1"))
                continue
            eid = edge_id(tenant_id, c.source_entity_id, c.relation, c.target_entity_id)
            if eid in edges:
                res.edges_skipped_duplicate += 1
                continue
            label = "INFERRED" if c.inferred else "EXTRACTED"
            edges[eid] = GraphEdge(c.source_entity_id, c.target_entity_id, c.relation, label, c.confidence, c.evidence_ref,
                                   tenant_id, eid, c.source_system, c.valid_from, c.valid_to, self._versions())
            res.edges_added += 1
        res.graph = KnowledgeGraph(sorted(nodes.values(), key=lambda n: n.entity_id), sorted(edges.values(), key=lambda e: (e.source, e.relation, e.target)))
        problems = res.graph.problems(set(self.view.bundle.concepts), set(self.view.relationship_rules))
        res.errors += [ProjectionError("graph_invalid", "", p) for p in problems]
        return res

    # ---- helpers -------------------------------------------------------------------------------------
    def _versions(self) -> dict:
        p = self.view.bundle.pins
        return {"ontology_version": p.core_version, "packs": {x.id: x.version for x in p.packs}, "digest": p.digest}

    def _node(self, r: LabelledRecord) -> GraphNode:
        labels = tuple(dict.fromkeys(l.value for l in r.custom_labels if l.value != r.concept))
        return GraphNode(
            entity_id=r.entity_id or "", concept=r.concept or "", name=r.name or "",
            attributes=dict(sorted(r.properties.items())), source_system=r.source_system, source_id=r.source_id,
            tenant_id=r.tenant_id, labels=labels,
            provenance={k: v for k, v in {"source_type": r.source_type, "source_uri": r.source_uri, "source_version": r.source_version,
                                          "evidence_ref": r.evidence_ref, "mapping_rule_id": r.mapping_rule_id, "recorded_at": r.recorded_at}.items() if v},
            versions={**self._versions(), "ontology_pack_id": r.ontology_pack_id, "ontology_pack_version": r.ontology_pack_version},
            valid_from=r.valid_from, valid_to=r.valid_to, sensitivity=r.sensitivity, acl_ref=r.acl_ref,
            owners_only=r.owners_only if r.owners_only is not None else r.acl_state in (None, "unknown", "stale"),
            confidence=r.confidence if r.confidence < 1 else None)
