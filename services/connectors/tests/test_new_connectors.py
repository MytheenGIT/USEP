from __future__ import annotations

import asyncio

from ado.connector import AdoConnector
from common.connector_base import next_cursor
from github.connector import GitHubConnector, pr_state
from servicenow.connector import ServiceNowConnector


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ GitHub
class FakeGitHub:
    def __init__(self, prs):
        self.prs, self.calls = prs, 0

    async def get_repo(self, repo):
        return {"name": "pay", "full_name": repo, "updated_at": "2026-04-01T00:00:00Z", "private": True,
                "html_url": f"https://github.com/{repo}"}

    async def list_pull_requests(self, repo, page=1, per_page=50):
        self.calls += 1
        return self.prs[(page - 1) * per_page: page * per_page]

    async def list_pr_commits(self, repo, number):
        return [{"sha": "abc", "author": {"login": "u"}, "commit": {"message": "ABC-1 x", "author": {"date": "2026-01-01T00:00:00Z"}}}]

    async def list_pr_reviews(self, repo, number):
        return [{"id": 1, "user": {"login": "r"}, "state": "APPROVED", "submitted_at": "2026-01-02T00:00:00Z"}]


def pr(n, updated, **kw):
    return {"number": n, "title": f"PR {n}", "state": "open", "updated_at": updated, "labels": [],
            "base": {"repo": {"private": True}}, **kw}


def test_github_pr_state():
    assert pr_state(pr(1, "x", merged_at="t", state="closed")) == "merged"
    assert pr_state(pr(1, "x", state="closed")) == "closed" and pr_state(pr(1, "x")) == "opened"


def test_github_scope_is_a_repo_and_incremental_fetch_stops_at_the_cursor():
    prs = [pr(3, "2026-04-03T00:00:00Z"), pr(2, "2026-04-02T00:00:00Z"), pr(1, "2026-04-01T00:00:00Z")]
    c = GitHubConnector(FakeGitHub(prs), ["acme/pay"], page_size=2)
    assert c.scopes == ["acme/pay"]
    first = run(c.fetch_scope("acme/pay", None))
    assert sorted(d.source_object_id for d in first.documents) == [
        "github:acme/pay", "github:acme/pay#1", "github:acme/pay#2", "github:acme/pay#3"]
    cursor = next_cursor(None, first)
    assert cursor == "2026-04-03T00:00:00.000Z"
    pr_doc = next(d for d in first.documents if d.source_object_id.endswith("#1"))
    assert pr_doc.commits[0].message == "ABC-1 x" and pr_doc.reviews[0].state == "APPROVED"
    assert pr_doc.scope == "acme/pay" and pr_doc.source_version == "2026-04-01T00:00:00.000Z"
    assert set(pr_doc.raw_payload) == {"pull_request", "commits", "reviews"}       # sub-resources kept for re-normalizing
    second = run(GitHubConnector(FakeGitHub(prs), ["acme/pay"], page_size=2).fetch_scope("acme/pay", cursor))
    assert [d.source_object_id for d in second.documents] == ["github:acme/pay#3"]  # repo unchanged since the cursor


def test_github_one_bad_pull_request_is_an_object_error_not_a_failed_scope():
    class Flaky(FakeGitHub):
        async def list_pr_commits(self, repo, number):
            if number == 2:
                raise RuntimeError("boom")
            return await super().list_pr_commits(repo, number)

    fetched = run(GitHubConnector(Flaky([pr(3, "2026-04-03T00:00:00Z"), pr(2, "2026-04-02T00:00:00Z")]), ["acme/pay"]).fetch_scope("acme/pay", None))
    assert [e.object_id for e in fetched.errors] == ["github:acme/pay#2"]
    assert fetched.errors[0].source_version == "2026-04-02T00:00:00.000Z"          # the cursor will stop here
    assert any(d.source_object_id.endswith("#3") for d in fetched.documents)


# ------------------------------------------------------------------ ServiceNow
class FakeSN:
    def __init__(self, rows):
        self.rows, self.since = rows, []

    async def query_table(self, table, since, offset=0, limit=100):
        self.since.append(since)
        rows = [r for r in self.rows.get(table, []) if not since or r["sys_updated_on"] >= since]
        return rows[offset: offset + limit]


def test_servicenow_scopes_are_tables_and_cursor_is_converted_for_the_query():
    rows = {"incident": [{"sys_id": str(i), "number": f"INC{i}", "sys_updated_on": f"2026-05-01 10:00:0{i}", "state": "1",
                          "assignment_group": {"value": "g1"}} for i in range(3)],
            "change_request": [{"sys_id": "9", "number": "CHG9", "sys_updated_on": "2026-05-02 00:00:00", "state": "-5"}]}
    fake = FakeSN(rows)
    c = ServiceNowConnector(fake, "https://x.service-now.com", page_size=2)
    assert c.scopes == ["incident", "change_request"]
    inc = run(c.fetch_scope("incident", None))
    assert [d.number for d in inc.documents] == ["INC0", "INC1", "INC2"]            # paged: 2 + 1
    assert inc.documents[0].assignment_group == "g1" and inc.documents[0].source_url.endswith("sys_id=0")
    assert inc.documents[0].source_version == "2026-05-01T10:00:00.000Z"
    cursor = next_cursor(None, inc)
    assert cursor == "2026-05-01T10:00:02.000Z"
    again = run(c.fetch_scope("incident", cursor))
    assert fake.since[-1] == "2026-05-01 10:00:02"                                  # the instance's own format
    assert [d.number for d in again.documents] == ["INC2"]                          # boundary record re-read (idempotent)


# ------------------------------------------------------------------ ADO
class FakeAdo:
    async def wiql_ids(self, project, since):
        return list(range(1, 251))                   # forces two batches

    async def work_items(self, ids):
        assert len(ids) <= 200
        return [{"id": i, "fields": {"System.TeamProject": "Pay", "System.WorkItemType": "Bug", "System.Title": "t",
                                     "System.State": "New", "System.Tags": "a; b",
                                     "System.ChangedDate": f"2026-06-01T00:00:{i % 60:02d}Z"}} for i in ids]

    async def list_repositories(self, project):
        return [{"id": "r1", "name": "svc"}]

    async def list_pull_requests(self, project, repo_id, status, min_time=None, top=100, skip=0):
        if status != "completed" or skip:
            return []
        return [{"pullRequestId": 7, "title": "x", "status": "completed", "closedDate": "2026-07-01T00:00:00Z",
                 "repository": {"name": "svc", "project": {"name": "Pay"}, "webUrl": "https://dev.azure.com/o/Pay/_git/svc"}}]


def test_ado_scope_is_a_project_and_batches_work_items():
    c = AdoConnector(FakeAdo(), "https://dev.azure.com/o", ["Pay"])
    assert c.scopes == ["Pay"]
    fetched = run(c.fetch_scope("Pay", None))
    wis = [d for d in fetched.documents if d.source_type == "work_item"]
    assert len(wis) == 250 and wis[0].labels == ["a", "b"] and wis[0].source_object_id == "Pay#1"
    assert wis[0].scope == "Pay" and wis[0].source_version.endswith("Z")
    (p,) = [d for d in fetched.documents if d.source_type == "pull_request"]
    assert p.state == "merged" and p.source_object_id == "ado:Pay/svc!7" and p.source_version == "2026-07-01T00:00:00.000Z"
    assert fetched.errors == [] and next_cursor(None, fetched) == "2026-07-01T00:00:00.000Z"
