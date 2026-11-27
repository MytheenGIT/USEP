"""Drop what must not leave the system before a graph is exported (ADR-19, open point on ADR-06 and ADR-10).

Graphify's traversal knows nothing about access, so the filter runs first. Fail closed: a node is kept only if it is
labelled, not owners-only, and not above `max_sensitivity` (default 1, the same ceiling as the model-egress policy).
An edge is kept only if both of its nodes are kept, so no edge can reveal a dropped node's id.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from usep.graph.model import KnowledgeGraph


@dataclass(slots=True)
class FilterResult:
    graph: KnowledgeGraph
    nodes_dropped: int = 0
    edges_dropped: int = 0
    reasons: dict[str, int] = field(default_factory=dict)


def restrict_for_export(graph: KnowledgeGraph, *, max_sensitivity: int = 1) -> FilterResult:
    out = KnowledgeGraph()
    res = FilterResult(out)
    kept: set[str] = set()
    for n in graph.nodes:
        if n.owners_only is not False:
            why = "owners_only"                       # True, or never labelled (None)
        elif n.sensitivity is None or n.sensitivity > max_sensitivity:
            why = "sensitivity"
        else:
            out.add_node(n)
            kept.add(n.entity_id)
            continue
        res.nodes_dropped += 1
        res.reasons[why] = res.reasons.get(why, 0) + 1
    for e in graph.edges:
        if e.source in kept and e.target in kept:
            out.add_edge(e)
        else:
            res.edges_dropped += 1
    return res
