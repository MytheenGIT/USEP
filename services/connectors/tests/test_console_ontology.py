"""The console's ontology endpoints: auth, tenant scoping, what the loader enforces, the Graphify graph, fail-closed loading."""
from __future__ import annotations

import pytest

from tests.test_console_api import JIRA, _auth, _make_client, _wait_done  # shared fixtures: fake connectors, signed-in admin


@pytest.fixture
def client(tmp_path, monkeypatch):
    with _make_client(tmp_path, monkeypatch) as c:
        yield c


def _config(client, headers) -> str:
    r = client.post("/api/configurations", headers=headers, json={"name": "Payments", "connectors": {"jira": JIRA}})
    assert r.status_code == 201
    _wait_done(client, headers, r.json()["id"])
    return r.json()["id"]


def test_both_endpoints_need_a_session(client):
    h = _auth(client)
    cid = _config(client, h)
    for path in (f"/api/configurations/{cid}/ontology", f"/api/configurations/{cid}/ontology/graphify"):
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer nope"}).status_code == 401


def test_unknown_configuration_is_404(client):
    h = _auth(client)
    assert client.get("/api/configurations/nope/ontology", headers=h).status_code == 404
    assert client.get("/api/configurations/nope/ontology/graphify", headers=h).status_code == 404


def test_ontology_is_what_the_one_loader_enforces(client):
    from console_api.ontology import DEFAULT_DIR
    from usep.ontology import load_ontology, resolve_pins
    from usep.ontology.export import to_dto

    h = _auth(client)
    body = client.get(f"/api/configurations/{_config(client, h)}/ontology", headers=h).json()
    packs = ["industry.banking-reference", "org.org-reference", "app.app-reference", "project.project-reference"]
    assert body == to_dto(load_ontology(DEFAULT_DIR, resolve_pins(DEFAULT_DIR, packs), allow_reference_only=True))
    assert all(p["reference_only"] for p in body["packs"] if p["level"] != "core")      # the console can say "placeholder"
    assert "tenant_id" not in str(body) and "TOKEN" not in str(body).upper().replace("TOKENS", "")


def test_graphify_graph_is_the_same_ontology(client):
    h = _auth(client)
    cid = _config(client, h)
    dto = client.get(f"/api/configurations/{cid}/ontology", headers=h).json()
    g = client.get(f"/api/configurations/{cid}/ontology/graphify", headers=h).json()
    assert g["graph"]["kind"] == "ontology-types" and g["graph"]["ontology_digest"] == dto["digest"]
    assert sorted(n["id"] for n in g["nodes"]) == sorted(c["id"] for c in dto["concepts"])
    assert {link["relation"] for link in g["links"]} - {"is_a"} == {r["id"] for r in dto["relationships"]}


def test_reads_are_audited_without_content(client, tmp_path):
    h = _auth(client)
    cid = _config(client, h)
    client.get(f"/api/configurations/{cid}/ontology", headers=h)
    text = "".join(p.read_text() for p in (tmp_path / "audit").rglob("*") if p.is_file())
    assert "ontology.read" in text and "description" not in text.split("ontology.read", 1)[1][:400]


def test_placeholder_packs_can_be_refused_and_the_failure_is_a_clear_503(tmp_path, monkeypatch):
    with _make_client(tmp_path, monkeypatch, USEP_INGESTION_ONTOLOGY_ALLOW_REFERENCE_PACKS="false") as c:
        h = _auth(c)
        cid = _config(c, h)
        r = c.get(f"/api/configurations/{cid}/ontology", headers=h)
        assert r.status_code == 503 and "cannot be loaded" in r.json()["message"]


def test_pins_come_from_settings(tmp_path, monkeypatch):
    with _make_client(tmp_path, monkeypatch, USEP_INGESTION_ONTOLOGY_PACKS="app.app-reference") as c:
        h = _auth(c)
        body = c.get(f"/api/configurations/{_config(c, h)}/ontology", headers=h).json()
        assert [p["id"] for p in body["packs"]] == ["core", "app.app-reference"]


# ---- a configuration is built against the ontology and records which one ----

def _bundle(monkeypatch):
    monkeypatch.setenv("USEP_INGESTION_TENANT_ID", "11111111-1111-4111-8111-111111111111")
    from config import Settings
    from console_api.ontology import load_bundle
    return load_bundle(Settings())


def test_what_the_graph_builder_proposes_conforms_to_the_ontology(monkeypatch):
    from console_api.graph import build_graph
    from console_api.ontology import conform
    from tests.test_console_graph import _jira, _pr, _snow

    docs = [_jira(), _pr(), _snow("incident", "INC1", "CHG0001234 failed"), _snow("change_request", "CHG0001234", "PAY-12 deploy")]
    graph = build_graph("c", docs)
    kept, pin = conform(graph, _bundle(monkeypatch))
    assert (pin.nodes_dropped, pin.edges_dropped) == (0, 0) and len(kept.nodes) == len(graph.nodes) and len(kept.edges) == len(graph.edges)
    assert kept.ontology_digest == pin.digest and {n.ontology_version for n in kept.nodes} == {pin.version}
    assert pin.reference_only is True and pin.packs[0].startswith("core@")


def test_the_ontology_decides_what_stays(monkeypatch):
    from console_api.models import Graph, GraphEdge, GraphNode
    from console_api.ontology import conform

    def node(i, concept):
        return GraphNode(id=i, concept=concept, name=i)

    def edge(s, rel, t):
        return GraphEdge(id=f"{s}-{rel}-{t}", source=s, target=t, relation=rel, confidence=1.0)

    g = Graph(configuration_id="c", generated_at="t", ontology_version="x",
              nodes=[node("req", "Requirement"), node("chg", "Change"), node("team", "Team"), node("w", "Wizard")],
              edges=[edge("chg", "implements", "req"),        # allowed
                     edge("req", "owns", "team"),             # owns is Team -> Service, not Requirement -> Team
                     edge("chg", "frobnicates", "req"),       # not a relationship type
                     edge("chg", "implements", "w"),          # its end is a node the ontology dropped
                     edge("chg", "implements", "ghost")])     # its end was never in the graph
    kept, pin = conform(g, _bundle(monkeypatch))
    assert [n.id for n in kept.nodes] == ["req", "chg", "team"] and [e.id for e in kept.edges] == ["chg-implements-req"]
    assert (pin.nodes_dropped, pin.edges_dropped) == (1, 4)


def test_a_processed_configuration_records_the_ontology_it_was_checked_against(client):
    h = _auth(client)
    cid = _config(client, h)
    config = client.get(f"/api/configurations/{cid}", headers=h).json()
    dto = client.get(f"/api/configurations/{cid}/ontology", headers=h).json()
    graph = client.get(f"/api/configurations/{cid}/graph", headers=h).json()
    assert config["status"] == "ready" and config["ontology"]["digest"] == dto["digest"] == graph["ontology_digest"]
    assert config["ontology"]["version"] == dto["ontology_version"] == graph["ontology_version"]
    assert config["ontology"]["nodes_dropped"] == 0 and config["ontology"]["reference_only"] is True
    assert {n["ontology_version"] for n in graph["nodes"]} == {dto["ontology_version"]}


def test_a_configuration_with_no_loadable_ontology_fails_with_the_reason(tmp_path, monkeypatch):
    with _make_client(tmp_path, monkeypatch, USEP_INGESTION_ONTOLOGY_ALLOW_REFERENCE_PACKS="false") as c:
        h = _auth(c)
        config = c.get(f"/api/configurations/{_config(c, h)}", headers=h).json()
        assert config["status"] == "failed" and "cannot be loaded" in config["status_detail"] and config["ontology"] is None
        assert c.get(f"/api/configurations/{config['id']}/graph", headers=h).status_code == 409   # nothing shown that was not checked
