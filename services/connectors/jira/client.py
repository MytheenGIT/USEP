"""Jira Cloud client: JQL search, paged comments and changelog, attachment download."""

from __future__ import annotations

import base64
from typing import Any

import httpx

from common.client_base import BaseAPIClient, ClientRuntime

DEFAULT_FIELDS = [
    "summary",
    "description",
    "status",
    "priority",
    "issuetype",
    "project",
    "labels",
    "components",
    "fixVersions",
    "parent",
    "security",
    "resolution",
    "created",
    "updated",
    "comment",
    "attachment",
    "issuelinks",       # read by the ontology pipeline to draw implements/relates edges (C-02)
]


class JiraClient(BaseAPIClient):
    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        runtime: ClientRuntime | None = None,
    ) -> None:
        token = base64.b64encode(f"{email}:{api_token}".encode()).decode()
        headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}
        super().__init__(base_url=base_url, headers=headers, timeout=timeout, transport=transport, runtime=runtime)

    async def get_myself(self) -> dict[str, Any]:
        """The API user; its ``timeZone`` is the zone JQL date literals are read in."""
        return await self.get_json("/rest/api/3/myself")

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
        return await self.get_json(
            f"/rest/api/3/issue/{issue_key}/comment",
            params={"startAt": start_at, "maxResults": max_results, "orderBy": "created"},
        )

    async def get_issue_changelog(self, issue_key: str, start_at: int = 0, max_results: int = 100) -> dict[str, Any]:
        return await self.get_json(
            f"/rest/api/3/issue/{issue_key}/changelog",
            params={"startAt": start_at, "maxResults": max_results},
        )

    async def get_all_comments(self, issue_key: str, page_size: int = 100) -> list[dict[str, Any]]:
        comments: list[dict[str, Any]] = []
        start = 0
        while True:
            page = await self.get_issue_comments(issue_key, start_at=start, max_results=page_size)
            batch = page.get("comments", [])
            comments.extend(batch)
            start += len(batch)
            if not batch or start >= page.get("total", 0):
                return comments

    async def get_all_changelog(self, issue_key: str, page_size: int = 100) -> list[dict[str, Any]]:
        histories: list[dict[str, Any]] = []
        start = 0
        while True:
            page = await self.get_issue_changelog(issue_key, start_at=start, max_results=page_size)
            batch = page.get("values", [])
            histories.extend(batch)
            start += len(batch)
            if not batch or page.get("isLast", start >= page.get("total", 0)):
                return histories

    async def get_remote_links(self, issue_key: str) -> list[dict[str, Any]]:
        """Remote links on an issue: the native Jira-to-Confluence (and other web) links. A 403 or 404 means the
        integration user cannot see them or the issue has none; that is an empty list, not a failure."""
        try:
            data = await self.get_json(f"/rest/api/3/issue/{issue_key}/remotelink")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (403, 404):
                return []
            raise
        return data if isinstance(data, list) else []

    async def download_attachment(self, content_url: str, max_bytes: int) -> bytes:
        return await self.get_bytes(content_url, max_bytes)
