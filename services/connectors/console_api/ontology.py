"""The ontology the console shows: loaded by the one loader, so the UI shows what gate G1 enforces. Definitions only.

Loaded on every request (a few milliseconds), so an edited definition shows up without a restart. A load problem (a missing
pack, a reference pack where none is allowed) is reported as a 503 naming the problem, never as a partial ontology.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from console_api.errors import ConsoleError
from console_api.ids import utc_now_iso
from console_api.models import Graph, OntologyPin
from usep.core.errors import OntologyLoadError
from usep.ontology import load_ontology, resolve_pins
from usep.ontology.export import to_dto
from usep.ontology.graph import ontology_graphify
from usep.ontology.model import OntologyBundle

DEFAULT_DIR = Path(__file__).resolve().parents[3] / "ontology"


def load_bundle(settings: Any) -> OntologyBundle:
    root = Path(settings.ontology_dir) if settings.ontology_dir else DEFAULT_DIR
    try:
        pins = resolve_pins(root, list(settings.ontology_packs))
        return load_ontology(root, pins, allow_reference_only=settings.ontology_allow_reference_packs)
    except OntologyLoadError as exc:
        raise ConsoleError(503, "ontology_unavailable", f"The ontology cannot be loaded: {'; '.join(exc.problems[:3])}") from exc


def ontology_dto(settings: Any) -> dict[str, Any]:
    return to_dto(load_bundle(settings))


def ontology_graph(settings: Any) -> dict[str, Any]:
    return ontology_graphify(load_bundle(settings))


def conform(graph: Graph, bundle: OntologyBundle) -> tuple[Graph, OntologyPin]:
    """Keep only what the ontology allows, and stamp the graph and its pin with the ontology it was checked against.

    The graph builder proposes concepts and relationships from rules; the ontology decides. A node whose concept is unknown, or an
    edge whose relationship is unknown, whose ends are not in the graph, or whose end concepts the relationship does not allow
    (a subclass counts as its parent), is dropped and counted, never shown. Nothing is guessed or repaired.
    """
    version, digest = bundle.release.core_version, bundle.release.digest
    nodes = [n.model_copy(update={"ontology_version": version}) for n in graph.nodes if n.concept in bundle.concepts]
    concept_of = {n.id: n.concept for n in nodes}

    def allowed(edge: Any) -> bool:
        rel = bundle.relationships.get(edge.relation)
        if rel is None or edge.source not in concept_of or edge.target not in concept_of:
            return False
        return bool(set(bundle.ancestors(concept_of[edge.source])) & set(rel.from_types)) and bool(
            set(bundle.ancestors(concept_of[edge.target])) & set(rel.to_types))

    edges = [e for e in graph.edges if allowed(e)]
    pin = OntologyPin(
        version=version, digest=digest, packs=[f"{p.id}@{p.version}" for p in bundle.release.packs],
        reference_only=any(p.reference_only for p in bundle.release.packs), checked_at=utc_now_iso(),
        nodes_dropped=len(graph.nodes) - len(nodes), edges_dropped=len(graph.edges) - len(edges))
    return graph.model_copy(update={"nodes": nodes, "edges": edges, "ontology_version": version, "ontology_digest": digest}), pin


def apply_ontology(settings: Any, graph: Graph) -> tuple[Graph, OntologyPin]:
    return conform(graph, load_bundle(settings))
