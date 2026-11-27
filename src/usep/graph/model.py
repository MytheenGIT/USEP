"""A vendor-neutral knowledge graph of ontology entities (ADR-19).

Nodes are instances of core or pack concepts; edges are instances of relationship types. This module
imports no vendor SDK. It does not decide what data becomes a node: that is the labelling step, which is
not defined yet. It only holds a graph and checks it against the concept and relationship names the
ontology allows.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Collection, Mapping

CONFIDENCE_LABELS = ("EXTRACTED", "INFERRED", "AMBIGUOUS")


@dataclass(frozen=True, slots=True)
class GraphNode:
    entity_id: str
    concept: str                      # a core or pack concept id, e.g. "Service"
    name: str
    attributes: Mapping[str, Any] = field(default_factory=dict)
    source_system: str | None = None
    source_id: str | None = None
    # Added for labelled projection (all optional so earlier callers keep working).
    tenant_id: str | None = None
    labels: tuple[str, ...] = ()              # domain / organisation / application / custom labels
    provenance: Mapping[str, Any] = field(default_factory=dict)   # source_uri, source_version, mapping rule, evidence
    versions: Mapping[str, Any] = field(default_factory=dict)     # ontology_version, ontology_pack_id/version
    valid_from: str | None = None
    valid_to: str | None = None
    sensitivity: int | None = None
    acl_ref: str | None = None
    owners_only: bool | None = None           # None means not labelled; the export filter treats that as restricted
    confidence: float | None = None           # set only for inferred labels


@dataclass(frozen=True, slots=True)
class GraphEdge:
    source: str                       # entity_id of the start node
    target: str                       # entity_id of the end node
    relation: str                     # a relationship type id, e.g. "owns"
    confidence: str = "EXTRACTED"
    confidence_score: float = 1.0
    evidence_ref: str | None = None
    tenant_id: str | None = None
    edge_id: str | None = None
    source_system: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    versions: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class KnowledgeGraph:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)

    def add_node(self, node: GraphNode) -> None:
        self.nodes.append(node)

    def add_edge(self, edge: GraphEdge) -> None:
        self.edges.append(edge)

    def problems(self, concepts: Collection[str], relationships: Collection[str]) -> list[str]:
        """Everything wrong with the graph, as readable lines. Empty means it is valid."""
        found: list[str] = []
        ids: set[str] = set()
        tenants: set[str | None] = set()
        for n in self.nodes:
            if n.entity_id in ids:
                found.append(f"duplicate entity_id: {n.entity_id}")
            ids.add(n.entity_id)
            tenants.add(n.tenant_id)
            if n.concept not in concepts:
                found.append(f"node {n.entity_id}: unknown concept {n.concept}")
            if not n.name:
                found.append(f"node {n.entity_id}: name is empty")
        for e in self.edges:
            if e.tenant_id is not None and tenants - {None} and e.tenant_id not in tenants:
                found.append(f"edge {e.source} -{e.relation}-> {e.target}: tenant {e.tenant_id} has no nodes in this graph")
            where = f"edge {e.source} -{e.relation}-> {e.target}"
            if e.relation not in relationships:
                found.append(f"{where}: unknown relationship {e.relation}")
            for end in (e.source, e.target):
                if end not in ids:
                    found.append(f"{where}: no node {end}")
            if e.confidence not in CONFIDENCE_LABELS:
                found.append(f"{where}: confidence must be one of {', '.join(CONFIDENCE_LABELS)}")
            if not 0 <= e.confidence_score <= 1:
                found.append(f"{where}: confidence_score must be between 0 and 1")
        if len({t for t in tenants if t}) > 1:
            found.append("graph mixes tenants: " + ", ".join(sorted(t for t in tenants if t)))
        return found
