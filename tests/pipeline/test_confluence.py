"""Confluence pages: decisions, evidence-only pages, restrictions, repository links."""
import json


from tests.fake_s3 import FakeS3
from tests.pipeline.helpers import (BUCKET, edges, published, raw_event)
from usep.adapters.s3.event_bus import S3EventBus
from usep.adapters.s3.snapshot_store import S3SnapshotStore
from usep.pipeline.topics import register_schemas
from usep.pipeline.worker import AcquisitionWorker
from usep.ports.event_bus import SchemaRegistry




def test_confluence_adr_page_is_a_decision_and_unlabelled_page_is_evidence_only(env):
    s3, _, w = env
    page = lambda pid, labels: {"id": pid, "title": f"Page {pid}", "space": {"key": "ENG"}, "version": {"number": 3, "when": "2026-02-01T00:00:00.000Z"},
                                "body": {"storage": {"value": "<p>Use <b>S3</b> as bus.</p>"}},
                                "metadata": {"labels": {"results": [{"name": n} for n in labels]}}}
    a = w.handle(raw_event(s3, "confluence", "11", page("11", ["ADR"])))
    b = w.handle(raw_event(s3, "confluence", "12", page("12", [])))
    assert a.entities == 1 and b.evidence_only == 1 and b.entities == 0
    assert published(s3, "entity.architecture")[0]["payload"]["type"] == "Decision"
    ev = [json.loads(v) for k, v in s3.objects.items() if k.startswith("evidence/confluence")]
    assert any(e["text"].endswith("Use S3 as bus.") for e in ev)


def test_confluence_page_restriction_is_a_known_restricted_acl(env):
    s3, _, w = env
    page = {"id": "13", "title": "Secret plans", "version": {"number": 1}, "metadata": {"labels": {"results": [{"name": "adr"}]}},
            "restrictions": {"read": {"restrictions": {"group": {"results": [{"name": "leads"}]}}}}}
    w.handle(raw_event(s3, "confluence", "13", page))
    p = published(s3, "entity.architecture")[0]["payload"]
    assert p["labels"]["acl_state"] == "known" and p["labels"]["owners_only"] and p["labels"]["sensitivity"] == 2


def test_page_documents_service_by_repo_url_only_on_known_hosts(bundle):
    s3 = FakeS3()
    reg = SchemaRegistry()
    register_schemas(reg, bundle.domains)
    bus = S3EventBus(s3, BUCKET, reg, partitions=4)
    w = AcquisitionWorker(bus, S3SnapshotStore(s3, BUCKET), lambda: bundle, repo_hosts=("gitlab.example.com",))
    body = ('<p>Code: <a href="https://gitlab.example.com/pay/checkout/-/tree/main">repo</a> '
            'and <a href="https://github.com/other/thing">x</a>; refs ABC-5</p>')
    page = {"id": "21", "title": "ADR 9", "version": {"number": 1}, "body": {"storage": {"value": body}},
            "metadata": {"labels": {"results": [{"name": "adr"}]}}, "ancestors": [{"id": "1"}, {"id": "7"}]}
    out = w.handle(raw_event(s3, "confluence", "21", page))
    assert out.links == 2
    (doc,) = edges(s3, "documents")
    assert doc["to"]["repository_ref"] == "https://gitlab.example.com/pay/checkout" and doc["to"]["type"] == "Service"
    assert doc["provenance"]["rule"] == "repo_url_in_body" and doc["from"]["type"] == "Decision"
    ev = json.loads(next(v for k, v in s3.objects.items() if k.startswith("evidence/confluence")))
    assert ev["refs"] == {"jira_keys": ["ABC-5"], "repo_urls": ["https://gitlab.example.com/pay/checkout"], "parent_id": "7"}


def test_unlabelled_page_makes_no_edge_but_evidence_records_its_refs(env):
    s3, _, w = env
    page = {"id": "22", "title": "Notes", "version": {"number": 1}, "body": {"storage": {"value": "<p>ABC-7</p>"}}}
    out = w.handle(raw_event(s3, "confluence", "22", page))
    assert (out.evidence_only, out.links) == (1, 0)
    ev = json.loads(next(v for k, v in s3.objects.items() if k.startswith("evidence/confluence")))
    assert ev["refs"]["jira_keys"] == ["ABC-7"]



def test_confluence_wrapped_payload_page_children_versions(env):
    """The connector stores {page, children, versions}; the page is what carries the content."""
    s3, _, w = env
    page = {"id": "31", "title": "ADR 12", "version": {"number": 4, "when": "2026-02-01T00:00:00.000Z"},
            "body": {"storage": {"value": "<p>Refs ABC-8</p>"}},
            "metadata": {"labels": {"results": [{"name": "adr"}]}}, "ancestors": [{"id": "2"}]}
    out = w.handle(raw_event(s3, "confluence", "31", {"page": page, "children": {"results": []}, "versions": []}))
    assert out.entities == 1 and out.links == 1
    assert published(s3, "entity.architecture")[0]["payload"]["type"] == "Decision"
