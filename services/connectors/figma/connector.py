"""Figma connector: one scope per file.

A scope is a file key or a file URL. A URL with ``?node-id=`` limits the
pull to those pages or frames (spec Module 1: Figma file URLs with page or
node selections).

Each run first asks for the file at ``depth=1``; if ``lastModified`` is not
newer than the cursor the file is skipped without downloading the tree or
rendering exports. Frames are found at any depth under sections and groups.
Export URLs from Figma expire, so the renders can optionally be downloaded
into the binary store.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import structlog

from common.binary_store import BinaryStore
from common.client_base import PayloadTooLarge, download_unauthenticated
from common.connector_base import ObjectError, ScopeFetch
from common.source_document import SourceType
from common.timeutil import to_utc_iso
from figma.client import FigmaClient
from figma.models import FigmaDocument, FigmaFrame, FigmaFrameExportRef, FigmaPage, FigmaTextLayer

logger = structlog.get_logger(__name__)

_FILE_URL = re.compile(r"/(?:file|design|proto|board)/([A-Za-z0-9]+)")
_CONTAINERS = {"SECTION", "GROUP"}


def parse_scope(scope: str) -> tuple[str, list[str]]:
    """(file_key, selected node ids) from a file key or a Figma URL."""
    value = scope.strip()
    if "://" not in value:
        return value, []
    parsed = urlparse(value)
    match = _FILE_URL.search(parsed.path)
    if not match:
        raise ValueError(f"Not a Figma file URL: {scope}")
    node_ids = [n.replace("-", ":") for raw in parse_qs(parsed.query).get("node-id", []) for n in raw.split(",") if n]
    return match.group(1), node_ids


def _collect_text_layers(node: dict[str, Any]) -> list[FigmaTextLayer]:
    layers: list[FigmaTextLayer] = []
    if node.get("type") == "TEXT":
        layers.append(FigmaTextLayer(node_id=node["id"], name=node.get("name", ""), characters=node.get("characters", "")))
    for child in node.get("children", []):
        layers.extend(_collect_text_layers(child))
    return layers


def _collect_frames(node: dict[str, Any], page_id: str, page_name: str) -> list[FigmaFrame]:
    """Top-most FRAME nodes under ``node``, looking through sections and groups."""
    if node.get("type") == "FRAME":
        return [
            FigmaFrame(
                node_id=node["id"],
                name=node.get("name", ""),
                page_id=page_id,
                page_name=page_name,
                text_layers=_collect_text_layers(node),
            )
        ]
    frames: list[FigmaFrame] = []
    if node.get("type") in _CONTAINERS or node.get("type") == "CANVAS":
        for child in node.get("children", []):
            frames.extend(_collect_frames(child, page_id, page_name))
    return frames


class FigmaConnector:
    source = SourceType.FIGMA

    def __init__(
        self,
        client: FigmaClient,
        file_keys: list[str],
        export_format: str = "png",
        binary_store: BinaryStore | None = None,
        download_exports: bool = False,
        export_max_bytes: int = 10_485_760,
    ) -> None:
        self._client = client
        self._scopes = [k for k in file_keys if k.strip()]
        self._export_format = export_format
        self._binary_store = binary_store
        self._download_exports = download_exports and binary_store is not None
        self._export_max_bytes = export_max_bytes

    @property
    def scopes(self) -> list[str]:
        return list(self._scopes)

    def _pages(self, file_data: dict[str, Any], selected: list[str]) -> list[FigmaPage]:
        if not selected:
            canvases = (file_data.get("document") or {}).get("children", [])
            return [
                FigmaPage(node_id=c["id"], name=c.get("name", ""), frames=_collect_frames(c, c["id"], c.get("name", "")))
                for c in canvases
            ]
        pages: list[FigmaPage] = []
        loose = FigmaPage(node_id="", name="(selected nodes)")
        for node_id in selected:
            node = ((file_data.get("nodes") or {}).get(node_id) or {}).get("document")
            if not node:
                continue
            if node.get("type") == "CANVAS":
                pages.append(FigmaPage(node_id=node["id"], name=node.get("name", ""), frames=_collect_frames(node, node["id"], node.get("name", ""))))
            else:
                loose.frames.extend(_collect_frames(node, "", ""))
        if loose.frames:
            pages.append(loose)
        return pages

    async def _attach_exports(self, file_key: str, version: str | None, frames: list[FigmaFrame]) -> str | None:
        """Fill export refs; returns an error message if the render call failed (non-fatal)."""
        try:
            urls = await self._client.get_image_export_urls(file_key, [f.node_id for f in frames], fmt=self._export_format)
        except Exception as exc:  # noqa: BLE001 -- metadata and text are still useful without renders
            logger.warning("figma.export_failed", file_key=file_key, error=str(exc))
            for frame in frames:
                frame.export_refs = [FigmaFrameExportRef(format=self._export_format, skipped_reason="export_failed")]
            return str(exc)

        for frame in frames:
            ref = FigmaFrameExportRef(format=self._export_format, url=urls.get(frame.node_id))
            if self._download_exports and ref.url:
                assert self._binary_store is not None
                key = f"figma/{file_key}/{version or 'unversioned'}/{frame.node_id}.{self._export_format}"
                existing = self._binary_store.exists(key)
                if existing:
                    ref.stored_ref = existing
                else:
                    try:
                        data = await download_unauthenticated(ref.url, self._export_max_bytes)
                        ref.stored_ref, ref.content_hash = self._binary_store.put(key, data)
                    except PayloadTooLarge:
                        ref.skipped_reason = "Q-SIZE"
                    except Exception as exc:  # noqa: BLE001
                        ref.skipped_reason = "download_failed"
                        logger.warning("figma.export_download_failed", file_key=file_key, node_id=frame.node_id, error=str(exc))
            frame.export_refs = [ref]
        return None

    async def fetch_scope(self, scope: str, cursor: str | None) -> ScopeFetch:
        file_key, selected = parse_scope(scope)
        meta = await self._client.get_file(file_key, depth=1)
        source_version = to_utc_iso(meta.get("lastModified"))
        if cursor and source_version and source_version <= cursor:
            return ScopeFetch()  # unchanged since the last successful run

        try:
            file_data = await (self._client.get_nodes(file_key, selected) if selected else self._client.get_file(file_key))
            pages = self._pages(file_data, selected)
            frames = [f for p in pages for f in p.frames]
            export_error = await self._attach_exports(file_key, meta.get("version"), frames) if frames else None
        except Exception as exc:  # noqa: BLE001
            # No source_version: the cursor stays where it was, so the file is retried next run.
            return ScopeFetch(errors=[ObjectError(scope=scope, object_id=file_key, error=str(exc))])

        document = FigmaDocument(
            source=self.source,
            source_type="file",
            source_object_id=file_key,
            source_url=f"https://www.figma.com/design/{file_key}",
            retrieved_at=datetime.now(UTC),
            raw_payload=file_data,
            scope=scope,
            source_version=source_version,
            acl={"file_key": file_key},
            title=meta.get("name", file_key),
            content="",
            metadata={
                "last_modified": source_version,
                "version": meta.get("version"),
                **({"export_error": export_error} if export_error else {}),
            },
            file_key=file_key,
            file_name=meta.get("name", file_key),
            version=meta.get("version"),
            last_modified=meta.get("lastModified"),
            selected_node_ids=selected,
            pages=pages,
            frames=frames,
            text_layers=[layer for frame in frames for layer in frame.text_layers],
        )
        return ScopeFetch(documents=[document])
