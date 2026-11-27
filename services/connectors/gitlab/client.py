from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from common.client_base import BaseAPIClient, ClientRuntime


class GitLabClient(BaseAPIClient):
    def __init__(
        self,
        base_url: str,
        private_token: str,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        runtime: ClientRuntime | None = None,
    ) -> None:
        super().__init__(base_url=base_url, headers={"PRIVATE-TOKEN": private_token}, timeout=timeout, transport=transport, runtime=runtime)

    @staticmethod
    def _enc(project_ref: str) -> str:
        return quote(str(project_ref), safe="")

    async def get_all_pages(
        self, path: str, params: dict[str, Any] | None = None, per_page: int = 100, max_items: int | None = None
    ) -> list[Any]:
        """Follow GitLab's offset pagination (``X-Next-Page``) to the end, or until ``max_items``."""
        items: list[Any] = []
        page = 1
        while True:
            response = await self.get_response(path, params={**(params or {}), "page": page, "per_page": per_page})
            batch = response.json()
            items.extend(batch)
            if max_items is not None and len(items) >= max_items:
                return items[:max_items]
            next_page = response.headers.get("x-next-page", "")
            if not next_page or not batch:
                return items
            page = int(next_page)

    async def get_current_user(self) -> dict[str, Any]:
        return await self.get_json("/api/v4/user")

    async def list_member_projects(self, max_projects: int) -> list[dict[str, Any]]:
        """Every non-archived project the token's user is a member of (id and path only), up to ``max_projects``."""
        return await self.get_all_pages(
            "/api/v4/projects",
            {"membership": "true", "archived": "false", "simple": "true", "order_by": "id", "sort": "asc"},
            max_items=max_projects,
        )

    async def get_project(self, project_ref: str) -> dict[str, Any]:
        return await self.get_json(f"/api/v4/projects/{self._enc(project_ref)}")

    async def list_merge_requests(self, project_id: str, updated_after: str | None = None, per_page: int = 100) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"order_by": "updated_at", "sort": "asc", "scope": "all", "state": "all"}
        if updated_after:
            params["updated_after"] = updated_after
        return await self.get_all_pages(f"/api/v4/projects/{self._enc(project_id)}/merge_requests", params, per_page)

    async def list_mr_commits(self, project_id: str, mr_iid: str) -> list[dict[str, Any]]:
        return await self.get_all_pages(f"/api/v4/projects/{self._enc(project_id)}/merge_requests/{mr_iid}/commits")

    async def list_mr_notes(self, project_id: str, mr_iid: str) -> list[dict[str, Any]]:
        return await self.get_all_pages(
            f"/api/v4/projects/{self._enc(project_id)}/merge_requests/{mr_iid}/notes",
            {"sort": "asc", "order_by": "created_at"},
        )

    async def list_mr_approvals(self, project_id: str, mr_iid: str) -> dict[str, Any]:
        return await self.get_json(f"/api/v4/projects/{self._enc(project_id)}/merge_requests/{mr_iid}/approvals")

    async def get_mr_diffs(self, project_id: str, mr_iid: str) -> list[dict[str, Any]]:
        base = f"/api/v4/projects/{self._enc(project_id)}/merge_requests/{mr_iid}"
        try:
            return await self.get_all_pages(f"{base}/diffs")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
            # GitLab before 15.7 has no /diffs endpoint; /changes returns the same entries unpaged.
            return (await self.get_json(f"{base}/changes")).get("changes", [])
