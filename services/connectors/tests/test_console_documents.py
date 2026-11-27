from __future__ import annotations

from datetime import UTC, datetime

from common.source_document import SourceType
from confluence.models import ConfluenceDocument, ConfluenceVersion
from console_api.documents import dump_documents, load_documents
from console_api.graph import build_graph
from console_api.store import ConfigurationStore
from figma.models import FigmaDocument
from github.models import GitHubCommit, GitHubDocument
from gitlab.models import GitLabCommit, GitLabDocument
from gitrepo.models import GitCommitDocument, GitFileChange
from jira.models import JiraDocument
from servicenow.models import ServiceNowDocument

NOW = datetime.now(UTC)
COMMON = dict(retrieved_at=NOW, raw_payload={"k": 1}, source_url="https://x", title="t")


def _docs():
    return {
        "jira": [JiraDocument(source=SourceType.JIRA, source_type="issue", source_object_id="PAY-1", issue_key="PAY-1", summary="s", status="Done", **COMMON)],
        "confluence": [ConfluenceDocument(source=SourceType.CONFLUENCE, source_type="page", source_object_id="9", space_key="ENG", page_id="9", version=ConfluenceVersion(number=2), **COMMON)],
        "gitlab": [
            GitLabDocument(source=SourceType.GITLAB, source_type="merge_request", source_object_id="7!1", project_id="7", mr_iid="1", state="merged", commits=[GitLabCommit(sha="a", message="PAY-1", url="u", raw={})], **COMMON),
            GitCommitDocument(source=SourceType.GITLAB, source_type="commit", source_object_id="g/p@abc", repository="g/p", sha="abc", message="PAY-1 x", files=[GitFileChange(status="M", path="a.py")], **COMMON),
        ],
        "github": [GitHubDocument(source=SourceType.GITHUB, source_type="pull_request", source_object_id="a/b#3", repository="a/b", pr_number="3", state="merged", commits=[GitHubCommit(sha="c", message="PAY-1", url="u", raw={})], **COMMON)],
        "servicenow": [ServiceNowDocument(source=SourceType.SERVICENOW, source_type="incident", source_object_id="incident:INC1", table="incident", number="INC1", sys_id="s", **COMMON)],
        "figma": [FigmaDocument(source=SourceType.FIGMA, source_type="file", source_object_id="K", file_key="K", file_name="F", **COMMON)],
    }


def test_every_kind_of_document_survives_being_saved_and_loaded(tmp_path) -> None:
    store = ConfigurationStore(str(tmp_path))
    cid = "01a21b20-a20e-75be-8f9b-80bc8d845006"
    for source, items in _docs().items():
        store.save_documents(cid, source, items)
        loaded = store.load_documents(cid, source)
        assert loaded is not None and [type(d) for d in loaded] == [type(d) for d in items]
        assert dump_documents(loaded) == dump_documents(items)


def test_the_graph_is_the_same_from_saved_documents_as_from_fresh_ones(tmp_path) -> None:
    store = ConfigurationStore(str(tmp_path))
    cid = "01a21b20-a20e-75be-8f9b-80bc8d845006"
    docs = _docs()
    for source, items in docs.items():
        store.save_documents(cid, source, items)
    fresh = build_graph(cid, [d for items in docs.values() for d in items])
    saved = build_graph(cid, [d for s in docs for d in store.load_documents(cid, s) or []])
    assert [n.id for n in saved.nodes] == [n.id for n in fresh.nodes] and [e.id for e in saved.edges] == [e.id for e in fresh.edges]


def test_missing_or_unreadable_saved_results_are_none_not_a_partial_list(tmp_path) -> None:
    store = ConfigurationStore(str(tmp_path))
    cid = "01a21b20-a20e-75be-8f9b-80bc8d845006"
    assert store.load_documents(cid, "jira") is None
    (tmp_path / "configurations" / cid / "sources").mkdir(parents=True)
    (tmp_path / "configurations" / cid / "sources" / "jira.json").write_text("not json")
    assert store.load_documents(cid, "jira") is None
    assert load_documents("jira", [{"source_type": "issue", "nonsense": True}]) is None
