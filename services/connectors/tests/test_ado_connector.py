from __future__ import annotations

import httpx

from ado.client import AdoClient
from ado.connector import AdoConnector

BASE = "https://dev.azure.com/acme"


def _connector(handler, projects=("checkout",), **kwargs) -> AdoConnector:
    client = AdoClient(BASE, "pat", transport=httpx.MockTransport(handler))
    return AdoConnector(client, base_url=BASE, project_names=list(projects), **kwargs)


def _work_item(item_id: int, title: str, changed: str) -> dict:
    return {"id": item_id, "fields": {"System.Title": title, "System.Description": f"{title} body", "System.ChangedDate": changed}}


def _happy_handler(request: httpx.Request) -> httpx.Response:
    path, params = request.url.path, dict(request.url.params)
    assert request.headers["authorization"].startswith("Basic ")
    if path.endswith("/_apis/projects"):
        return httpx.Response(200, json={"value": [{"name": "checkout"}]})
    if path.endswith("/checkout/_apis/wit/wiql"):
        return httpx.Response(200, json={"workItems": [{"id": 101}, {"id": 102}]})
    if path.endswith("/checkout/_apis/wit/workitems"):
        ids = {int(i) for i in params["ids"].split(",")}
        assert ids == {101, 102}
        return httpx.Response(200, json={"value": [
            _work_item(101, "Fix retry bug", "2026-11-01T00:00:00Z"),
            _work_item(102, "Add logging", "2026-11-02T00:00:00Z"),
        ]})
    if path.endswith("/checkout/_apis/git/repositories"):
        return httpx.Response(200, json={"value": [{"id": "r1", "name": "checkout", "webUrl": f"{BASE}/checkout/_git/checkout", "defaultBranch": "refs/heads/main"}]})
    if path.endswith("/checkout/_apis/git/repositories/r1/pullrequests"):
        return httpx.Response(200, json={"value": [{"pullRequestId": 5, "title": "Fix retry", "description": "see PAY-12", "lastMergeCommit": {"commitId": "abc123"}}]})
    return httpx.Response(404)


async def test_fetch_scope_returns_work_items_repositories_and_pull_requests() -> None:
    result = await _connector(_happy_handler).fetch_scope("checkout", None)

    assert not result.errors
    by_type = {(d.source_type, d.source_object_id): d for d in result.documents}
    assert set(by_type) == {("work_item", "101"), ("work_item", "102"), ("repository", "r1"), ("pull_request", "5")}
    work_item = by_type[("work_item", "101")]
    assert work_item.title == "Fix retry bug" and work_item.source_version == "2026-11-01T00:00:00Z"
    repo = by_type[("repository", "r1")]
    assert repo.title == "checkout" and repo.source_url == f"{BASE}/checkout/_git/checkout"
    pr = by_type[("pull_request", "5")]
    assert pr.title == "Fix retry" and pr.content == "see PAY-12" and pr.source_version == "abc123"


async def test_one_bad_work_item_batch_is_an_object_error_not_a_failed_scope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/checkout/_apis/wit/workitems"):
            return httpx.Response(500)
        return _happy_handler(request)

    result = await _connector(handler).fetch_scope("checkout", None)

    assert [d.source_object_id for d in result.documents if d.source_type == "work_item"] == []
    assert any(e.scope == "checkout" and "work-items" in (e.object_id or "") for e in result.errors)
    # repositories and pull requests are unaffected by the work item failure
    assert any(d.source_type == "repository" for d in result.documents)


async def test_check_reports_missing_projects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/_apis/projects"):
            return httpx.Response(200, json={"value": [{"name": "checkout"}]})
        return httpx.Response(404)

    ok = await _connector(handler, projects=["checkout"]).check()
    assert ok.ok

    missing = await _connector(handler, projects=["checkout", "ghost"]).check()
    assert not missing.ok and "ghost" in missing.detail
