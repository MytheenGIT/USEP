"""Knowledge graph of ontology entities (ADR-19). The model is vendor-neutral; vendors live in adapters/."""
from usep.graph.model import CONFIDENCE_LABELS, GraphEdge, GraphNode, KnowledgeGraph

__all__ = ["CONFIDENCE_LABELS", "GraphEdge", "GraphNode", "KnowledgeGraph"]
