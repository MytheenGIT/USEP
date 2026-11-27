"""Figma REST client."""

from __future__ import annotations

from typing import Any

import httpx

from common.client_base import BaseAPIClient

EXPORT_BATCH = 50


class FigmaClient(BaseAPIClient):
    def __init__(
        self,
        base_url: str,
        access_token: str,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(base_url=base_url, headers={"X-Figma-Token": access_token}, timeout=timeout, transport=transport)

    async def get_file(self, file_key: str, depth: int | None = None) -> dict[str, Any]:
        """Document tree. ``depth=1`` returns only file metadata and the page list (cheap change check)."""
        params = {"depth": depth} if depth is not None else None
        return await self.get_json(f"/v1/files/{file_key}", params=params)

    async def get_nodes(self, file_key: str, node_ids: list[str]) -> dict[str, Any]:
        """Subtrees for the selected pages or frames only."""
        return await self.get_json(f"/v1/files/{file_key}/nodes", params={"ids": ",".join(node_ids)})

    async def get_image_export_urls(self, file_key: str, node_ids: list[str], fmt: str = "png") -> dict[str, str | None]:
        """Node id -> temporary render URL, requested in batches. Never downloads the image."""
        urls: dict[str, str | None] = {}
        for i in range(0, len(node_ids), EXPORT_BATCH):
            batch = node_ids[i : i + EXPORT_BATCH]
            result = await self.get_json(f"/v1/images/{file_key}", params={"ids": ",".join(batch), "format": fmt})
            urls.update(result.get("images") or {})
        return urls
