"""Graph model checks and the Graphify export (ADR-19)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from usep.graph import GraphEdge, GraphNode, KnowledgeGraph
from usep.graph.adapters.graphify import to_graphify, write_graphify

CORE = Path(__file__).resolve().parents[2] / "ontology" / "core"
CONCEPTS = {c["id"] for c in yaml.safe_load((CORE / "concepts.yml").read_text(encoding="utf-8"))["concepts"]}
RELATIONSHIPS = {r["id"] for r in yaml.safe_load((CORE / "relationships.yml").read_text(encoding="utf-8"))["relationships"]}


def sample() -> KnowledgeGraph:
    g = KnowledgeGraph()
    g.add_node(GraphNode("team-1", "Team", "payments-team"))
    g.add_node(GraphNode("svc-1", "Service", "checkout-service", {"criticality": "tier_1"}, "git", "owner/checkout"))
    g.add_node(GraphNode("api-1", "API", "orders-api"))
    g.add_node(GraphNode("inc-1", "Incident", "INC-101", {"severity": "sev2"}))
    g.add_edge(GraphEdge("team-1", "svc-1", "owns", evidence_ref="CODEOWNERS"))
    g.add_edge(GraphEdge("svc-1", "api-1", "exposes"))
    g.add_edge(GraphEdge("inc-1", "svc-1", "caused_by", "INFERRED", 0.6))
    return g


def test_valid_graph_has_no_problems():
    assert sample().problems(CONCEPTS, RELATIONSHIPS) == []


def test_unknown_concept_is_reported():
    g = sample()
    g.add_node(GraphNode("x", "Widget", "w"))
    assert any("unknown concept Widget" in p for p in g.problems(CONCEPTS, RELATIONSHIPS))


def test_unknown_relationship_is_reported():
    g = sample()
    g.add_edge(GraphEdge("svc-1", "api-1", "likes"))
    assert any("unknown relationship likes" in p for p in g.problems(CONCEPTS, RELATIONSHIPS))


def test_dangling_edge_and_duplicate_id_are_reported():
    g = sample()
    g.add_edge(GraphEdge("svc-1", "ghost", "depends_on"))
    g.add_node(GraphNode("svc-1", "Service", "again"))
    found = g.problems(CONCEPTS, RELATIONSHIPS)
    assert any("no node ghost" in p for p in found)
    assert any("duplicate entity_id: svc-1" in p for p in found)


def test_bad_confidence_is_reported():
    g = sample()
    g.add_edge(GraphEdge("svc-1", "api-1", "depends_on", "SURE", 1.5))
    found = g.problems(CONCEPTS, RELATIONSHIPS)
    assert any("confidence must be one of" in p for p in found)
    assert any("between 0 and 1" in p for p in found)


def test_export_keeps_the_fields_graphify_reads():
    data = to_graphify(sample())
    assert data["directed"] is True and data["graph"]["schema_version"] == 1
    node = next(n for n in data["nodes"] if n["id"] == "svc-1")
    assert node["label"] == "checkout-service" and node["type"] == "Service"
    assert node["metadata"] == {"concept": "Service", "criticality": "tier_1"}
    assert node["source_file"] == "usep://git" and node["source_location"] == "owner/checkout"
    edge = next(e for e in data["links"] if e["relation"] == "caused_by")
    assert (edge["source"], edge["target"], edge["confidence"], edge["confidence_score"]) == ("inc-1", "svc-1", "INFERRED", 0.6)


def test_export_is_deterministic_and_lf(tmp_path):
    first = write_graphify(sample(), tmp_path / "a")
    reversed_graph = KnowledgeGraph(list(reversed(sample().nodes)), list(reversed(sample().edges)))
    second = write_graphify(reversed_graph, tmp_path / "b")
    assert first.read_bytes() == second.read_bytes()
    assert b"\r" not in first.read_bytes()
    json.loads(first.read_text(encoding="utf-8"))


@pytest.mark.skipif(shutil.which("graphify") is None, reason="graphify CLI not installed (ADR-19 is not accepted)")
def test_real_graphify_reads_the_export(tmp_path):
    """Contract test: the pinned fields are enough for Graphify's own commands."""
    path = write_graphify(sample(), tmp_path)
    run = lambda *a: subprocess.run(["graphify", *a, "--graph", str(path)], capture_output=True, text=True)
    path_out = run("path", "payments-team", "orders-api")
    assert path_out.returncode == 0 and "owns" in path_out.stdout and "exposes" in path_out.stdout
    explain = run("explain", "checkout-service")
    assert explain.returncode == 0 and "INFERRED" in explain.stdout
