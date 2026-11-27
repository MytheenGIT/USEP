"""HTTP client for Azure DevOps REST API."""

from __future__ import annotations

import base64

import httpx

from common.client_base import BaseAPIClient, ClientRuntime


class AdoClient(BaseAPIClient):
    """Azure DevOps REST API client. Authentication is a PAT (Personal Access Token) sent as a Basic auth header."""

    def __init__(
        self,
        base_url: str,
        pat: str,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        runtime: ClientRuntime | None = None,
    ) -> None:
        """base_url is the organization URL, e.g., https://dev.azure.com/myorg"""
        auth_header = base64.b64encode(f":{pat}".encode()).decode()
        headers = {"Authorization": f"Basic {auth_header}"}
        super().__init__(base_url=base_url, headers=headers, timeout=timeout, transport=transport, runtime=runtime)

    async def list_projects(self) -> list[dict]:
        """List all projects in the organization."""
        result = await self.get_json("/_apis/projects", params={"api-version": "7.0"})
        return result.get("value", [])

    async def list_work_item_ids(self, project: str) -> list[int]:
        """Every work item id in the project. The API has no plain "list all work items" endpoint,
        so this runs a WIQL query that selects every id (WIQL caps a single query at 20000 results)."""
        wiql = {"query": "SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = @project ORDER BY [System.Id]"}
        result = await self.post_json(f"/{project}/_apis/wit/wiql?api-version=7.0", json=wiql)
        return [item["id"] for item in result.get("workItems", [])]

    async def get_work_items_batch(self, project: str, ids: list[int]) -> list[dict]:
        """Full records for up to 200 ids (the API's own limit per call)."""
        joined = ",".join(str(i) for i in ids)
        result = await self.get_json(f"/{project}/_apis/wit/workitems", params={"ids": joined, "api-version": "7.0", "$expand": "all"})
        return result.get("value", [])

    async def list_pull_requests(self, project: str, repo: str, state: str = "all") -> list[dict]:
        """List pull requests in a repository."""
        result = await self.get_json(
            f"/{project}/_apis/git/repositories/{repo}/pullrequests",
            params={"api-version": "7.0", "searchCriteria.status": state},
        )
        return result.get("value", [])

    async def list_repositories(self, project: str) -> list[dict]:
        """List repositories in a project."""
        result = await self.get_json(f"/{project}/_apis/git/repositories", params={"api-version": "7.0"})
        return result.get("value", [])
