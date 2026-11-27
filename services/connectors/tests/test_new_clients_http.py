"""HTTP-level tests of the GitHub, ServiceNow and ADO clients: auth header, path, query string and request body."""
from __future__ import annotations

import base64
import json

import httpx
import pytest

from ado.client import AdoClient
from github.client import GitHubClient
from servicenow.client import ServiceNowClient


def recorder(responses):
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        body = responses(request) if callable(responses) else responses
        return httpx.Response(200, json=body)

    return seen, httpx.MockTransport(handler)


# ------------------------------------------------------------------ GitHub
@pytest.mark.asyncio
async def test_github_sends_bearer_token_and_api_version_and_lists_all_states_newest_first():
    seen, t = recorder([{"number": 1}])
    c = GitHubClient("https://api.github.com", "tok", transport=t)
    assert await c.list_pull_requests("acme/pay", page=2, per_page=30) == [{"number": 1}]
    r = seen[0]
    assert r.headers["authorization"] == "Bearer tok" and r.headers["x-github-api-version"] == "2022-11-28"
    assert r.url.path == "/repos/acme/pay/pulls"
    assert dict(r.url.params) == {"state": "all", "sort": "updated", "direction": "desc", "page": "2", "per_page": "30"}


@pytest.mark.asyncio
async def test_github_enterprise_base_path_is_kept():
    seen, t = recorder({"full_name": "a/b"})
    await GitHubClient("https://ghe.example.com/api/v3", "t", transport=t).get_repo("a/b")
    assert seen[0].url.path == "/api/v3/repos/a/b"


@pytest.mark.asyncio
async def test_github_commits_and_reviews_paths():
    seen, t = recorder([])
    c = GitHubClient("https://api.github.com", "t", transport=t)
    await c.list_pr_commits("a/b", 7)
    await c.list_pr_reviews("a/b", 7)
    assert [r.url.path for r in seen] == ["/repos/a/b/pulls/7/commits", "/repos/a/b/pulls/7/reviews"]


# ------------------------------------------------------------------ ServiceNow
@pytest.mark.asyncio
async def test_servicenow_basic_auth_and_incremental_ordered_query():
    seen, t = recorder({"result": [{"sys_id": "1"}]})
    c = ServiceNowClient("https://x.service-now.com", "svc", "pw", transport=t)
    rows = await c.query_table("incident", "2026-05-01 10:00:00", offset=200, limit=100)
    assert rows == [{"sys_id": "1"}]
    r = seen[0]
    assert r.headers["authorization"] == "Basic " + base64.b64encode(b"svc:pw").decode()
    assert r.url.path == "/api/now/table/incident"
    q = dict(r.url.params)
    assert q["sysparm_query"] == "sys_updated_on>=2026-05-01 10:00:00^ORDERBYsys_updated_on^ORDERBYsys_id"
    assert q["sysparm_offset"] == "200" and q["sysparm_limit"] == "100" and q["sysparm_exclude_reference_link"] == "true"


@pytest.mark.asyncio
async def test_servicenow_first_run_has_no_time_filter_and_missing_result_is_empty():
    seen, t = recorder({})
    assert await ServiceNowClient("https://x.service-now.com", "u", "p", transport=t).query_table("change_request", None) == []
    assert dict(seen[0].url.params)["sysparm_query"] == "ORDERBYsys_updated_on^ORDERBYsys_id"


# ------------------------------------------------------------------ ADO
@pytest.mark.asyncio
async def test_ado_pat_is_basic_auth_with_empty_user_and_wiql_filters_by_changed_date():
    seen, t = recorder({"workItems": [{"id": 5}, {"id": 6}]})
    c = AdoClient("https://dev.azure.com/org", "pat123", transport=t)
    assert await c.wiql_ids("My Project", "2026-06-01T00:00:00.000Z") == [5, 6]
    r = seen[0]
    assert r.method == "POST" and r.headers["authorization"] == "Basic " + base64.b64encode(b":pat123").decode()
    assert r.url.raw_path.startswith(b"/org/My%20Project/_apis/wit/wiql")       # organization path kept, name encoded
    assert "api-version=7.1" in str(r.url)
    query = json.loads(r.content)["query"]
    assert "[System.TeamProject] = @project" in query and "[System.ChangedDate] >= '2026-06-01T00:00:00.000Z'" in query
    assert query.endswith("ORDER BY [System.ChangedDate] ASC")


@pytest.mark.asyncio
async def test_ado_work_item_batch_expands_relations_and_pull_request_filters():
    seen, t = recorder({"value": [{"id": 1}]})
    c = AdoClient("https://dev.azure.com/org", "p", transport=t)
    await c.work_items([1, 2])
    assert json.loads(seen[0].content) == {"ids": [1, 2], "$expand": "relations"}
    await c.list_pull_requests("P", "repo1", "completed", "2026-06-01T00:00:00Z", top=50, skip=100)
    q = dict(seen[1].url.params)
    assert q["searchCriteria.status"] == "completed" and q["searchCriteria.queryTimeRangeType"] == "closed"
    assert q["searchCriteria.minTime"] == "2026-06-01T00:00:00Z" and q["$top"] == "50" and q["$skip"] == "100"
    await c.list_pull_requests("P", "repo1", "active", "2026-06-01T00:00:00Z")
    assert "searchCriteria.minTime" not in dict(seen[2].url.params)        # active PRs have no closed time to filter on


@pytest.mark.asyncio
async def test_rate_limited_servicenow_call_is_retried_through_the_client():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, headers={"Retry-After": "0"}) if len(calls) == 1 else httpx.Response(200, json={"result": []})

    c = ServiceNowClient("https://x.service-now.com", "u", "p", transport=httpx.MockTransport(handler))
    await c.query_table("incident", None)
    assert len(calls) == 2
