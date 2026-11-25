"""Graphify adapter (ADR-19). Writes JSON only; takes no dependency on the graphifyy package."""
from usep.graph.adapters.graphify.export import to_graphify, write_graphify

__all__ = ["to_graphify", "write_graphify"]
