from __future__ import annotations

import httpx

from confluence.client import ConfluenceClient
from confluence.connector import ConfluenceConnector
from figma.client import FigmaClient
from figma.connector import FigmaConnector
from gitlab.client import GitLabClient
from gitlab.connector import GitLabConnector
from jira.client import JiraClient
from jira.connector import JiraConnector

BASE = "https://x.atlassian.net"


def _gitlab(handler, explicit=None, **kwargs) -> GitLabConnector:
    return GitLabConnector(GitLabClient("https://gitlab.com", "t", transport=httpx.MockTransport(handler)), explicit or [], **kwargs)


def _projects_handler(pages: dict[str, list[dict]]):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v4/projects":
            assert request.url.params["membership"] == "true" and request.url.params["archived"] == "false"
            page = request.url.params["page"]
            headers = {"x-next-page": str(int(page) + 1)} if str(int(page) + 1) in pages else {}
            return httpx.Response(200, json=pages[page], headers=headers)
        return httpx.Response(404)

    return handler


async def test_gitlab_finds_every_member_repository_across_pages() -> None:
    handler = _projects_handler({"1": [{"id": 1, "path_with_namespace": "g/a"}, {"id": 2, "path_with_namespace": "g/b"}], "2": [{"id": 3, "path_with_namespace": "h/c"}]})
    connector = _gitlab(handler, all_member_projects=True)

    assert connector.scopes == []  # nothing is known until it has looked
    await connector.refresh_scopes()
    assert connector.scopes == ["1", "2", "3"]


async def test_gitlab_does_not_read_a_listed_repository_twice() -> None:
    handler = _projects_handler({"1": [{"id": 1, "path_with_namespace": "g/a"}, {"id": 2, "path_with_namespace": "g/b"}, {"id": 3, "path_with_namespace": "h/c"}]})
    connector = _gitlab(handler, ["G/A", "https://gitlab.com/h/c.git", "g/own-extra"], all_member_projects=True)

    await connector.refresh_scopes()

    assert connector.scopes == ["G/A", "https://gitlab.com/h/c.git", "g/own-extra", "2"]  # 1 and 3 are already listed


async def test_gitlab_stops_at_the_limit_and_keeps_the_old_list_when_the_source_fails() -> None:
    many = [{"id": i, "path_with_namespace": f"g/p{i}"} for i in range(1, 8)]
    connector = _gitlab(_projects_handler({"1": many}), all_member_projects=True, max_member_projects=3)
    await connector.refresh_scopes()
    assert connector.scopes == ["1", "2", "3"]

    connector._client._client._transport = httpx.MockTransport(lambda r: httpx.Response(500))  # type: ignore[attr-defined]
    try:
        await connector.refresh_scopes()
    except httpx.HTTPStatusError:
        pass
    assert connector.scopes == ["1", "2", "3"]


async def test_gitlab_without_the_switch_never_looks_for_repositories() -> None:
    calls: list[str] = []
    connector = _gitlab(lambda r: calls.append(r.url.path) or httpx.Response(200, json=[]), ["g/a"])

    await connector.refresh_scopes()

    assert calls == [] and connector.scopes == ["g/a"]


async def test_gitlab_check_reports_each_repository() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v4/user":
            return httpx.Response(200, json={"username": "admin"})
        if request.url.raw_path == b"/api/v4/projects/g%2Fa":
            return httpx.Response(200, json={"id": 1, "path_with_namespace": "g/a"})
        return httpx.Response(404, json={"message": "404 Project Not Found"})

    result = await _gitlab(handler, ["g/a", "g/missing"]).check()

    assert not result.ok
    assert [(s.scope, s.ok) for s in result.scopes] == [("g/a", True), ("g/missing", False)]
    assert "404 Project Not Found" in result.scopes[1].detail


async def test_gitlab_check_says_when_the_token_is_refused() -> None:
    result = await _gitlab(lambda r: httpx.Response(401, json={"message": "401 Unauthorized"}), ["g/a"]).check()

    assert not result.ok and "401" in result.detail and result.scopes == []


async def test_jira_check_runs_each_query_and_shows_jiras_own_complaint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/api/3/myself":
            return httpx.Response(200, json={"timeZone": "UTC"})
        if 'project = "NOPE"' in request.url.params.get("jql", ""):
            return httpx.Response(400, json={"errorMessages": ["The value 'NOPE' does not exist for the field 'project'."]})
        return httpx.Response(200, json={"issues": [], "isLast": True})

    connector = JiraConnector(JiraClient(BASE, "a@b.c", "t", transport=httpx.MockTransport(handler)), BASE, jql_queries=['project = "ENG" ORDER BY updated ASC', 'project = "NOPE" ORDER BY updated ASC'])

    result = await connector.check()

    assert not result.ok
    assert [s.ok for s in result.scopes] == [True, False]
    assert "does not exist for the field 'project'" in result.scopes[1].detail


async def test_jira_with_no_queries_has_nothing_to_read_and_check_says_so() -> None:
    connector = JiraConnector(JiraClient(BASE, "a@b.c", "t", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))), BASE)

    assert connector.scopes == []  # no hidden "read everything" default
    result = await connector.check()
    assert result.ok and result.scopes == []  # the sign-in works; there is simply nothing to read


async def test_confluence_check_tells_which_space_keys_work() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/wiki/rest/api/user/current":
            return httpx.Response(200, json={"displayName": "Admin"})
        if request.url.path == "/wiki/rest/api/space/ENG":
            return httpx.Response(200, json={"key": "ENG", "name": "Engineering"})
        return httpx.Response(404, json={"message": "No space with key : OPS"})

    connector = ConfluenceConnector(ConfluenceClient(BASE, "a@b.c", "t", transport=httpx.MockTransport(handler)), BASE, ["ENG", "OPS", "ENG"])

    assert connector.scopes == ["ENG", "OPS"]
    result = await connector.check()
    assert [(s.scope, s.ok) for s in result.scopes] == [("ENG", True), ("OPS", False)] and not result.ok
    assert result.scopes[0].detail == "Engineering" and "No space with key" in result.scopes[1].detail


async def test_figma_check_uses_the_cheap_metadata_call() -> None:
    depths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        depths.append(request.url.params.get("depth", ""))
        return httpx.Response(200, json={"name": "Design system"})

    result = await FigmaConnector(FigmaClient("https://api.figma.com", "t", transport=httpx.MockTransport(handler)), ["KEY"]).check()

    assert result.ok and depths == ["1"] and result.scopes[0].detail == "Design system"


async def test_confluence_check_says_when_the_sign_in_fails() -> None:
    connector = ConfluenceConnector(ConfluenceClient(BASE, "a@b.c", "t", transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"message": "bad"}))), BASE, ["ENG"])

    result = await connector.check()

    assert not result.ok and "cannot sign in" in result.detail and result.scopes == []


async def test_gitlab_check_only_opens_the_listed_repositories_not_every_discovered_one() -> None:
    opened: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v4/user":
            return httpx.Response(200, json={})
        if request.url.path == "/api/v4/projects":
            return httpx.Response(200, json=[{"id": i, "path_with_namespace": f"g/p{i}"} for i in range(1, 30)])
        opened.append(request.url.raw_path)
        return httpx.Response(200, json={"path_with_namespace": "g/own"})

    result = await _gitlab(handler, ["g/own"], all_member_projects=True).check()

    assert result.ok and opened == [b"/api/v4/projects/g%2Fown"] and "29 more found from membership" in result.detail
