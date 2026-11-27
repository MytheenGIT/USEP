from __future__ import annotations

import httpx

from github.client import GitHubClient
from github.connector import GitHubConnector, repo_from_scope

BASE = "https://api.github.com"


def _connector(handler, repos=None, **kwargs) -> GitHubConnector:
    return GitHubConnector(GitHubClient(BASE, "tok", transport=httpx.MockTransport(handler)), repos or [], **kwargs)


def _pr(number: int, updated: str, **extra) -> dict:
    return {"number": number, "title": f"PR {number}", "state": "closed", "updated_at": updated, "html_url": f"https://github.com/acme/checkout/pull/{number}",
            "body": "PAY-12 retry", "merged_at": updated, "base": {"ref": "main"}, "head": {"ref": f"feature-{number}"}, **extra}


def test_scopes_accept_names_links_and_ssh_links_without_repeats() -> None:
    assert repo_from_scope("acme/checkout") == "acme/checkout"
    assert repo_from_scope("https://github.com/acme/checkout.git") == "acme/checkout"
    assert repo_from_scope("git@github.com:acme/checkout.git") == "acme/checkout"
    connector = _connector(lambda r: httpx.Response(200, json=[]), ["acme/checkout", "https://github.com/acme/checkout", "git@github.com:acme/billing.git"])
    assert connector.scopes == ["acme/checkout", "acme/billing"]


def _repo_handler(pulls_pages: dict[str, list[dict]], failing_pr: int | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        path, params = request.url.path, dict(request.url.params)
        assert request.headers["authorization"] == "Bearer tok"
        if path == "/repos/acme/checkout":
            return httpx.Response(200, json={"full_name": "acme/checkout", "private": True, "visibility": "private"})
        if path == "/repos/acme/checkout/pulls":
            page = params.get("page", "1")
            nxt = str(int(page) + 1)
            headers = {"Link": f'<{BASE}/repos/acme/checkout/pulls?page={nxt}>; rel="next"'} if nxt in pulls_pages else {}
            return httpx.Response(200, json=pulls_pages[page], headers=headers)
        for number in (7, 8, 9):
            if path.startswith(f"/repos/acme/checkout/pulls/{number}/") or path == f"/repos/acme/checkout/issues/{number}/comments":
                if failing_pr == number:
                    return httpx.Response(500)
                if path.endswith("/commits"):
                    return httpx.Response(200, json=[{"sha": "abc", "commit": {"message": "PAY-12 retry", "author": {"name": "Dev", "date": "2026-11-01T00:00:00Z"}}, "html_url": "u"}])
                if path.endswith("/files"):
                    return httpx.Response(200, json=[{"filename": "pay.py", "status": "modified", "additions": 3, "deletions": 1, "patch": "@@ -1 +1 @@"}])
                if path.endswith("/reviews"):
                    return httpx.Response(200, json=[{"user": {"login": "lead"}, "state": "APPROVED", "body": "ok", "submitted_at": "2026-11-02T00:00:00Z"}])
                if path.endswith("/issues/%d/comments" % number):
                    return httpx.Response(200, json=[{"id": 1, "user": {"login": "dev"}, "body": "talk", "created_at": "2026-11-01T00:00:00Z"}])
                if path.endswith("/comments"):
                    return httpx.Response(200, json=[{"id": 2, "user": {"login": "lead"}, "body": "nit", "created_at": "2026-11-01T00:00:00Z", "path": "pay.py"}])
        return httpx.Response(404)

    return handler


async def test_a_pull_request_is_read_with_everything_around_it() -> None:
    connector = _connector(_repo_handler({"1": [_pr(7, "2026-11-05T10:00:00Z")]}), ["acme/checkout"])

    result = await connector.fetch_scope("acme/checkout", None)

    [doc] = result.documents
    assert (doc.source_object_id, doc.state, doc.base_branch, doc.head_branch, doc.source_version) == ("acme/checkout#7", "merged", "main", "feature-7", "2026-11-05T10:00:00.000Z")
    assert [c.sha for c in doc.commits] == ["abc"] and doc.commits[0].author == "Dev"
    assert sorted((c.kind, c.path) for c in doc.comments) == [("conversation", None), ("review_comment", "pay.py")]
    assert (doc.reviews[0].reviewer, doc.reviews[0].state) == ("lead", "APPROVED")
    assert (doc.files[0].filename, doc.files[0].additions, doc.files[0].patch) == ("pay.py", 3, "@@ -1 +1 @@")
    assert doc.acl == {"repository": "acme/checkout", "private": True, "visibility": "private"}
    assert set(doc.raw_payload) == {"pull_request", "commits", "comments", "review_comments", "reviews", "files"}
    assert not result.errors


async def test_it_pages_newest_first_and_stops_at_the_cursor() -> None:
    pages = {"1": [_pr(9, "2026-11-09T00:00:00Z"), _pr(8, "2026-11-08T00:00:00Z")], "2": [_pr(7, "2026-11-01T00:00:00Z")]}
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pulls"):
            requested.append(request.url.params.get("page", "1"))
        return _repo_handler(pages)(request)

    result = await _connector(handler, ["acme/checkout"]).fetch_scope("acme/checkout", "2026-11-05T00:00:00.000Z")

    assert [d.pr_number for d in result.documents] == ["8", "9"]  # oldest change first, older than the cursor left out
    assert requested == ["1", "2"]  # page 2 was needed to see that 7 is older


async def test_one_bad_pull_request_is_an_object_error_not_a_failed_scope() -> None:
    pages = {"1": [_pr(8, "2026-11-08T00:00:00Z"), _pr(7, "2026-11-07T00:00:00Z")]}
    result = await _connector(_repo_handler(pages, failing_pr=8), ["acme/checkout"]).fetch_scope("acme/checkout", None)

    assert [d.pr_number for d in result.documents] == ["7"]
    assert [(e.object_id, e.source_version) for e in result.errors] == [("acme/checkout#8", "2026-11-08T00:00:00.000Z")]


async def test_it_finds_every_member_repository_across_pages_and_skips_archived_and_listed_ones() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/user/repos" and "organization_member" in request.url.params["affiliation"]
        if request.url.params.get("page") == "2":  # GitHub's next link carries every parameter of the first request
            return httpx.Response(200, json=[{"full_name": "acme/c"}])
        link = f'<{BASE}/user/repos?affiliation=owner,collaborator,organization_member&page=2>; rel="next"'
        return httpx.Response(200, json=[{"full_name": "acme/a"}, {"full_name": "acme/old", "archived": True}, {"full_name": "Acme/B"}], headers={"Link": link})

    connector = _connector(handler, ["acme/b"], all_member_projects=True)
    assert connector.scopes == ["acme/b"]
    await connector.refresh_scopes()
    assert connector.scopes == ["acme/b", "acme/a", "acme/c"]


async def test_check_reports_the_token_and_each_listed_repository() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/user":
            return httpx.Response(200, json={"login": "admin"})
        if request.url.path == "/repos/acme/checkout":
            return httpx.Response(200, json={"full_name": "acme/checkout"})
        return httpx.Response(404, json={"message": "Not Found"})

    result = await _connector(handler, ["acme/checkout", "acme/missing"]).check()
    assert not result.ok and [(s.scope, s.ok) for s in result.scopes] == [("acme/checkout", True), ("acme/missing", False)]
    assert "Not Found" in result.scopes[1].detail

    refused = await _connector(lambda r: httpx.Response(401, json={"message": "Bad credentials"}), ["acme/checkout"]).check()
    assert not refused.ok and "Bad credentials" in refused.detail and refused.scopes == []
