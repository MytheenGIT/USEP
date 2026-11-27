from __future__ import annotations

from typing import Any

from common.client_base import BaseAPIClient


class GitHubClient(BaseAPIClient):
    """GitHub REST API (github.com or GitHub Enterprise Server: base_url https://<host>/api/v3)."""

    def __init__(self, base_url: str, token: str, timeout: float = 30.0) -> None:
        super().__init__(base_url=base_url, timeout=timeout, headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"})

    async def get_repo(self, repo: str) -> dict[str, Any]:
        return await self.get_json(f"/repos/{repo}")

    async def list_pull_requests(self, repo: str, page: int = 1, per_page: int = 50) -> list[dict[str, Any]]:
        # Newest update first: the list endpoint has no `since`, so the connector stops at the first PR older than its cursor.
        return await self.get_json(f"/repos/{repo}/pulls", params={
            "state": "all", "sort": "updated", "direction": "desc", "page": page, "per_page": per_page})

    async def list_pr_commits(self, repo: str, number: int) -> list[dict[str, Any]]:
        return await self.get_json(f"/repos/{repo}/pulls/{number}/commits", params={"per_page": 100})

    async def list_pr_reviews(self, repo: str, number: int) -> list[dict[str, Any]]:
        return await self.get_json(f"/repos/{repo}/pulls/{number}/reviews", params={"per_page": 100})
