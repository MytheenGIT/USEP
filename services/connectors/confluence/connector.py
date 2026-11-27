"""Confluence connector: one scope per space (or page tree).

A scope is a space key, a space URL (``.../wiki/spaces/KEY/...``) or a page
URL (``.../pages/<id>/...``, which pulls that page and its descendants).

Changed pages are found with CQL ``lastmodified >= <date>`` instead of
listing the whole space. CQL date literals are read in the API user's time
zone, so the query steps back one day from the UTC cursor and pages older
than the cursor are dropped afterwards. Version history and child pages are
only fetched for pages that changed.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from common.connector_base import ObjectError, ScopeFetch
from common.source_document import SourceType
from common.timeutil import parse_ts, to_utc_iso
from confluence.client import ConfluenceClient
from confluence.models import ConfluenceChildRef, ConfluenceDocument, ConfluenceVersion

_SPACE_URL = re.compile(r"/spaces/([^/]+)")
_PAGE_URL = re.compile(r"/pages/(\d+)")


def _page_url(base_url: str, page: dict[str, Any]) -> str:
    webui = (page.get("_links") or {}).get("webui", "")
    if not webui:
        return base_url
    return f"{base_url}/wiki{webui}" if not webui.startswith("/wiki") else f"{base_url}{webui}"


def scope_filter(scope: str) -> tuple[str, str | None]:
    """CQL filter for a scope, and the space key when the scope names one."""
    value = scope.strip()
    if "://" in value:
        path = urlparse(value).path
        page = _PAGE_URL.search(path)
        if page:
            page_id = page.group(1)
            return f"(id = {page_id} OR ancestor = {page_id})", None
        space = _SPACE_URL.search(path)
        if space:
            value = space.group(1)
    return f'space = "{value}"', value


def _version(raw: dict[str, Any]) -> ConfluenceVersion:
    return ConfluenceVersion(
        number=raw.get("number", 1),
        author=(raw.get("by") or {}).get("displayName"),
        when=raw.get("when"),
        message=raw.get("message"),
    )


class ConfluenceConnector:
    source = SourceType.CONFLUENCE

    def __init__(
        self,
        client: ConfluenceClient,
        base_url: str,
        space_keys: list[str],
        page_size: int = 25,
        fetch_version_history: bool = True,
        version_history_limit: int = 50,
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._scopes = [s for s in space_keys if s.strip()]
        self._page_size = page_size
        self._fetch_version_history = fetch_version_history
        self._version_history_limit = version_history_limit

    @property
    def scopes(self) -> list[str]:
        return list(self._scopes)

    def build_cql(self, scope: str, cursor: str | None) -> str:
        where, _ = scope_filter(scope)
        cql = f"{where} AND type = page"
        cursor_dt = parse_ts(cursor)
        if cursor_dt:
            since = (cursor_dt - timedelta(days=1)).strftime("%Y-%m-%d")
            cql += f' AND lastmodified >= "{since}"'
        return f"{cql} ORDER BY lastmodified ASC"

    async def _normalize_page(self, scope: str, page: dict[str, Any]) -> ConfluenceDocument:
        page_id = str(page["id"])
        raw_children = await self._client.get_page_children(page_id)
        raw_versions = (
            await self._client.get_page_version_history(page_id, self._version_history_limit)
            if self._fetch_version_history
            else []
        )
        children = [
            ConfluenceChildRef(page_id=str(c["id"]), title=c.get("title", ""), url=_page_url(self._base_url, c))
            for c in raw_children
        ]
        ancestors = [
            ConfluenceChildRef(page_id=str(a["id"]), title=a.get("title", ""), url=_page_url(self._base_url, a))
            for a in page.get("ancestors", [])
        ]
        labels = [label.get("name", "") for label in (page.get("metadata", {}).get("labels", {}).get("results", []))]
        version = _version(page.get("version", {}) or {})
        body = ((page.get("body") or {}).get("storage") or {}).get("value", "")
        space_key = (page.get("space") or {}).get("key") or scope_filter(scope)[1] or ""
        read_groups = [
            g.get("name", "")
            for g in (((page.get("restrictions") or {}).get("read") or {}).get("restrictions") or {})
            .get("group", {})
            .get("results", [])
        ]
        source_version = to_utc_iso(version.when)

        return ConfluenceDocument(
            source=self.source,
            source_type="page",
            source_object_id=page_id,
            source_url=_page_url(self._base_url, page),
            retrieved_at=datetime.now(UTC),
            raw_payload={"page": page, "children": raw_children, "versions": raw_versions},
            scope=scope,
            source_version=source_version,
            acl={"space_key": space_key, "read_restriction_groups": read_groups},
            title=page.get("title", ""),
            content=body,
            metadata={"version_when": source_version, "version_number": version.number},
            space_key=space_key,
            page_id=page_id,
            labels=labels,
            version=version,
            version_history=[_version(v) for v in raw_versions],
            ancestors=ancestors,
            children=children,
        )

    async def list_ids(self, scope: str) -> set[str]:
        """Every page id in the space right now (for delete reconciliation). Ids only: no bodies."""
        pages = await self._client.search_pages(self.build_cql(scope, None), limit=self._page_size, expand="version")
        return {str(p["id"]) for p in pages}

    async def fetch_scope(self, scope: str, cursor: str | None) -> ScopeFetch:
        pages = await self._client.search_pages(self.build_cql(scope, cursor), limit=self._page_size)

        documents: list[ConfluenceDocument] = []
        errors: list[ObjectError] = []
        for page in pages:
            version = to_utc_iso(((page.get("version") or {}).get("when")))
            if cursor and version and version < cursor:
                continue  # inside the one-day look-back but not changed since the cursor
            try:
                documents.append(await self._normalize_page(scope, page))
            except Exception as exc:  # noqa: BLE001 -- one bad page must not fail the scope
                errors.append(ObjectError(scope=scope, object_id=str(page.get("id")), source_version=version, error=str(exc)))
        return ScopeFetch(documents=documents, errors=errors)
