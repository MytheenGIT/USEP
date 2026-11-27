"""The ontology as a Graphify graph: valid against the ontology, definitions only, deterministic."""
import json
from pathlib import Path

from usep.graph.adapters.graphify.export import write_graphify
from usep.ontology import load_ontology, resolve_pins
from usep.ontology.graph import IS_A, ontology_graph, ontology_graphify

ROOT = Path(__file__).resolve().parents[1] / "ontology"
PACKS = ["industry.banking-reference", "org.org-reference", "app.app-reference", "project.project-reference"]


def bundle():
    return load_ontology(ROOT, resolve_pins(ROOT, PACKS), allow_reference_only=True)


def test_graph_is_valid_against_the_ontology():
    b = bundle()
    assert ontology_graph(b).problems(set(b.concepts), set(b.relationships) | {IS_A}) == []


def test_every_concept_is_a_node_and_every_relationship_type_an_edge():
    b, g = bundle(), ontology_graph(bundle())
    assert {n.entity_id for n in g.nodes} == set(b.concepts)
    assert {e.relation for e in g.edges} - {IS_A} == set(b.relationships)
    assert any(e.relation == "owns" and e.source == "Team" and e.target == "Service" for e in g.edges)


def test_pack_concepts_are_subclasses():
    b, g = bundle(), ontology_graph(bundle())
    subs = {(e.source, e.target) for e in g.edges if e.relation == IS_A}
    assert subs == {(c.id, c.parent) for c in b.concepts.values() if c.parent}


def test_holds_definitions_only_and_is_never_restricted():
    d = ontology_graphify(bundle())
    assert "tenant_id" not in json.dumps(d)
    assert all(n["metadata"].get("owners_only") is False and n["metadata"].get("sensitivity") == 0 for n in d["nodes"])


def test_graphify_file_shape_and_stamp(tmp_path):
    b, d = bundle(), ontology_graphify(bundle())
    assert d["directed"] is True and d["graph"]["schema_version"] == 1
    assert d["graph"]["ontology_digest"] == b.release.digest and d["graph"]["reference_only"] is True
    assert {"id", "label", "type", "metadata"} <= set(d["nodes"][0]) and {"source", "target", "relation"} <= set(d["links"][0])
    p = write_graphify(ontology_graph(b), tmp_path)
    assert json.loads(p.read_text())["nodes"] == d["nodes"]


def test_same_ontology_gives_the_same_bytes():
    assert json.dumps(ontology_graphify(bundle()), sort_keys=True) == json.dumps(ontology_graphify(bundle()), sort_keys=True)
