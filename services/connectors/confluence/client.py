from __future__ import annotations

from typing import Any

from common.client_base import BaseAPIClient

PAGE_EXPAND = "body.storage,version,ancestors,metadata.labels"


class ConfluenceClient(BaseAPIClient):
    def __init__(self, base_url: str, email: str, api_token: str, timeout: float = 30.0) -> None:
        super().__init__(base_url=base_url, headers={"Accept": "application/json"}, timeout=timeout)
        self._client.auth = (email, api_token)

    async def list_spaces(self, limit: int = 25, start: int = 0) -> dict[str, Any]:
        return await self.get_json("/wiki/rest/api/space", params={"limit": limit, "start": start})

    async def list_pages(self, space_key: str, limit: int = 25, start: int = 0) -> dict[str, Any]:
        return await self.get_json(
            "/wiki/rest/api/content",
            params={"spaceKey": space_key, "type": "page", "limit": limit, "start": start, "expand": PAGE_EXPAND},
        )

    async def get_page(self, page_id: str, expand: str = PAGE_EXPAND) -> dict[str, Any]:
        return await self.get_json(f"/wiki/rest/api/content/{page_id}", params={"expand": expand})

    async def get_page_children(self, page_id: str, limit: int = 50) -> dict[str, Any]:
        return await self.get_json(f"/wiki/rest/api/content/{page_id}/child/page", params={"limit": limit})

    async def get_page_labels(self, page_id: str) -> dict[str, Any]:
        return await self.get_json(f"/wiki/rest/api/content/{page_id}/label")

    async def get_page_version_history(self, page_id: str, limit: int = 50) -> dict[str, Any]:
        return await self.get_json(f"/wiki/rest/api/content/{page_id}/version", params={"limit": limit})
