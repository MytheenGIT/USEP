from __future__ import annotations

import httpx

from confluence.client import ConfluenceClient
from confluence.connector import ConfluenceConnector, scope_filter

BASE = "https://example.atlassian.net"


def _page(page_id: str, when: str) -> dict:
    return {
        "id": page_id,
        "title": f"Page {page_id}",
        "version": {"number": 3, "when": when},
        "space": {"key": "ENG"},
        "body": {"storage": {"value": "<h1>Intro</h1>"}},
        "_links": {"webui": f"/spaces/ENG/pages/{page_id}"},
        "restrictions": {"read": {"restrictions": {"group": {"results": [{"name": "eng-team"}]}}}},
    }


def test_scope_filter() -> None:
    assert scope_filter("ENG") == ('space = "ENG"', "ENG")
    assert scope_filter(f"{BASE}/wiki/spaces/ENG/overview") == ('space = "ENG"', "ENG")
    assert scope_filter(f"{BASE}/wiki/spaces/ENG/pages/123/Title") == ("(id = 123 OR ancestor = 123)", None)


async def test_incremental_cql_next_links_and_version_history() -> None:
    cqls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/wiki/rest/api/content/search":
            if "cursor" in request.url.params:
                return httpx.Response(200, json={"results": [_page("2", "2026-11-26T12:00:00.000Z")], "_links": {}})
            cqls.append(request.url.params["cql"])
            return httpx.Response(
                200,
                json={
                    "results": [_page("1", "2026-11-25T12:00:00.000Z")],  # in the look-back day, older than cursor
                    "_links": {"next": "/rest/api/content/search?cursor=abc"},
                },
            )
        if path == "/wiki/rest/api/content/2/version":
            return httpx.Response(200, json={"results": [{"number": 3}, {"number": 2}, {"number": 1}], "_links": {}})
        if path == "/wiki/rest/api/content/2/child/page":
            return httpx.Response(200, json={"results": [{"id": "9", "title": "Child"}], "_links": {}})
        raise AssertionError(f"unexpected {path}")

    client = ConfluenceClient(BASE, "bot@example.com", "token", transport=httpx.MockTransport(handler))
    result = await ConfluenceConnector(client, BASE, ["ENG"]).fetch_scope("ENG", "2026-11-26T10:00:00.000Z")

    assert cqls == ['space = "ENG" AND type = page AND lastmodified >= "2026-11-25" ORDER BY lastmodified ASC']
    assert [d.page_id for d in result.documents] == ["2"]
    doc = result.documents[0]
    assert [v.number for v in doc.version_history] == [3, 2, 1]
    assert doc.children[0].page_id == "9"
    assert doc.source_url == f"{BASE}/wiki/spaces/ENG/pages/2"
    assert doc.acl == {"space_key": "ENG", "read_restriction_groups": ["eng-team"]}
