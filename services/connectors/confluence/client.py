from __future__ import annotations

from typing import Any

import httpx

from common.client_base import BaseAPIClient, ClientRuntime

PAGE_EXPAND = "body.storage,version,ancestors,metadata.labels,space,restrictions.read.restrictions.group"


class ConfluenceClient(BaseAPIClient):
    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        runtime: ClientRuntime | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            headers={"Accept": "application/json"},
            timeout=timeout,
            auth=(email, api_token),
            transport=transport,
            runtime=runtime,
        )

    @staticmethod
    def _next_path(links: dict[str, Any]) -> str | None:
        """``_links.next`` is relative to the ``/wiki`` context path; turn it into a request path."""
        nxt = links.get("next")
        if not nxt:
            return None
        if nxt.startswith("http") or nxt.startswith("/wiki/"):
            return nxt
        return f"/wiki{nxt}"

    async def _all_results(self, path: str, params: dict[str, Any], max_items: int | None = None) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        page = await self.get_json(path, params=params)
        while True:
            results.extend(page.get("results", []))
            if max_items is not None and len(results) >= max_items:
                return results[:max_items]
            next_path = self._next_path(page.get("_links") or {})
            if not next_path or not page.get("results"):
                return results
            # The next link already carries every query parameter, including the cursor.
            page = await self.get_json(next_path)

    async def search_pages(self, cql: str, limit: int = 25, expand: str = PAGE_EXPAND) -> list[dict[str, Any]]:
        return await self._all_results("/wiki/rest/api/content/search", {"cql": cql, "limit": limit, "expand": expand})

    async def get_current_user(self) -> dict[str, Any]:
        return await self.get_json("/wiki/rest/api/user/current")

    async def get_space(self, space_key: str) -> dict[str, Any]:
        return await self.get_json(f"/wiki/rest/api/space/{space_key}")

    async def get_page(self, page_id: str, expand: str = PAGE_EXPAND) -> dict[str, Any]:
        return await self.get_json(f"/wiki/rest/api/content/{page_id}", params={"expand": expand})

    async def get_page_children(self, page_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return await self._all_results(f"/wiki/rest/api/content/{page_id}/child/page", {"limit": limit})

    async def get_page_version_history(self, page_id: str, max_versions: int = 50) -> list[dict[str, Any]]:
        return await self._all_results(
            f"/wiki/rest/api/content/{page_id}/version", {"limit": min(max_versions, 50)}, max_items=max_versions
        )
