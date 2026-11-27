from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote

from common.client_base import BaseAPIClient

API = "api-version=7.1"


class AdoClient(BaseAPIClient):
    """Azure DevOps Services / Server REST API. base_url is the organization (https://dev.azure.com/<org>)."""

    def __init__(self, organization_url: str, pat: str, timeout: float = 60.0) -> None:
        token = base64.b64encode(f":{pat}".encode()).decode()
        super().__init__(base_url=organization_url, timeout=timeout,
                         headers={"Authorization": f"Basic {token}", "Accept": "application/json"})

    @staticmethod
    def _p(project: str) -> str:
        return quote(project, safe="")

    async def wiql_ids(self, project: str, since: str | None) -> list[int]:
        where = "[System.TeamProject] = @project" + (f" AND [System.ChangedDate] >= '{since}'" if since else "")
        body = await self.post_json(f"/{self._p(project)}/_apis/wit/wiql?timePrecision=true&{API}", json={
            "query": f"SELECT [System.Id] FROM WorkItems WHERE {where} ORDER BY [System.ChangedDate] ASC"})
        return [w["id"] for w in body.get("workItems", [])]

    async def work_items(self, ids: list[int]) -> list[dict[str, Any]]:
        body = await self.post_json(f"/_apis/wit/workitemsbatch?{API}", json={"ids": ids, "$expand": "relations"})
        return body.get("value", [])

    async def list_repositories(self, project: str) -> list[dict[str, Any]]:
        return (await self.get_json(f"/{self._p(project)}/_apis/git/repositories", params={"api-version": "7.1"})).get("value", [])

    async def list_pull_requests(self, project: str, repo_id: str, status: str, min_time: str | None = None,
                                 top: int = 100, skip: int = 0) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"api-version": "7.1", "searchCriteria.status": status, "$top": top, "$skip": skip}
        if min_time and status != "active":
            params.update({"searchCriteria.minTime": min_time, "searchCriteria.queryTimeRangeType": "closed"})
        body = await self.get_json(f"/{self._p(project)}/_apis/git/repositories/{repo_id}/pullrequests", params=params)
        return body.get("value", [])
