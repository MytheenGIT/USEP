from __future__ import annotations

from typing import Any
from urllib.parse import quote

from common.client_base import BaseAPIClient


class GitLabClient(BaseAPIClient):
    def __init__(self, base_url: str, private_token: str, timeout: float = 30.0) -> None:
        super().__init__(base_url=base_url, headers={"PRIVATE-TOKEN": private_token}, timeout=timeout)

    @staticmethod
    def _enc(project_id: str) -> str:
        return quote(str(project_id), safe="")

    async def list_merge_requests(
        self,
        project_id: str,
        updated_after: str | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"page": page, "per_page": per_page, "order_by": "updated_at", "sort": "asc"}
        if updated_after:
            params["updated_after"] = updated_after
        return await self.get_json(f"/api/v4/projects/{self._enc(project_id)}/merge_requests", params=params)

    async def list_mr_commits(self, project_id: str, mr_iid: str) -> list[dict[str, Any]]:
        return await self.get_json(f"/api/v4/projects/{self._enc(project_id)}/merge_requests/{mr_iid}/commits")

    async def list_mr_notes(self, project_id: str, mr_iid: str, page: int = 1, per_page: int = 50) -> list[dict[str, Any]]:
        return await self.get_json(
            f"/api/v4/projects/{self._enc(project_id)}/merge_requests/{mr_iid}/notes",
            params={"page": page, "per_page": per_page},
        )

    async def list_mr_approvals(self, project_id: str, mr_iid: str) -> dict[str, Any]:
        return await self.get_json(f"/api/v4/projects/{self._enc(project_id)}/merge_requests/{mr_iid}/approvals")

    async def get_mr_diffs(self, project_id: str, mr_iid: str) -> list[dict[str, Any]]:
        return await self.get_json(f"/api/v4/projects/{self._enc(project_id)}/merge_requests/{mr_iid}/diffs")
