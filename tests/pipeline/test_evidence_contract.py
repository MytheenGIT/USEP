"""The evidence object, the evidence event and the egress flag: what the chunking and LLM teams depend on."""
import json
import re

import pytest

from tests.pipeline.helpers import BUCKET, ONT, jira, published, raw_event
from usep.pipeline.egress import EgressDenied, EgressPolicy, assert_allowed, decide
from usep.pipeline.acl import from_connector, merge
from usep.pipeline.classify import Labels
from usep.pipeline.normalize.record import UNKNOWN_ACL, Acl, html_to_text
from usep.pipeline.redact import RedactionReport
from usep.pipeline.topics import EVIDENCE_OBJECT_FIELDS, EVIDENCE_REQUIRED

DOC = (ONT.parent / "docs/contracts/evidence.md").read_text(encoding="utf-8")


def evidence_objects(s3):
    return [json.loads(v) for k, v in sorted(s3.objects.items()) if k.startswith("evidence/")]


def with_event(s3, source, ref, raw, acl=None):
    ev = raw_event(s3, source, ref, raw)
    if acl is not None:
        p = dict(ev.payload)
        p["acl"] = acl
        ev = type(ev)(ev.event_id, ev.topic, ev.key, ev.tenant_id, ev.type, ev.schema_version, ev.occurred_at, p, ev.headers)
    return ev


# ---------------------------------------------------------------- the contract document matches the code
def test_document_names_every_evidence_object_field_and_event_field():
    for f in EVIDENCE_OBJECT_FIELDS + EVIDENCE_REQUIRED:
        assert f"`{f}`" in DOC, f"{f} is in the code but not in docs/contracts/evidence.md"


def test_evidence_object_has_exactly_the_documented_fields(env):
    s3, _, w = env
    w.handle(raw_event(s3, "jira", "ABC-1", jira("ABC-1", "Story", "Open")))
    (obj,) = evidence_objects(s3)
    assert set(obj) == set(EVIDENCE_OBJECT_FIELDS) and obj["schema_version"] == 1


def test_evidence_event_carries_every_required_field_and_points_at_a_real_object(env):
    s3, _, w = env
    w.handle(raw_event(s3, "jira", "ABC-1", jira("ABC-1", "Story", "Open", desc="Customers pay by card")))
    (ev,) = published(s3, "evidence.jira")
    p = ev["payload"]
    assert set(EVIDENCE_REQUIRED) <= set(p)
    key = p["evidence_ref"].removeprefix(f"s3://{BUCKET}/")
    assert json.loads(s3.objects[key])["text"].endswith("Customers pay by card")
    assert ev["tenant_id"] and "text" not in p                 # the event is a pointer: no content on the bus


# ---------------------------------------------------------------- every kind of record is announced, except empty text
def test_unlabelled_page_and_figma_file_are_announced_even_though_they_make_no_entity(env):
    s3, _, w = env
    page = {"id": "22", "title": "Notes", "version": {"number": 1}, "body": {"storage": {"value": "<p>ABC-7</p>"}}}
    figma = {"name": "Checkout", "version": "9", "document": {"children": [{"type": "TEXT", "characters": "Pay now"}]}}
    w.handle(raw_event(s3, "confluence", "22", page))
    w.handle(raw_event(s3, "figma", "FILEKEY1", figma))
    assert [e["payload"]["source_id"] for e in published(s3, "evidence.confluence")] == ["22"]
    assert [e["payload"]["source_id"] for e in published(s3, "evidence.figma")] == ["FILEKEY1"]


def test_edge_only_record_writes_evidence_but_announces_nothing(env):
    s3, _, w = env
    link = {"type": {"outward": "implements", "inward": "is implemented by"}, "inwardIssue": {"key": "ABC-9"}}
    w.handle(raw_event(s3, "jira", "ABC-10", jira("ABC-10", "Story", "Open", links=[link])))
    assert len(evidence_objects(s3)) == 2                       # the issue and its link record (the edge cites it)
    assert [e["payload"]["source_id"] for e in published(s3, "evidence.jira")] == ["ABC-10"]


def test_quarantined_record_has_no_evidence(env):
    s3, _, w = env
    w.handle(raw_event(s3, "jira", "ABC-4", jira("ABC-4", "Spike", "Open")))
    assert evidence_objects(s3) == [] and published(s3, "evidence.jira") == []


def test_replay_does_not_duplicate_the_object_and_the_event_key_is_stable(env):
    s3, _, w = env
    ev = raw_event(s3, "jira", "ABC-1", jira("ABC-1", "Story", "Open"))
    w.handle(ev)
    w.handle(ev)
    assert len(evidence_objects(s3)) == 1
    keys = {e["headers"]["idempotency_key"] for e in published(s3, "evidence.jira")}
    assert len(keys) == 1


# ---------------------------------------------------------------- ACL: principals and scopes from the connector
def test_connector_acl_becomes_principals_and_scopes_on_evidence(env):
    s3, _, w = env
    page = {"id": "13", "title": "Plans", "version": {"number": 1}, "body": {"storage": {"value": "<p>x</p>"}}}
    w.handle(with_event(s3, "confluence", "13", page, {"space_key": "ENG", "read_restriction_groups": ["leads"]}))
    (obj,) = evidence_objects(s3)
    assert obj["acl"] == {"known": True, "scheme": "confluence_page_restriction", "principals": ["group:leads"],
                          "restricted": True, "scopes": ["space:ENG"]}
    assert obj["acl_state"] == "known" and obj["owners_only"] and obj["sensitivity"] == 2


def test_scope_alone_never_makes_an_acl_known(env):
    s3, _, w = env
    w.handle(with_event(s3, "jira", "ABC-1", jira("ABC-1", "Story", "Open"), {"project_key": "ABC"}))
    (obj,) = evidence_objects(s3)
    assert obj["acl"]["scopes"] == ["project:ABC"] and obj["acl_state"] == "unknown" and obj["owners_only"]


def test_gitlab_private_project_is_known_restricted_and_public_is_known_open(env):
    s3, _, w = env
    mr = lambda n: {"merge_request": {"iid": n, "project_id": 5, "title": f"MR {n}", "state": "opened"}, "commits": []}
    w.handle(with_event(s3, "gitlab", "5!1", mr(1), {"project_path": "pay/checkout", "visibility": "private"}))
    w.handle(with_event(s3, "gitlab", "5!2", mr(2), {"project_path": "pay/docs", "visibility": "public"}))
    by_id = {o["source_id"]: o for o in evidence_objects(s3)}
    assert by_id["5!1"]["owners_only"] and by_id["5!1"]["sensitivity"] == 2
    assert by_id["5!2"]["acl_state"] == "known" and not by_id["5!2"]["owners_only"]
    assert by_id["5!2"]["egress"] == {"external_model": True, "reasons": []}


def test_merge_is_a_union_and_never_loosens():
    parsed = Acl(True, "jira_issue_security", ("security_level:Finance",), True)
    merged = merge(parsed, from_connector("jira", {"project_key": "ABC"}))
    assert merged.restricted and merged.known and merged.principals == ("security_level:Finance",)
    assert merged.scopes == ("project:ABC",)
    assert merge(UNKNOWN_ACL, UNKNOWN_ACL) == UNKNOWN_ACL


def test_changed_acl_with_unchanged_payload_writes_a_new_evidence_object(env):
    """GitLab visibility is not in the MR payload, so the checksum does not change when a project goes private."""
    s3, _, w = env
    mr = {"merge_request": {"iid": 3, "project_id": 5, "title": "MR", "state": "opened"}, "commits": []}
    ev = with_event(s3, "gitlab", "5!3", mr, {"visibility": "public"})
    w.handle(ev)
    w.handle(type(ev)(ev.event_id, ev.topic, ev.key, ev.tenant_id, ev.type, ev.schema_version, ev.occurred_at,
                      {**ev.payload, "acl": {"visibility": "private"}}, ev.headers))
    objs = evidence_objects(s3)
    assert len(objs) == 2 and {o["owners_only"] for o in objs} == {True, False}
    assert len({e["payload"]["evidence_ref"] for e in published(s3, "evidence.gitlab")}) == 2


# ---------------------------------------------------------------- egress
def labels(sens=1, owners_only=False):
    return Labels(sens, "known", owners_only, None, ())


def test_egress_blocks_each_reason_and_allows_clean_internal_text():
    assert decide(labels(), RedactionReport()) == {"external_model": True, "reasons": []}
    assert decide(labels(2), RedactionReport())["reasons"] == ["sensitivity_2"]
    assert decide(labels(owners_only=True), RedactionReport())["reasons"] == ["owners_only"]
    assert decide(labels(), RedactionReport(secrets={"aws_access_key": 1}))["reasons"] == ["secret_found"]
    assert decide(labels(), RedactionReport(pii={"email": 1}))["reasons"] == ["pii_found"]
    relaxed = EgressPolicy(max_sensitivity=2, allow_owners_only=True, allow_pii_hit=True)
    assert decide(labels(2, True), RedactionReport(pii={"email": 1}), relaxed)["external_model"]


def test_assert_allowed_denies_blocked_and_missing_decisions():
    assert_allowed({"egress": {"external_model": True, "reasons": []}})
    with pytest.raises(EgressDenied) as e:
        assert_allowed({"egress": {"external_model": False, "reasons": ["owners_only"]}})
    assert e.value.reasons == ["owners_only"]
    for bad in ({}, {"egress": None}, {"egress": {"external_model": "yes"}}):
        with pytest.raises(EgressDenied):
            assert_allowed(bad)


def test_unknown_acl_blocks_egress_end_to_end(env):
    s3, _, w = env
    w.handle(raw_event(s3, "jira", "ABC-1", jira("ABC-1", "Story", "Open")))
    (ev,) = published(s3, "evidence.jira")
    assert ev["payload"]["egress"] == {"external_model": False, "reasons": ["owners_only"]}
    with pytest.raises(EgressDenied):
        assert_allowed(evidence_objects(s3)[0])


# ---------------------------------------------------------------- text coverage and structure
def test_gitlab_text_includes_commit_messages_and_human_comments_but_not_diffs_or_system_notes(env):
    s3, _, w = env
    raw = {"merge_request": {"iid": 8, "project_id": 5, "title": "Add bus", "description": "Why", "state": "opened"},
           "commits": [{"message": "wire the queue"}], "approvals": {},
           "notes": [{"body": "looks good", "system": False}, {"body": "added 1 commit", "system": True}],
           "diffs": [{"diff": "+SECRETCODE"}]}
    w.handle(raw_event(s3, "gitlab", "5!8", raw))
    text = evidence_objects(s3)[0]["text"]
    assert "Commits:\n- wire the queue" in text and "Comments:\nlooks good" in text
    assert "added 1 commit" not in text and "SECRETCODE" not in text


def test_github_text_includes_commits_and_reviews(env):
    s3, _, w = env
    from tests.pipeline.helpers import gh_pr
    raw = {"pull_request": gh_pr(number=9), "commits": [{"commit": {"message": "add queue"}}],
           "reviews": [{"body": "ship it"}, {"body": ""}]}
    w.handle(raw_event(s3, "github", "github:acme/pay#9", raw))
    text = evidence_objects(s3)[0]["text"]
    assert "Commits:\n- add queue" in text and "Reviews:\nship it" in text


def test_html_keeps_headings_and_list_items():
    out = html_to_text("<h1>Title</h1><p>Intro</p><h2>Part</h2><ul><li>one</li><li>two &amp; three</li></ul>")
    assert out.splitlines() == ["# Title", "Intro", "## Part", "- one", "- two & three"]


def test_secret_in_a_commit_message_is_redacted_in_evidence(env):
    s3, _, w = env
    raw = {"merge_request": {"iid": 1, "project_id": 5, "title": "t", "state": "opened"},
           "commits": [{"message": "oops AKIAABCDEFGHIJKLMNOP"}], "notes": []}
    w.handle(raw_event(s3, "gitlab", "5!1", raw))
    blob = b"".join(v for k, v in s3.objects.items() if not k.startswith("raw/"))
    assert b"AKIAABCDEFGHIJKLMNOP" not in blob
    assert evidence_objects(s3)[0]["egress"]["reasons"].count("secret_found") == 1


def test_evidence_key_ends_with_checksum_and_label_hash(env):
    s3, _, w = env
    w.handle(raw_event(s3, "jira", "ABC-1", jira("ABC-1", "Story", "Open")))
    (key,) = [k for k in s3.objects if k.startswith("evidence/")]
    assert re.search(r"/[0-9a-f]+\.[0-9a-f]{12}\.json$", key)
