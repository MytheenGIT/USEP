"""Pipeline entity events -> graph -> restricted export (ADR-19)."""
import json
from pathlib import Path

import pytest

from tests.fake_s3 import FakeS3
from tests.pipeline.helpers import BUCKET, ONT, PINS, TENANT, jira, published, raw_event
from usep.adapters.s3.event_bus import S3EventBus
from usep.adapters.s3.snapshot_store import S3SnapshotStore
from usep.graph import GraphNode, KnowledgeGraph
from usep.graph.adapters.graphify import write_graphify_restricted
from usep.graph.entity_events import build_graph
from usep.graph.export_filter import restrict_for_export
from usep.ontology.bundle import OntologyBundle
from usep.ontology.view import OntologyView
from usep.ontology import load_ontology
from usep.pipeline.topics import register_schemas
from usep.pipeline.worker import AcquisitionWorker
from usep.ports.event_bus import SchemaRegistry

BUNDLE = load_ontology(ONT, PINS, allow_reference_only=True)
VIEW = OntologyView(OntologyBundle.load(ONT, [p.replace("@0.1.0", "") for p in PINS], allow_reference=True), ONT)


def run(*issues):
    s3 = FakeS3()
    reg = SchemaRegistry()
    register_schemas(reg, BUNDLE.domains)
    w = AcquisitionWorker(S3EventBus(s3, BUCKET, reg, partitions=4), S3SnapshotStore(s3, BUCKET), lambda: BUNDLE)
    for key, raw in issues:
        w.handle(raw_event(s3, "jira", key, raw))
    return [e for d in BUNDLE.domains for e in published(s3, f"entity.{d}")]


def test_nodes_and_resolved_edge_reach_the_graph_and_unresolved_ends_are_reported():
    events = run(("ABC-1", jira("ABC-1", "Story", "Open", desc="builds on ABC-2 and ABC-99")),
                 ("ABC-2", jira("ABC-2", "Task", "In Review")))
    eg = build_graph(VIEW, TENANT, events)
    g = eg.result.graph
    assert {(n.concept, n.source_id) for n in g.nodes} == {("Requirement", "ABC-1"), ("Change", "ABC-2")}
    assert [(e.relation, e.confidence) for e in g.edges] == [("references", "INFERRED")]
    assert [u.reason for u in eg.unresolved] == ["no_node"]              # ABC-99 was never ingested
    assert eg.result.ok


def test_same_events_twice_add_nothing_and_other_tenants_are_ignored():
    events = run(("ABC-2", jira("ABC-2", "Task", "In Review")))
    again = build_graph(VIEW, TENANT, events + events).result.graph
    assert len(again.nodes) == 1
    assert build_graph(VIEW, "00000000-0000-7000-8000-000000000009", events).result.graph.nodes == []


def test_default_labelling_is_owners_only_so_restricted_export_drops_everything():
    events = run(("ABC-2", jira("ABC-2", "Task", "In Review")))
    g = build_graph(VIEW, TENANT, events).result.graph
    assert all(n.owners_only for n in g.nodes)                           # ACL unknown: fail closed
    res = restrict_for_export(g)
    assert res.graph.nodes == [] and res.reasons == {"owners_only": 1}


def test_restrict_keeps_open_low_sensitivity_nodes_and_drops_edges_to_dropped_nodes(tmp_path):
    g = KnowledgeGraph()
    g.add_node(GraphNode("a", "Team", "a", sensitivity=1, owners_only=False))
    g.add_node(GraphNode("b", "Service", "b", sensitivity=1, owners_only=False))
    g.add_node(GraphNode("c", "Service", "c", sensitivity=2, owners_only=False))
    g.add_node(GraphNode("d", "Service", "d"))                           # never labelled
    from usep.graph import GraphEdge
    g.add_edge(GraphEdge("a", "b", "owns"))
    g.add_edge(GraphEdge("a", "c", "owns"))
    res = restrict_for_export(g)
    assert [n.entity_id for n in res.graph.nodes] == ["a", "b"] and res.edges_dropped == 1
    assert res.reasons == {"sensitivity": 1, "owners_only": 1}
    out = json.loads(write_graphify_restricted(g, tmp_path).read_text())
    assert {n["id"] for n in out["nodes"]} == {"a", "b"} and len(out["links"]) == 1


def retraction(system, sid, at):
    return {"tenant_id": TENANT, "payload": {"source_family": system, "source_systems": [system], "source_id": sid,
                                             "scope": "ABC", "reason": "not_found_in_scope", "detected_at": at,
                                             "idempotency_key": "k"}}


def test_a_retraction_removes_the_node_and_its_edges_unless_the_object_came_back():
    events = run(("ABC-1", jira("ABC-1", "Story", "Open", desc="builds on ABC-2")),
                 ("ABC-2", jira("ABC-2", "Task", "In Review")))
    assert len(build_graph(VIEW, TENANT, events).result.graph.edges) == 1
    gone = build_graph(VIEW, TENANT, events + [retraction("jira", "ABC-2", "9999-01-01T00:00:00.000Z")])
    assert {n.source_id for n in gone.result.graph.nodes} == {"ABC-1"} and gone.result.graph.edges == []
    back = build_graph(VIEW, TENANT, events + [retraction("jira", "ABC-2", "2000-01-01T00:00:00.000Z")])
    assert {n.source_id for n in back.result.graph.nodes} == {"ABC-1", "ABC-2"}      # recorded after the deletion: kept
