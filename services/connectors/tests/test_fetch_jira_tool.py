from __future__ import annotations

import base64

import httpx

from tools.fetch_jira import run


async def test_the_tool_reads_an_issue_through_the_connector_and_sends_basic_auth() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        if request.url.path == "/rest/api/3/myself":
            return httpx.Response(200, json={"timeZone": "UTC"})
        seen["jql"] = request.url.params["jql"]
        issue = {"id": "10001", "key": "KAN-2", "fields": {"summary": "Second task", "status": {"name": "To Do"}, "issuetype": {"name": "Task"},
                 "project": {"key": "KAN"}, "updated": "2026-11-20T10:00:00.000+0000", "created": "2026-11-19T10:00:00.000+0000", "description": None,
                 "comment": {"comments": [], "total": 0}}, "changelog": {"histories": [], "total": 0}}
        return httpx.Response(200, json={"issues": [issue], "isLast": True})

    result = await run("https://sematic-test.atlassian.net", "me@example.test", "tok", "key = KAN-2", transport=httpx.MockTransport(handler))

    assert result["check"].ok and [d.source_object_id for d in result["fetched"].documents] == ["KAN-2"]
    assert seen["auth"] == "Basic " + base64.b64encode(b"me@example.test:tok").decode()  # the same header as the curl in the request
    assert seen["jql"].startswith("key = KAN-2")


async def test_a_refused_sign_in_stops_before_reading_anything() -> None:
    result = await run("https://x.atlassian.net", "me@example.test", "bad", "key = KAN-2", transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"message": "no"})))
    assert not result["check"].ok and result["fetched"] is None and "401" in result["check"].detail
