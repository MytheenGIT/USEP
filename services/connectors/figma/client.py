"""Figma client. Only metadata and export URLs are ever fetched -- never image binaries."""

from __future__ import annotations

from typing import Any

from common.client_base import BaseAPIClient


class FigmaClient(BaseAPIClient):
    def __init__(self, base_url: str, access_token: str, timeout: float = 30.0) -> None:
        super().__init__(base_url=base_url, headers={"X-Figma-Token": access_token}, timeout=timeout)

    async def get_file(self, file_key: str) -> dict[str, Any]:
        """Full document tree: pages (CANVAS) -> frames (FRAME) -> text layers (TEXT)."""
        return await self.get_json(f"/v1/files/{file_key}")

    async def get_image_export_urls(self, file_key: str, node_ids: list[str], fmt: str = "png") -> dict[str, Any]:
        """Returns a mapping of node id -> temporary export URL. Never downloads the image."""
        if not node_ids:
            return {"images": {}}
        return await self.get_json(
            f"/v1/images/{file_key}",
            params={"ids": ",".join(node_ids), "format": fmt},
        )
