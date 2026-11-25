"""Example Figma connector: file/page/frame/text-layer metadata + export URL references.

Image binaries are never fetched; only the temporary export URLs Figma returns.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from figma.client import FigmaClient
from figma.models import FigmaDocument, FigmaFrame, FigmaFrameExportRef, FigmaPage, FigmaTextLayer
from common.source_document import SourceType


def _collect_text_layers(node: dict[str, Any]) -> list[FigmaTextLayer]:
    layers: list[FigmaTextLayer] = []
    if node.get("type") == "TEXT":
        layers.append(FigmaTextLayer(node_id=node["id"], name=node.get("name", ""), characters=node.get("characters", "")))
    for child in node.get("children", []):
        layers.extend(_collect_text_layers(child))
    return layers


class FigmaConnector:
    source = SourceType.FIGMA

    def __init__(self, client: FigmaClient, file_keys: list[str], export_format: str = "png") -> None:
        self._client = client
        self._file_keys = file_keys
        self._export_format = export_format

    async def _normalize_file(self, file_key: str) -> FigmaDocument:
        file_data = await self._client.get_file(file_key)
        document_node = file_data.get("document", {})

        pages: list[FigmaPage] = []
        all_frames: list[FigmaFrame] = []
        for canvas_node in document_node.get("children", []):
            frames = [
                FigmaFrame(
                    node_id=frame_node["id"],
                    name=frame_node.get("name", ""),
                    text_layers=_collect_text_layers(frame_node),
                )
                for frame_node in canvas_node.get("children", [])
                if frame_node.get("type") == "FRAME"
            ]
            pages.append(FigmaPage(node_id=canvas_node["id"], name=canvas_node.get("name", ""), frames=frames))
            all_frames.extend(frames)

        if all_frames:
            export_result = await self._client.get_image_export_urls(
                file_key, [f.node_id for f in all_frames], fmt=self._export_format
            )
            urls: dict[str, str | None] = export_result.get("images", {})
            for frame in all_frames:
                url = urls.get(frame.node_id)
                frame.export_refs = [FigmaFrameExportRef(format=self._export_format, url=url)]

        all_text_layers = [layer for frame in all_frames for layer in frame.text_layers]

        return FigmaDocument(
            source=self.source,
            source_type="file",
            source_object_id=file_key,
            source_url=f"https://www.figma.com/file/{file_key}",
            retrieved_at=datetime.now(UTC),
            raw_payload=file_data,
            title=file_data.get("name", file_key),
            content="",
            metadata={"last_modified": file_data.get("lastModified"), "version": file_data.get("version")},
            file_key=file_key,
            file_name=file_data.get("name", file_key),
            version=file_data.get("version"),
            last_modified=file_data.get("lastModified"),
            pages=pages,
            frames=all_frames,
            text_layers=all_text_layers,
        )

    async def fetch(self, cursor: str | None) -> tuple[list[FigmaDocument], str | None]:
        documents = [await self._normalize_file(file_key) for file_key in self._file_keys]

        if cursor:
            documents = [d for d in documents if (d.last_modified or "") >= cursor]

        modified_values = [d.last_modified for d in documents if d.last_modified]
        new_cursor = max(modified_values) if modified_values else cursor
        return documents, new_cursor
