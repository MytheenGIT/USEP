from __future__ import annotations

from datetime import UTC, datetime

from common.source_document import SourceType
from console_api.graph import build_graph
from github.models import GitHubCommit, GitHubDocument
from gitrepo.models import GitCommitDocument
from jira.models import JiraDocument
from servicenow.models import ServiceNowDocument

NOW = datetime.now(UTC)


def _jira(key: str = "PAY-12", kind: str = "Story") -> JiraDocument:
    return JiraDocument(
        source=SourceType.JIRA, source_type="issue", source_object_id=key, source_url=f"https://x/browse/{key}", retrieved_at=NOW,
        raw_payload={"fields": {"issuetype": {"name": kind}}}, title="Retry payments", issue_key=key, summary="Retry payments", status="Done",
    )


def _pr() -> GitHubDocument:
    return GitHubDocument(
        source=SourceType.GITHUB, source_type="pull_request", source_object_id="acme/checkout#7", source_url="https://github.com/acme/checkout/pull/7",
        retrieved_at=NOW, raw_payload={}, title="Add retry", repository="acme/checkout", pr_number="7", state="merged",
        commits=[GitHubCommit(sha="a", message="PAY-12 retry on timeout", url="u", raw={})],
    )


def _snow(table: str, number: str, text: str = "") -> ServiceNowDocument:
    return ServiceNowDocument(
        source=SourceType.SERVICENOW, source_type=table, source_object_id=f"{table}:{number}", source_url=f"https://x/{number}", retrieved_at=NOW,
        raw_payload={}, title=f"{number} title", table=table, number=number, sys_id="s", short_description="title", description=text, state="New",
    )


def test_a_github_pull_request_that_names_an_issue_implements_it() -> None:
    graph = build_graph("c", [_jira(), _pr()])
    assert {n.id: n.concept for n in graph.nodes} == {"jira:PAY-12": "Requirement", "github:acme/checkout#7": "Change"}
    assert [(e.relation, e.source, e.target, e.confidence) for e in graph.edges] == [("implements", "github:acme/checkout#7", "jira:PAY-12", 1.0)]


def test_a_commit_read_over_ssh_is_a_change_too() -> None:
    commit = GitCommitDocument(
        source=SourceType.GITLAB, source_type="commit", source_object_id="grp/proj@0123456789abcdef", source_url="https://gitlab.com/c",
        retrieved_at=NOW, raw_payload={}, title="PAY-12 add retry", repository="grp/proj", sha="0123456789abcdef", message="PAY-12 add retry",
    )
    graph = build_graph("c", [_jira(), commit])
    assert {n.id: (n.concept, n.labels) for n in graph.nodes}["gitlab:grp/proj@0123456789abcdef"] == ("Change", ["commit"])
    assert [(e.relation, e.target) for e in graph.edges] == [("implements", "jira:PAY-12")]


def test_servicenow_incidents_and_changes_are_mapped_and_linked() -> None:
    docs = [
        _jira(),
        _snow("change_request", "CHG0001001", "Deploy the PAY-12 retry"),
        _snow("incident", "INC0007001", "Timeouts started after CHG0001001"),
        _snow("incident", "INC0007002", "Unrelated"),
        _snow("problem", "PRB0000100"),
        _snow("sys_user", "USR1"),
    ]
    graph = build_graph("c", docs)

    concepts = {n.id: n.concept for n in graph.nodes}
    assert concepts == {
        "jira:PAY-12": "Requirement", "servicenow:change_request:CHG0001001": "Change", "servicenow:incident:INC0007001": "Incident",
        "servicenow:incident:INC0007002": "Incident", "servicenow:problem:PRB0000100": "Incident",
    }  # a table the graph does not model is left out
    edges = {(e.relation, e.source, e.target): e.confidence for e in graph.edges}
    assert edges == {
        ("implements", "servicenow:change_request:CHG0001001", "jira:PAY-12"): 1.0,
        ("caused_by", "servicenow:incident:INC0007001", "servicenow:change_request:CHG0001001"): 0.6,  # inferred, so lower
    }


def test_each_source_is_optional_for_the_graph() -> None:
    assert build_graph("c", []).nodes == []
    assert [n.id for n in build_graph("c", [_pr()]).nodes] == ["github:acme/checkout#7"]  # no Jira: a change with no issue to link to
