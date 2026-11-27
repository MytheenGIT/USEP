from __future__ import annotations

from typing import Any

import httpx

from common.client_base import BaseAPIClient, ClientRuntime
from common.timeutil import parse_ts


class GitHubClient(BaseAPIClient):
    """GitHub REST API. ``base_url`` is https://api.github.com, or https://<host>/api/v3 for GitHub Enterprise."""

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        runtime: ClientRuntime | None = None,
    ) -> None:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        super().__init__(base_url=base_url, headers=headers, timeout=timeout, transport=transport, runtime=runtime)

    async def get_all_pages(
        self, path: str, params: dict[str, Any] | None = None, per_page: int = 100, max_items: int | None = None
    ) -> list[Any]:
        """Follow the ``Link: rel="next"`` header to the end, or until ``max_items``."""
        items: list[Any] = []
        response = await self.get_response(path, params={**(params or {}), "per_page": per_page})
        while True:
            items.extend(response.json())
            if max_items is not None and len(items) >= max_items:
                return items[:max_items]
            next_url = response.links.get("next", {}).get("url")
            if not next_url:
                return items
            response = await self.get_response(next_url)

    async def get_current_user(self) -> dict[str, Any]:
        return await self.get_json("/user")

    async def get_repo(self, full_name: str) -> dict[str, Any]:
        return await self.get_json(f"/repos/{full_name}")

    async def list_member_repos(self, max_repos: int) -> list[dict[str, Any]]:
        """Repositories the token's user owns, collaborates on, or can reach through an organisation (not archived)."""
        repos = await self.get_all_pages(
            "/user/repos",
            {"affiliation": "owner,collaborator,organization_member", "sort": "full_name", "direction": "asc"},
            max_items=max_repos,
        )
        return [r for r in repos if not r.get("archived")]

    async def list_pull_requests(self, full_name: str, updated_since: str | None, per_page: int = 50) -> list[dict[str, Any]]:
        """Pull requests changed at or after ``updated_since``, oldest change first.

        The list has no "since" filter, so it is read newest change first and stops at the first page that reaches
        something older than the cursor.
        """
        since = parse_ts(updated_since)
        found: list[dict[str, Any]] = []
        response = await self.get_response(
            f"/repos/{full_name}/pulls", params={"state": "all", "sort": "updated", "direction": "desc", "per_page": per_page}
        )
        while True:
            page = response.json()
            found.extend(pr for pr in page if since is None or (parse_ts(pr.get("updated_at")) or since) >= since)
            reached_older = since is not None and any((parse_ts(pr.get("updated_at")) or since) < since for pr in page)
            next_url = response.links.get("next", {}).get("url")
            if reached_older or not next_url:
                return list(reversed(found))
            response = await self.get_response(next_url)

    async def list_pr_commits(self, full_name: str, number: int) -> list[dict[str, Any]]:
        return await self.get_all_pages(f"/repos/{full_name}/pulls/{number}/commits")

    async def list_pr_comments(self, full_name: str, number: int) -> list[dict[str, Any]]:
        return await self.get_all_pages(f"/repos/{full_name}/issues/{number}/comments")

    async def list_pr_review_comments(self, full_name: str, number: int) -> list[dict[str, Any]]:
        return await self.get_all_pages(f"/repos/{full_name}/pulls/{number}/comments")

    async def list_pr_reviews(self, full_name: str, number: int) -> list[dict[str, Any]]:
        return await self.get_all_pages(f"/repos/{full_name}/pulls/{number}/reviews")

    async def list_pr_files(self, full_name: str, number: int) -> list[dict[str, Any]]:
        return await self.get_all_pages(f"/repos/{full_name}/pulls/{number}/files")
