from __future__ import annotations

import httpx

from common.binary_store import LocalBinaryStore
from jira.adf import adf_to_markdown
from jira.client import JiraClient
from jira.connector import JiraConnector, split_order_by

BASE = "https://example.atlassian.net"


def _issue(key: str, updated: str, **fields) -> dict:
    return {
        "key": key,
        "fields": {
            "summary": f"Story {key}",
            "updated": updated,
            "status": {"name": "To Do"},
            "project": {"key": "ABC"},
            "labels": ["backend"],
            "comment": {"comments": [], "total": 0},
            "attachment": [],
            **fields,
        },
        "changelog": {"histories": [], "total": 0},
    }


def _connector(handler, tmp_path=None, **kwargs) -> JiraConnector:
    client = JiraClient(BASE, "bot@example.com", "token", transport=httpx.MockTransport(handler))
    store = LocalBinaryStore(str(tmp_path)) if tmp_path else None
    return JiraConnector(client, base_url=BASE, binary_store=store, **kwargs)


def test_split_order_by() -> None:
    assert split_order_by("project = ABC ORDER BY updated ASC") == ("project = ABC", "ORDER BY updated ASC")
    assert split_order_by("order by updated asc") == ("", "order by updated asc")
    assert split_order_by("project = ABC") == ("project = ABC", "")


async def test_build_jql_uses_user_time_zone_and_keeps_order_by_outside() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/api/3/myself"
        return httpx.Response(200, json={"timeZone": "Asia/Kolkata"})

    connector = _connector(handler)
    assert await connector.build_jql("order by updated asc", None) == "order by updated asc"
    jql = await connector.build_jql("project = ABC ORDER BY updated ASC", "2026-11-26T10:00:00.000Z")
    assert jql == '(project = ABC) AND updated >= "2026-11-26 15:30" ORDER BY updated ASC'
    assert await connector.build_jql("order by created desc", "2026-11-26T10:00:00.000Z") == 'updated >= "2026-11-26 15:30" order by created desc'


async def test_fetch_pages_truncated_comments_and_drops_issues_older_than_cursor() -> None:
    issues = [
        _issue("ABC-1", "2026-11-26T09:59:30.000+0000"),  # same JQL minute but before the cursor
        _issue("ABC-2", "2026-11-26T10:30:00.000+0000", comment={"comments": [{"id": "1", "body": "a"}], "total": 2}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/rest/api/3/myself":
            return httpx.Response(200, json={"timeZone": "UTC"})
        if path == "/rest/api/3/search/jql":
            assert "updated" in request.url.params["fields"].split(",")
            return httpx.Response(200, json={"issues": issues, "isLast": True})
        if path == "/rest/api/3/issue/ABC-2/comment":
            return httpx.Response(200, json={"comments": [{"id": "1", "body": "a"}, {"id": "2", "body": "b"}], "total": 2})
        raise AssertionError(f"unexpected {path}")

    result = await _connector(handler).fetch_scope("project = ABC", "2026-11-26T10:00:00.000Z")

    assert [d.source_object_id for d in result.documents] == ["ABC-2"]
    doc = result.documents[0]
    assert [c.comment_id for c in doc.comments] == ["1", "2"]
    assert doc.source_version == "2026-11-26T10:30:00.000Z"
    assert doc.acl == {"project_key": "ABC", "security_level": None}
    assert doc.labels == ["backend"] and doc.content_hash
    assert result.errors == []


async def test_attachments_downloaded_once_and_oversize_skipped(tmp_path) -> None:
    downloads: list[str] = []
    attachments = [
        {"id": "10", "filename": "spec.txt", "size": 5, "content": f"{BASE}/rest/api/3/attachment/content/10"},
        {"id": "11", "filename": "big.zip", "size": 5_000_000, "content": f"{BASE}/rest/api/3/attachment/content/11"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/api/3/search/jql":
            return httpx.Response(200, json={"issues": [_issue("ABC-3", "2026-11-26T10:00:00.000+0000", attachment=attachments)], "isLast": True})
        downloads.append(request.url.path)
        return httpx.Response(200, content=b"hello")

    connector = _connector(handler, tmp_path, attachment_max_bytes=1024)
    first = (await connector.fetch_scope("project = ABC", None)).documents[0]
    await connector.fetch_scope("project = ABC", None)

    small, big = first.attachments
    assert small.stored_ref and small.content_hash and small.skipped_reason is None
    assert big.skipped_reason == "Q-SIZE" and big.stored_ref is None
    assert downloads == ["/rest/api/3/attachment/content/10"]


async def test_one_bad_issue_becomes_object_error() -> None:
    issues = [
        _issue("ABC-4", "2026-11-26T10:00:00.000+0000", comment={"comments": [], "total": 5}),
        _issue("ABC-5", "2026-11-26T11:00:00.000+0000"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/api/3/search/jql":
            return httpx.Response(200, json={"issues": issues, "isLast": True})
        return httpx.Response(500)

    result = await _connector(handler).fetch_scope("project = ABC", None)

    assert [d.source_object_id for d in result.documents] == ["ABC-5"]
    assert result.errors[0].object_id == "ABC-4"
    assert result.errors[0].source_version == "2026-11-26T10:00:00.000Z"


def test_adf_to_markdown_keeps_structure() -> None:
    doc = {
        "type": "doc",
        "content": [
            {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Acceptance criteria"}]},
            {
                "type": "bulletList",
                "content": [
                    {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Given a user"}]}]},
                    {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "id", "marks": [{"type": "code"}]}]}]},
                ],
            },
            {"type": "codeBlock", "attrs": {"language": "python"}, "content": [{"type": "text", "text": "print(1)"}]},
        ],
    }
    assert adf_to_markdown(doc) == "## Acceptance criteria\n\n- Given a user\n- `id`\n\n```python\nprint(1)\n```"
