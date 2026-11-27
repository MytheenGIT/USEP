"""Cross-system link rules and issue-link edges."""


from tests.pipeline.helpers import (jira, ONT, published, raw_event)
from usep.ontology import load_ontology




def test_issue_link_becomes_edge_with_flipped_direction(env):
    s3, _, w = env
    link = {"type": {"outward": "implements", "inward": "is implemented by"}, "inwardIssue": {"key": "ABC-9"}}
    out = w.handle(raw_event(s3, "jira", "ABC-10", jira("ABC-10", "Story", "Open", links=[link])))
    assert (out.entities, out.edges) == (1, 1)
    edge = next(e["payload"] for e in published(s3, "entity.product") if e["payload"]["kind"] == "edge")
    assert edge["type"] == "implements"
    assert edge["from"]["source_id"] == "ABC-9" and edge["to"]["source_id"] == "ABC-10"   # ABC-9 implements ABC-10


def test_no_links_when_pack_without_relationship_is_pinned():
    b = load_ontology(ONT, ["org.org-reference@0.1.0", "project.project-reference@0.1.0"], allow_reference_only=True)
    from usep.pipeline.links import extract
    from usep.pipeline.normalize import normalize
    rec = normalize("gitlab", "5!1", {"iid": 1, "project_id": 5, "title": "ABC-1 x", "state": "opened"})[0]
    assert extract(b, rec, "Change") == []


def test_links_are_idempotent_across_replays(env):
    s3, _, w = env
    ev = raw_event(s3, "gitlab", "5!10", {"iid": 10, "project_id": 5, "title": "ABC-1 x", "state": "opened"})
    w.handle(ev)
    w.handle(ev)
    ks = [e["headers"]["idempotency_key"] for e in published(s3, "entity.product") if e["payload"]["kind"] == "edge"]
    assert len(ks) == 2 and ks[0] == ks[1]


def test_project_key_allowlist_limits_keys(env):
    from usep.pipeline.links import scan
    from usep.pipeline.normalize import normalize
    rec = normalize("gitlab", "5!1", {"iid": 1, "project_id": 5, "title": "ABC-1 and XYZ-2 and bugfix-ABC-3-x", "state": "opened"})[0]
    assert set(scan(rec)[0]) == {"ABC-1", "XYZ-2", "ABC-3"}
    assert set(scan(rec, project_keys=("ABC",))[0]) == {"ABC-1", "ABC-3"}

