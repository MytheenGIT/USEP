"""Write a KnowledgeGraph as Graphify's graph.json (ADR-19).

Writes JSON only; it does not import the `graphifyy` package. The field names were read from Graphify
0.9.119 output (`graph.schema_version` 1), not from a published schema, so tests/graph pins the ones used
here. The concept goes in `type` and every attribute in `metadata`, so nothing is lost on the way out.

`file_type` is "code" because that is the value verified to work with Graphify's explain, path, affected,
query and cluster-only commands. Other values were not tried.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from usep.graph.export_filter import restrict_for_export
from usep.graph.model import GraphEdge, GraphNode, KnowledgeGraph

GRAPHIFY_VERSION = "0.9.119"
SCHEMA_VERSION = 1


def _node(n: GraphNode) -> dict[str, Any]:
    extra = {k: v for k, v in {
        "tenant_id": n.tenant_id, "labels": list(n.labels) or None, "provenance": dict(n.provenance) or None,
        "versions": dict(n.versions) or None, "valid_from": n.valid_from, "valid_to": n.valid_to,
        "sensitivity": n.sensitivity, "acl_ref": n.acl_ref, "owners_only": n.owners_only, "confidence": n.confidence,
    }.items() if v is not None}
    return {
        "id": n.entity_id,
        "label": n.name,
        "norm_label": n.name.lower(),
        "file_type": "code",
        "type": n.concept,
        "source_file": f"usep://{n.source_system or 'unknown'}",
        "source_location": n.source_id or "",
        "metadata": {"concept": n.concept, **extra, **n.attributes},
    }


def _edge(e: GraphEdge) -> dict[str, Any]:
    extra = {k: v for k, v in {
        "tenant_id": e.tenant_id, "edge_id": e.edge_id, "source_system": e.source_system,
        "valid_from": e.valid_from, "valid_to": e.valid_to, "versions": dict(e.versions) or None,
    }.items() if v is not None}
    return {"metadata": extra,
        "source": e.source,
        "target": e.target,
        "relation": e.relation,
        "confidence": e.confidence,
        "confidence_score": e.confidence_score,
        "source_file": "usep://graph",
        "source_location": e.evidence_ref or "",
        "weight": 1.0,
    }


def to_graphify(graph: KnowledgeGraph) -> dict[str, Any]:
    """The graph as a node-link dict. Nodes and edges are sorted so the same graph gives the same bytes."""
    nodes = sorted((_node(n) for n in graph.nodes), key=lambda d: d["id"])
    links = sorted((_edge(e) for e in graph.edges), key=lambda d: (d["source"], d["relation"], d["target"]))
    return {
        "directed": True,
        "multigraph": False,
        "graph": {"schema_version": SCHEMA_VERSION, "graphify_version": GRAPHIFY_VERSION},
        "nodes": nodes,
        "links": links,
        "hyperedges": [],
    }


def write_graphify(graph: KnowledgeGraph, out_dir: str | Path) -> Path:
    """Write <out_dir>/graphify-out/graph.json (LF line endings) and return its path."""
    path = Path(out_dir) / "graphify-out" / "graph.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_graphify(graph), indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return path


def write_graphify_restricted(graph: KnowledgeGraph, out_dir: str | Path, *, max_sensitivity: int = 1) -> Path:
    """Filter first (owners-only and sensitive records never leave), then write. Use this for any real data (ADR-19)."""
    return write_graphify(restrict_for_export(graph, max_sensitivity=max_sensitivity).graph, out_dir)
