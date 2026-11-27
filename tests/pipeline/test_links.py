"""Cross-system link rules and issue-link edges."""


from tests.pipeline.helpers import ONT, edges, jira, published, raw_event
from usep.ontology_runtime import load_ontology




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



# ---------------------------------------------------------------- Jira remote links (native API links to Confluence)
def remote(*urls):
    return [{"object": {"url": u}} for u in urls]


def test_jira_remote_link_to_a_confluence_page_becomes_an_api_link_edge(env):
    s3, _, w = env
    raw = jira("ABC-50", "Story", "Open")
    raw["remote_links"] = remote("https://x.atlassian.net/wiki/spaces/ENG/pages/12345/Design+doc",
                                 "https://x.atlassian.net/wiki/pages/viewpage.action?pageId=777",
                                 "https://example.com/not-a-page")
    out = w.handle(raw_event(s3, "jira", "ABC-50", raw))
    by_to = {e["to"]["source_id"]: e for e in edges(s3, "references")}
    assert set(by_to) == {"12345", "777"} and out.links == 2
    e = by_to["12345"]
    assert e["to"]["source_system"] == "confluence" and e["to"]["pending_resolution"]
    assert e["provenance"] == {"method": "api_link", "rule": "jira_remote_link", "evidence": "12345"}
    assert e["attributes"]["confidence"] == 1.0


def test_remote_links_are_listed_in_evidence_refs_and_absent_when_none(env):
    import json
    s3, _, w = env
    raw = jira("ABC-51", "Story", "Open")
    raw["remote_links"] = remote("https://x.atlassian.net/wiki/spaces/ENG/pages/42")
    w.handle(raw_event(s3, "jira", "ABC-51", raw))
    w.handle(raw_event(s3, "jira", "ABC-52", jira("ABC-52", "Story", "Open")))
    refs = {json.loads(v)["source_id"]: json.loads(v)["refs"] for k, v in s3.objects.items() if k.startswith("evidence/jira/issue")}
    assert refs["ABC-51"]["confluence_page_ids"] == ["42"] and "confluence_page_ids" not in refs["ABC-52"]


def test_tiny_links_and_prose_mentions_of_page_urls_are_not_remote_links(env):
    s3, _, w = env
    raw = jira("ABC-53", "Story", "Open", desc="see https://x.atlassian.net/wiki/spaces/ENG/pages/999")
    raw["remote_links"] = remote("https://x.atlassian.net/wiki/x/AbCdE")
    w.handle(raw_event(s3, "jira", "ABC-53", raw))
    assert edges(s3, "references") == []


def test_ado_project_visibility_is_a_known_acl_and_private_restricts():
    from usep.pipeline.acl import from_connector
    priv = from_connector("ado", {"project": "Pay", "repository": "r", "visibility": "private"})
    pub = from_connector("ado", {"project": "Pay", "repository": "r", "visibility": "public"})
    none = from_connector("ado", {"project": "Pay", "area_path": "Pay\\x"})          # a work item: no visibility
    assert priv.known and priv.restricted and "visibility:private" in priv.principals
    assert pub.known and not pub.restricted
    assert not none.known
