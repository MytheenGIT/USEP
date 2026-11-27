"""GitHub connector: one scope per repository, reading its pull requests.

The admin can list repositories (``owner/repo``, a link, or an SSH link), ask for every repository the token's user can
reach, or both. Pull requests carry their commits, comments, review comments, reviews and changed files, all paged to
the end, with the raw responses kept in ``raw_payload`` so the raw landing holds everything needed to re-normalize later.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog

from common.client_base import error_detail
from common.connector_base import ObjectError, ScopeCheck, ScopeFetch, SourceCheck
from common.scopes import repo_path_from_link
from common.source_document import SourceType
from common.timeutil import to_utc_iso
from github.client import GitHubClient
from github.models import GitHubComment, GitHubCommit, GitHubDocument, GitHubFile, GitHubReview

logger = structlog.get_logger(__name__)


def repo_from_scope(scope: str) -> str:
    """``owner/repo`` from ``owner/repo``, an https link or an SSH link."""
    return repo_path_from_link(scope)


class GitHubConnector:
    source = SourceType.GITHUB

    def __init__(
        self,
        client: GitHubClient,
        repositories: list[str],
        page_size: int = 50,
        pr_concurrency: int = 4,
        all_member_projects: bool = False,
        max_member_projects: int = 500,
    ) -> None:
        self._client = client
        self._explicit = list(dict.fromkeys(repo_from_scope(r) for r in repositories if str(r).strip()))
        self._page_size = page_size
        self._pr_concurrency = max(1, pr_concurrency)
        self._all_member = all_member_projects
        self._max_member = max_member_projects
        self._discovered: list[str] = []

    @property
    def scopes(self) -> list[str]:
        return [*self._explicit, *self._discovered]

    async def refresh_scopes(self) -> None:
        """Find every repository the token's user can reach. A failure keeps the previous list."""
        if not self._all_member:
            return
        repos = await self._client.list_member_repos(self._max_member)
        listed = {r.lower() for r in self._explicit}
        self._discovered = [r["full_name"] for r in repos if r["full_name"].lower() not in listed]
        if len(repos) >= self._max_member:
            logger.warning("github.member_repos_truncated", limit=self._max_member)
        logger.info("github.member_repos", discovered=len(self._discovered), listed=len(self._explicit))

    async def check(self) -> SourceCheck:
        """The token works, then every listed repository can be opened. Discovered ones are only counted."""
        try:
            await self._client.get_current_user()
            await self.refresh_scopes()
        except Exception as exc:  # noqa: BLE001 -- reported, not raised
            return SourceCheck(ok=False, detail=f"cannot use the token: {error_detail(exc)}")
        results = []
        for scope in self._explicit:
            try:
                repo = await self._client.get_repo(scope)
                results.append(ScopeCheck(scope=scope, ok=True, detail=repo.get("full_name", "found")))
            except Exception as exc:  # noqa: BLE001
                results.append(ScopeCheck(scope=scope, ok=False, detail=error_detail(exc)))
        found = f"{len(self._discovered)} more found from membership" if self._all_member else "signed in"
        return SourceCheck(ok=all(r.ok for r in results), detail=found, scopes=results)

    def _normalize(
        self,
        scope: str,
        repo: dict[str, Any],
        pr: dict[str, Any],
        raw_commits: list[dict[str, Any]],
        raw_comments: list[dict[str, Any]],
        raw_review_comments: list[dict[str, Any]],
        raw_reviews: list[dict[str, Any]],
        raw_files: list[dict[str, Any]],
    ) -> GitHubDocument:
        full_name = repo.get("full_name", scope)
        commits = [
            GitHubCommit(
                sha=c["sha"],
                author=(c.get("commit", {}).get("author") or {}).get("name"),
                authored_at=(c.get("commit", {}).get("author") or {}).get("date"),
                message=c.get("commit", {}).get("message", ""),
                url=c.get("html_url", pr.get("html_url", "")),
                raw=c,
            )
            for c in raw_commits
        ]
        comments = [
            GitHubComment(
                comment_id=str(c["id"]), author=(c.get("user") or {}).get("login"), body=c.get("body") or "",
                created_at=c.get("created_at"), kind="conversation", raw=c,
            )
            for c in raw_comments
        ] + [
            GitHubComment(
                comment_id=str(c["id"]), author=(c.get("user") or {}).get("login"), body=c.get("body") or "",
                created_at=c.get("created_at"), kind="review_comment", path=c.get("path"), raw=c,
            )
            for c in raw_review_comments
        ]
        reviews = [
            GitHubReview(
                reviewer=(r.get("user") or {}).get("login"), state=r.get("state", ""), body=r.get("body") or "",
                submitted_at=r.get("submitted_at"), raw=r,
            )
            for r in raw_reviews
        ]
        files = [
            GitHubFile(
                filename=f.get("filename", ""), status=f.get("status", ""), additions=f.get("additions", 0),
                deletions=f.get("deletions", 0), patch=f.get("patch", "") or "",
            )
            for f in raw_files
        ]
        version = to_utc_iso(pr.get("updated_at"))
        return GitHubDocument(
            source=self.source,
            source_type="pull_request",
            source_object_id=f"{full_name}#{pr['number']}",
            source_url=pr.get("html_url", ""),
            retrieved_at=datetime.now(UTC),
            raw_payload={
                "pull_request": pr, "commits": raw_commits, "comments": raw_comments,
                "review_comments": raw_review_comments, "reviews": raw_reviews, "files": raw_files,
            },
            scope=scope,
            source_version=version,
            acl={"repository": full_name, "private": repo.get("private"), "visibility": repo.get("visibility")},
            title=pr.get("title", ""),
            content=pr.get("body") or "",
            metadata={"updated_at": version, "state": pr.get("state"), "repository": full_name},
            repository=full_name,
            pr_number=str(pr["number"]),
            description=pr.get("body"),
            state="merged" if pr.get("merged_at") else pr.get("state", ""),
            draft=bool(pr.get("draft", False)),
            base_branch=(pr.get("base") or {}).get("ref"),
            head_branch=(pr.get("head") or {}).get("ref"),
            merged_at=pr.get("merged_at"),
            commits=commits,
            comments=comments,
            reviews=reviews,
            files=files,
        )

    async def _fetch_pr(self, scope: str, repo: dict[str, Any], pr: dict[str, Any]) -> GitHubDocument:
        name, number = repo["full_name"], pr["number"]
        commits, comments, review_comments, reviews, files = await asyncio.gather(
            self._client.list_pr_commits(name, number),
            self._client.list_pr_comments(name, number),
            self._client.list_pr_review_comments(name, number),
            self._client.list_pr_reviews(name, number),
            self._client.list_pr_files(name, number),
        )
        return self._normalize(scope, repo, pr, commits, comments, review_comments, reviews, files)

    async def list_ids(self, scope: str) -> set[str]:
        """The repository and every pull request id right now (for delete reconciliation)."""
        ids = {f"github:{scope}"}
        await self._client.get_repo(scope)                      # a repository that is gone raises here: the scope fails
        page = 1
        while True:
            prs = await self._client.list_pull_requests(scope, page=page, per_page=self._page_size)
            ids |= {f"github:{scope}#{p['number']}" for p in prs}
            if len(prs) < self._page_size:
                return ids
            page += 1

    async def fetch_scope(self, scope: str, cursor: str | None) -> ScopeFetch:
        repo = await self._client.get_repo(scope)
        pulls = await self._client.list_pull_requests(repo["full_name"], cursor, per_page=self._page_size)
        semaphore = asyncio.Semaphore(self._pr_concurrency)

        async def one(pr: dict[str, Any]) -> GitHubDocument | ObjectError:
            async with semaphore:
                try:
                    return await self._fetch_pr(scope, repo, pr)
                except Exception as exc:  # noqa: BLE001 -- one bad pull request must not fail the scope
                    return ObjectError(
                        scope=scope, object_id=f"{repo['full_name']}#{pr.get('number')}",
                        source_version=to_utc_iso(pr.get("updated_at")), error=error_detail(exc),
                    )

        results = await asyncio.gather(*(one(pr) for pr in pulls))
        return ScopeFetch(
            documents=[r for r in results if isinstance(r, GitHubDocument)],
            errors=[r for r in results if isinstance(r, ObjectError)],
        )
