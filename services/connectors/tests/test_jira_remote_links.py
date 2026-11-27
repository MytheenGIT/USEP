from __future__ import annotations

import httpx
import pytest

from jira.client import JiraClient
from jira.connector import JiraConnector
from tests.test_jira_connector import BASE, _issue

LINKS = [{"id": 1, "object": {"url": "https://example.atlassian.net/wiki/spaces/ENG/pages/12345/Design", "title": "Design"}}]


def handler_for(links_status=200, links=LINKS):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/rest/api/3/search/jql":
            return httpx.Response(200, json={"issues": [_issue("ABC-1", "2026-11-26T10:00:00.000+0000")], "isLast": True})
        if request.url.path.endswith("/remotelink"):
            return httpx.Response(links_status, json=links if links_status == 200 else {})
        return httpx.Response(404, json={})

    return seen, handler


def connector(handler, **kw):
    client = JiraClient(BASE, "bot@example.com", "token", transport=httpx.MockTransport(handler))
    return JiraConnector(client, base_url=BASE, **kw)


@pytest.mark.asyncio
async def test_remote_links_are_stored_in_the_raw_payload_when_enabled():
    seen, h = handler_for()
    fetched = await connector(h, fetch_remote_links=True).fetch_scope("project = ABC", None)
    assert fetched.errors == [] and fetched.documents[0].raw_payload["remote_links"] == LINKS
    assert "/rest/api/3/issue/ABC-1/remotelink" in seen


@pytest.mark.asyncio
async def test_remote_links_are_not_requested_by_default():
    seen, h = handler_for()
    fetched = await connector(h).fetch_scope("project = ABC", None)
    assert "remote_links" not in fetched.documents[0].raw_payload and not any(p.endswith("/remotelink") for p in seen)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 404])
async def test_invisible_remote_links_are_empty_not_a_failure(status):
    _, h = handler_for(links_status=status)
    fetched = await connector(h, fetch_remote_links=True).fetch_scope("project = ABC", None)
    assert fetched.errors == [] and fetched.documents[0].raw_payload["remote_links"] == []


@pytest.mark.asyncio
async def test_other_remote_link_errors_fail_that_issue_so_the_cursor_retries_it():
    _, h = handler_for(links_status=500)
    fetched = await connector(h, fetch_remote_links=True).fetch_scope("project = ABC", None)
    assert fetched.documents == [] and [e.object_id for e in fetched.errors] == ["ABC-1"]
