from __future__ import annotations

import httpx

from gitlab.client import GitLabClient
from gitlab.connector import GitLabConnector, project_ref_from_scope


def test_project_ref_from_scope() -> None:
    assert project_ref_from_scope("42") == "42"
    assert project_ref_from_scope("group/sub/proj") == "group/sub/proj"
    assert project_ref_from_scope("https://gitlab.com/group/proj.git") == "group/proj"
    assert project_ref_from_scope("https://gitlab.com/group/proj/-/merge_requests/3") == "group/proj"


def _mr(iid: int, updated: str) -> dict:
    return {"iid": iid, "title": f"MR {iid}", "updated_at": updated, "state": "opened", "web_url": f"https://gitlab.com/g/p/-/merge_requests/{iid}"}


async def test_pages_through_mrs_and_commits_and_isolates_failures() -> None:
    seen_params: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path, params = request.url.path, dict(request.url.params)
        if request.url.raw_path == b"/api/v4/projects/g%2Fp":
            return httpx.Response(200, json={"id": 7, "path_with_namespace": "g/p", "visibility": "private"})
        if path == "/api/v4/projects/7/merge_requests":
            seen_params.append(params)
            if params["page"] == "1":
                return httpx.Response(200, json=[_mr(1, "2026-11-01T00:00:00Z")], headers={"x-next-page": "2"})
            return httpx.Response(200, json=[_mr(2, "2026-11-02T00:00:00Z"), _mr(3, "2026-11-03T00:00:00Z")], headers={"x-next-page": ""})
        if path.endswith("/merge_requests/2/commits"):
            return httpx.Response(500)
        if path.endswith("/commits"):
            if params["page"] == "1":
                return httpx.Response(200, json=[{"id": "a1", "message": "one"}], headers={"x-next-page": "2"})
            return httpx.Response(200, json=[{"id": "b2", "message": "two"}])
        if path.endswith("/approvals"):
            return httpx.Response(200, json={"approved_by": [{"user": {"username": "rev"}}]})
        return httpx.Response(200, json=[])

    client = GitLabClient("https://gitlab.com", "token", transport=httpx.MockTransport(handler))
    result = await GitLabConnector(client, ["https://gitlab.com/g/p"]).fetch_scope("https://gitlab.com/g/p", "2026-10-01T00:00:00.000Z")

    assert seen_params[0]["updated_after"] == "2026-10-01T00:00:00.000Z"
    assert [d.source_object_id for d in result.documents] == ["7!1", "7!3"]
    assert [c.sha for c in result.documents[0].commits] == ["a1", "b2"]
    assert set(result.documents[0].raw_payload) == {"merge_request", "commits", "notes", "approvals", "diffs"}
    assert result.documents[0].acl["visibility"] == "private"
    assert len(result.errors) == 1 and result.errors[0].object_id == "7!2"
    assert result.errors[0].source_version == "2026-11-02T00:00:00.000Z"
