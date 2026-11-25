"""Example Confluence connector: spaces + pages + children + labels + version history."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from confluence.client import ConfluenceClient
from confluence.models import ConfluenceChildRef, ConfluenceDocument, ConfluenceVersion
from common.source_document import SourceType


def _page_url(base_url: str, page: dict[str, Any]) -> str:
    webui = (page.get("_links") or {}).get("webui", "")
    return f"{base_url}{webui}" if webui else base_url


class ConfluenceConnector:
    source = SourceType.CONFLUENCE

    def __init__(self, client: ConfluenceClient, base_url: str, space_keys: list[str], page_size: int = 25) -> None:
        self._client = client
        self._base_url = base_url
        self._space_keys = space_keys
        self._page_size = page_size

    async def _normalize_page(self, space_key: str, page: dict[str, Any]) -> ConfluenceDocument:
        page_id = page["id"]
        children_raw = await self._client.get_page_children(page_id)
        children = [
            ConfluenceChildRef(page_id=c["id"], title=c.get("title", ""), url=_page_url(self._base_url, c))
            for c in children_raw.get("results", [])
        ]
        ancestors = [
            ConfluenceChildRef(page_id=a["id"], title=a.get("title", ""), url=_page_url(self._base_url, a))
            for a in page.get("ancestors", [])
        ]
        labels = [label.get("name", "") for label in (page.get("metadata", {}).get("labels", {}).get("results", []))]
        version_raw = page.get("version", {}) or {}
        version = ConfluenceVersion(
            number=version_raw.get("number", 1),
            author=(version_raw.get("by") or {}).get("displayName"),
            when=version_raw.get("when"),
            message=version_raw.get("message"),
        )
        body = ((page.get("body") or {}).get("storage") or {}).get("value", "")

        return ConfluenceDocument(
            source=self.source,
            source_type="page",
            source_object_id=page_id,
            source_url=_page_url(self._base_url, page),
            retrieved_at=datetime.now(UTC),
            raw_payload=page,
            title=page.get("title", ""),
            content=body,
            metadata={"version_when": version.when},
            space_key=space_key,
            page_id=page_id,
            labels=labels,
            version=version,
            ancestors=ancestors,
            children=children,
        )

    async def _fetch_space(self, space_key: str) -> list[ConfluenceDocument]:
        documents: list[ConfluenceDocument] = []
        start = 0
        while True:
            page_result = await self._client.list_pages(space_key, limit=self._page_size, start=start)
            results = page_result.get("results", [])
            for page in results:
                documents.append(await self._normalize_page(space_key, page))
            if len(results) < self._page_size:
                break
            start += self._page_size
        return documents

    async def fetch(self, cursor: str | None) -> tuple[list[ConfluenceDocument], str | None]:
        documents: list[ConfluenceDocument] = []
        for space_key in self._space_keys:
            documents.extend(await self._fetch_space(space_key))

        if cursor:
            documents = [d for d in documents if (d.version.when and str(d.version.when) >= cursor)]

        updated_values = [str(d.version.when) for d in documents if d.version.when]
        new_cursor = max(updated_values) if updated_values else cursor
        return documents, new_cursor
