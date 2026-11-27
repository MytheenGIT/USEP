"""GitHub connector: one scope per repository (owner/name). Repositories (-> Service) and pull requests (-> Change),
with commits and reviews. A failing pull request is reported as an object error, not a failed scope."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from common.connector_base import ObjectError, ScopeFetch
from common.source_document import SourceType
from common.timeutil import to_utc_iso
from github.client import GitHubClient
from github.models import GitHubCommit, GitHubDocument, GitHubReview


def pr_state(pr: dict[str, Any]) -> str:
    if pr.get("merged_at"):
        return "merged"
    return "opened" if pr.get("state") == "open" else "closed"


class GitHubConnector:
    source = SourceType.GITHUB

    def __init__(self, client: GitHubClient, repos: list[str], web_url: str = "https://github.com",
                 page_size: int = 50) -> None:
        self._client, self._repos, self._web, self._page_size = client, repos, web_url.rstrip("/"), page_size

    @property
    def scopes(self) -> list[str]:
        return [r for r in self._repos if r.strip()]

    def _repo_doc(self, repo: str, data: dict[str, Any]) -> GitHubDocument:
        version = to_utc_iso(data.get("updated_at"))
        return GitHubDocument(
            scope=repo, source_version=version, acl={"repo": repo, "private": data.get("private")},
            source=self.source, source_type="repository", source_object_id=f"github:{repo}",
            source_url=data.get("html_url", f"{self._web}/{repo}"), retrieved_at=datetime.now(UTC), raw_payload=data,
            title=data.get("name", repo), content=data.get("description") or "",
            metadata={"updated_at": version}, repo=repo, private=data.get("private"))

    async def _pr_doc(self, repo: str, pr: dict[str, Any]) -> GitHubDocument:
        n = pr["number"]
        version = to_utc_iso(pr.get("updated_at"))
        commits_raw, reviews_raw = await asyncio.gather(self._client.list_pr_commits(repo, n),
                                                        self._client.list_pr_reviews(repo, n))
        commits = [GitHubCommit(sha=c["sha"], author=(c.get("author") or {}).get("login"),
                                authored_at=((c.get("commit") or {}).get("author") or {}).get("date"),
                                message=(c.get("commit") or {}).get("message", ""), raw=c) for c in commits_raw]
        reviews = [GitHubReview(review_id=str(r["id"]), reviewer=(r.get("user") or {}).get("login"),
                                state=r.get("state", ""), submitted_at=r.get("submitted_at"), raw=r) for r in reviews_raw]
        return GitHubDocument(
            scope=repo, source_version=version,
            acl={"repo": repo, "private": ((pr.get("base") or {}).get("repo") or {}).get("private")},
            source=self.source, source_type="pull_request", source_object_id=f"github:{repo}#{n}",
            source_url=pr.get("html_url", f"{self._web}/{repo}/pull/{n}"), retrieved_at=datetime.now(UTC),
            raw_payload={"pull_request": pr, "commits": commits_raw, "reviews": reviews_raw},
            title=pr.get("title", ""), content=pr.get("body") or "",
            metadata={"updated_at": version, "state": pr_state(pr)}, repo=repo, number=n,
            state=pr_state(pr), labels=[lb.get("name", "") for lb in pr.get("labels", [])],
            private=((pr.get("base") or {}).get("repo") or {}).get("private"), commits=commits, reviews=reviews)

    async def fetch_scope(self, scope: str, cursor: str | None) -> ScopeFetch:
        docs: list[GitHubDocument] = []
        errors: list[ObjectError] = []
        data = await self._client.get_repo(scope)                      # an exception here fails this scope only
        repo_version = to_utc_iso(data.get("updated_at")) or ""
        if not cursor or repo_version >= cursor:                       # unchanged repositories are not re-sent
            docs.append(self._repo_doc(scope, data))
        page = 1
        while True:
            prs = await self._client.list_pull_requests(scope, page=page, per_page=self._page_size)
            fresh = [p for p in prs if not cursor or (to_utc_iso(p.get("updated_at")) or "") >= cursor]
            results = await asyncio.gather(*(self._pr_doc(scope, p) for p in fresh), return_exceptions=True)
            for pr, res in zip(fresh, results):
                if isinstance(res, BaseException):
                    errors.append(ObjectError(scope=scope, object_id=f"github:{scope}#{pr.get('number')}",
                                              source_version=to_utc_iso(pr.get("updated_at")), error=str(res)))
                else:
                    docs.append(res)
            if len(prs) < self._page_size or len(fresh) < len(prs):    # last page, or reached what we already have
                return ScopeFetch(documents=docs, errors=errors)
            page += 1
