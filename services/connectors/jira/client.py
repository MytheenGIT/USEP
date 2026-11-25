"""Example Jira client implementation (JQL search, pagination, changelog, comments)."""

from __future__ import annotations

import base64
from typing import Any

from common.client_base import BaseAPIClient

DEFAULT_FIELDS = ["summary", "description", "status", "priority", "comment", "attachment"]


class JiraClient(BaseAPIClient):
    def __init__(self, base_url: str, email: str, api_token: str, timeout: float = 30.0) -> None:
        token = base64.b64encode(f"{email}:{api_token}".encode()).decode()
        headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}
        super().__init__(base_url=base_url, headers=headers, timeout=timeout)

    async def search_issues(
        self,
        jql: str,
        next_page_token: str | None = None,
        max_results: int = 50,
        fields: list[str] | None = None,
        expand: list[str] | None = None,
    ) -> dict[str, Any]:
        """One page of JQL search results, via the token-based /search/jql endpoint."""
        params: dict[str, Any] = {
            "jql": jql,
            "maxResults": max_results,
            "fields": ",".join(fields or DEFAULT_FIELDS),
            "expand": ",".join(expand or ["changelog"]),
        }
        if next_page_token:
            params["nextPageToken"] = next_page_token
        return await self.get_json("/rest/api/3/search/jql", params=params)

    async def search_issues_paginated(
        self,
        jql: str,
        page_size: int = 50,
        fields: list[str] | None = None,
        expand: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Walks every page of a JQL search and returns the concatenated issues."""
        issues: list[dict[str, Any]] = []
        next_page_token: str | None = None
        while True:
            page = await self.search_issues(
                jql, next_page_token=next_page_token, max_results=page_size, fields=fields, expand=expand
            )
            issues.extend(page.get("issues", []))
            next_page_token = page.get("nextPageToken")
            if page.get("isLast", True) or not next_page_token:
                break
        return issues

    async def get_issue_comments(self, issue_key: str, start_at: int = 0, max_results: int = 100) -> dict[str, Any]:
        """Explicit comment fetch for issues whose embedded comment page was truncated."""
        return await self.get_json(
            f"/rest/api/3/issue/{issue_key}/comment",
            params={"startAt": start_at, "maxResults": max_results},
        )

    async def get_issue_changelog(self, issue_key: str, start_at: int = 0, max_results: int = 100) -> dict[str, Any]:
        """Explicit changelog fetch for issues whose embedded changelog page was truncated."""
        return await self.get_json(
            f"/rest/api/3/issue/{issue_key}/changelog",
            params={"startAt": start_at, "maxResults": max_results},
        )
