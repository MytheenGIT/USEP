"""The ontology itself as a graph, for Graphify and the console (ADR-19).

This is the type level: nodes are concepts, edges are relationship types (and `is_a` for a pack concept's parent). It holds
definitions only, never tenant or source data, so nothing here is owners-only and it is safe to export unrestricted. It reuses
the vendor-neutral KnowledgeGraph and the Graphify adapter, so Graphify's explain, path, affected and query commands work
on the rulebook ("what can own a Service?", "path from Incident to Policy").
"""
from __future__ import annotations

from typing import Any

from usep.graph.adapters.graphify.export import to_graphify
from usep.graph.model import GraphEdge, GraphNode, KnowledgeGraph
from usep.ontology.model import OntologyBundle

IS_A = "is_a"      # a pack concept is a subclass of a core concept; not a relationship type, so listed apart


def ontology_graph(b: OntologyBundle) -> KnowledgeGraph:
    g = KnowledgeGraph()
    for cid, c in sorted(b.concepts.items()):
        g.add_node(GraphNode(
            entity_id=cid, concept=cid, name=cid, source_system="ontology", source_id=f"{c.pack_id}/{cid}",
            labels=tuple(x for x in (c.domain, c.level, c.pack_id) if x),
            attributes={"kind": "concept", "domain": c.domain, "level": c.level, "pack_id": c.pack_id, "parent": c.parent,
                        "description": c.description, "role_only": c.role_only,
                        "attribute_names": [a.name for a in b.attributes_of(cid)]},
            versions={"ontology_version": b.release.core_version}, sensitivity=0, owners_only=False))
    ref = f"ontology://{b.release.digest[:12]}"
    for rid, r in sorted(b.relationships.items()):
        for src in r.from_types:
            for dst in r.to_types:
                if src in b.concepts and dst in b.concepts:
                    g.add_edge(GraphEdge(src, dst, rid, evidence_ref=f"{ref}/relationships/{rid}",
                                         source_system="ontology", edge_id=f"{rid}:{src}:{dst}"))
    for cid, c in sorted(b.concepts.items()):
        if c.parent and c.parent in b.concepts:
            g.add_edge(GraphEdge(cid, c.parent, IS_A, evidence_ref=f"{ref}/concepts/{cid}", source_system="ontology",
                                 edge_id=f"{IS_A}:{cid}:{c.parent}"))
    return g


def ontology_graphify(b: OntologyBundle) -> dict[str, Any]:
    """Graphify graph.json for the ontology, stamped with the version and digest it was built from."""
    out = to_graphify(ontology_graph(b))
    out["graph"].update({"kind": "ontology-types", "ontology_version": b.release.core_version, "ontology_digest": b.release.digest,
                         "reference_only": any(p.reference_only for p in b.release.packs),
                         "packs": [f"{p.id}@{p.version}" for p in b.release.packs]})
    return out
