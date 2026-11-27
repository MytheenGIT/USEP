from __future__ import annotations

import pytest

from config import Settings
from console_api import repositories
from console_api.models import ConnectorSummary
from console_api.repositories import RepositoryListError, list_repositories
from console_api.secrets_store import Credentials
from console_api.validation import SPECS, ParsedConnector
from github.client import GitHubClient
from gitlab.client import GitLabClient


def _parsed(url: str, secret: str = "tok", method: str = "token") -> ParsedConnector:
    return ParsedConnector(summary=ConnectorSummary(enabled=True, auth_method=method), base_url=url, credentials=Credentials("", secret))


@pytest.fixture
def patched(monkeypatch):
    closed = []

    async def github(self, limit):
        return [{"full_name": "Acme/zeta", "name": "zeta", "private": True, "description": "z"}, {"full_name": "acme/Alpha", "name": "Alpha", "private": False}]

    async def gitlab(self, limit):
        return [{"path_with_namespace": "grp/b", "name": "b", "visibility": "internal"}, {"path_with_namespace": "grp/a", "name": "a", "visibility": "private"}]

    async def aclose(self):
        closed.append(1)

    monkeypatch.setattr(GitHubClient, "list_member_repos", github)
    monkeypatch.setattr(GitLabClient, "list_member_projects", gitlab)
    monkeypatch.setattr(GitHubClient, "aclose", aclose)
    monkeypatch.setattr(GitLabClient, "aclose", aclose)
    return closed


async def test_github_repositories_are_listed_sorted_with_their_visibility(patched) -> None:
    result = await list_repositories(SPECS["github"], _parsed("https://api.github.com"), Settings())
    assert [(r.path, r.visibility) for r in result.repositories] == [("acme/Alpha", "public"), ("Acme/zeta", "private")] and not result.truncated
    assert patched == [1]  # the client was closed


async def test_gitlab_projects_are_listed_the_same_way(patched) -> None:
    result = await list_repositories(SPECS["gitlab"], _parsed("https://gitlab.com"), Settings())
    assert [(r.path, r.visibility) for r in result.repositories] == [("grp/a", "private"), ("grp/b", "internal")]


async def test_more_than_the_limit_is_flagged_not_silently_cut(monkeypatch) -> None:
    async def many(self, limit):
        return [{"full_name": f"o/r{i:04d}", "name": f"r{i}", "private": False} for i in range(limit)]

    async def aclose(self):
        return None

    monkeypatch.setattr(GitHubClient, "list_member_repos", many)
    monkeypatch.setattr(GitHubClient, "aclose", aclose)
    result = await list_repositories(SPECS["github"], _parsed("https://api.github.com"), Settings())
    assert len(result.repositories) == repositories.LIMIT and result.truncated


async def test_it_explains_why_it_cannot_list(monkeypatch) -> None:
    with pytest.raises(RepositoryListError, match="no repositories"):
        await list_repositories(SPECS["jira"], _parsed("https://x.atlassian.net"), Settings())
    with pytest.raises(RepositoryListError, match="needs a token"):
        await list_repositories(SPECS["github"], _parsed("https://api.github.com", method="ssh_key"), Settings())
    with pytest.raises(RepositoryListError, match="Enter the GitHub token"):
        await list_repositories(SPECS["github"], _parsed("https://api.github.com", secret=""), Settings())

    async def refused(self, limit):
        import httpx

        request = httpx.Request("GET", "https://api.github.com/user/repos")
        raise httpx.HTTPStatusError("x", request=request, response=httpx.Response(401, json={"message": "Bad credentials"}, request=request))

    async def aclose(self):
        return None

    monkeypatch.setattr(GitHubClient, "list_member_repos", refused)
    monkeypatch.setattr(GitHubClient, "aclose", aclose)
    with pytest.raises(RepositoryListError, match="401: Bad credentials"):
        await list_repositories(SPECS["github"], _parsed("https://api.github.com"), Settings())
