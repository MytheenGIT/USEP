from __future__ import annotations

import pytest

from config import ConfluenceSettings, GitHubSettings, GitLabSettings, JiraSettings, ServiceNowSettings
from jira.connector import build_scopes

JIRA = {"enabled": True, "base_url": "https://x.atlassian.net", "email": "a@b.c", "api_token": "t"}


def test_lists_can_be_comma_separated_or_json_and_repeats_are_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USEP_INGESTION_JIRA_PROJECT_KEYS", "ENG, OPS ,ENG;;DOCS")
    monkeypatch.setenv("USEP_INGESTION_CONFLUENCE_SPACE_KEYS", '["ENG", "OPS"]')
    monkeypatch.setenv("USEP_INGESTION_GITLAB_PROJECT_IDS", "group/a\ngroup/b,42")

    assert JiraSettings().project_keys == ["ENG", "OPS", "DOCS"]
    assert ConfluenceSettings().space_keys == ["ENG", "OPS"]
    assert GitLabSettings().project_ids == ["group/a", "group/b", "42"]


def test_jql_queries_are_one_per_line_so_commas_inside_a_query_survive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USEP_INGESTION_JIRA_JQL_QUERIES", "project in (ENG, OPS) AND type = Bug\nlabels = release")

    assert JiraSettings().jql_queries == ["project in (ENG, OPS) AND type = Bug", "labels = release"]


def test_jira_needs_a_jql_or_project_keys_and_either_is_enough() -> None:
    assert any("PROJECT_KEYS" in p for p in JiraSettings(**JIRA).problems())
    assert JiraSettings(**JIRA, jql="project = ABC").problems() == []
    assert JiraSettings(**JIRA, project_keys="ENG,OPS").problems() == []
    assert JiraSettings(**JIRA, jql_queries=["labels = x"]).problems() == []


def test_jira_scopes_are_the_queries_plus_one_per_project() -> None:
    scopes = build_scopes("assignee = currentUser()", ["labels = x", "assignee = currentUser()"], ["ENG", "OPS", "ENG"])

    assert scopes == [
        "labels = x",
        "assignee = currentUser()",
        'project = "ENG" ORDER BY updated ASC',
        'project = "OPS" ORDER BY updated ASC',
    ]


@pytest.mark.parametrize("bad", ['ENG" OR 1=1', "ENG OPS", "9ENG", "E", "ENG;DROP"])
def test_a_project_key_cannot_carry_query_text(bad: str) -> None:
    assert any("not Jira project keys" in p for p in JiraSettings(**JIRA, project_keys=[bad]).problems())
    with pytest.raises(ValueError):
        build_scopes("", [], [bad])


def test_confluence_needs_spaces_and_each_must_be_a_real_key_or_url() -> None:
    base = {"enabled": True, "base_url": "https://x.atlassian.net", "email": "a@b.c", "api_token": "t"}

    assert any("SPACE_KEYS is required" in p for p in ConfluenceSettings(**base).problems())
    assert ConfluenceSettings(**base, space_keys="ENG, ~personal, https://x.atlassian.net/wiki/spaces/OPS/overview").problems() == []
    bad = ConfluenceSettings(**base, space_keys=['ENG" OR space = "SECRET', "ftp://x/spaces/A"]).problems()
    assert len(bad) == 2


def test_confluence_refuses_to_build_a_query_from_a_bad_key() -> None:
    from confluence.connector import scope_filter

    assert scope_filter("ENG") == ('space = "ENG"', "ENG")
    with pytest.raises(ValueError):
        scope_filter('ENG" OR space = "SECRET')


def test_gitlab_needs_repositories_or_the_member_switch() -> None:
    base = {"enabled": True, "private_token": "t"}

    assert any("PROJECT_IDS" in p for p in GitLabSettings(**base).problems())
    assert GitLabSettings(**base, all_member_projects=True).problems() == []
    assert GitLabSettings(**base, project_ids="group/a, 42, https://gitlab.com/g/p.git").problems() == []
    assert len(GitLabSettings(**base, project_ids=["not a path", "a b/c"]).problems()) == 2


def test_github_needs_a_token_and_repositories_or_the_member_switch() -> None:
    base = {"enabled": True, "token": "t"}

    assert any("REPOSITORIES" in p for p in GitHubSettings(**base).problems())
    assert GitHubSettings(**base, all_member_projects=True).problems() == []
    assert GitHubSettings(**base, repositories="acme/a, https://github.com/acme/b.git, git@github.com:acme/c.git").problems() == []
    assert len(GitHubSettings(**base, repositories=["not a repo", "acme"]).problems()) == 2
    assert any("TOKEN is required" in p for p in GitHubSettings(enabled=True, repositories=["acme/a"]).problems())


def test_servicenow_needs_an_instance_a_login_and_tables() -> None:
    full = {"enabled": True, "base_url": "https://dev1.service-now.com", "username": "u", "password": "p", "tables": "incident, change_request"}

    assert ServiceNowSettings(**full).problems() == [] and ServiceNowSettings(**full).tables == ["incident", "change_request"]
    assert {p.split(" ")[0] for p in ServiceNowSettings(enabled=True).problems()} == {
        "USEP_INGESTION_SERVICENOW_BASE_URL", "USEP_INGESTION_SERVICENOW_USERNAME", "USEP_INGESTION_SERVICENOW_PASSWORD", "USEP_INGESTION_SERVICENOW_TABLES",
    }
    assert any("not a ServiceNow table" in p for p in ServiceNowSettings(**{**full, "tables": ["incident;drop"]}).problems())


def test_gitlab_accepts_ssh_links_too() -> None:
    assert GitLabSettings(enabled=True, private_token="t", project_ids="git@gitlab.com:grp/sub/proj.git").problems() == []
