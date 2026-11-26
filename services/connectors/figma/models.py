from __future__ import annotations

from pydantic import BaseModel

from common.source_document import SourceDocument


class FigmaTextLayer(BaseModel):
    node_id: str
    name: str
    characters: str


class FigmaFrameExportRef(BaseModel):
    """A rendered export of a frame: Figma's temporary URL, plus the stored copy when downloaded."""

    format: str
    url: str | None = None
    stored_ref: str | None = None
    content_hash: str | None = None
    skipped_reason: str | None = None


class FigmaFrame(BaseModel):
    node_id: str
    name: str
    page_id: str = ""
    page_name: str = ""
    text_layers: list[FigmaTextLayer] = []
    export_refs: list[FigmaFrameExportRef] = []


class FigmaPage(BaseModel):
    node_id: str
    name: str
    frames: list[FigmaFrame] = []


class FigmaDocument(SourceDocument):
    """Normalized Figma file.

    ``pages`` preserves the page -> frame -> text-layer hierarchy. ``frames`` and
    ``text_layers`` additionally flatten that same data into their own top-level
    fields, as required, so downstream chunking can iterate either shape without
    ever merging them into a single content string.
    """

    file_key: str
    file_name: str
    version: str | None = None
    last_modified: str | None = None
    # Node ids the scope was limited to (empty means the whole file).
    selected_node_ids: list[str] = []
    pages: list[FigmaPage] = []
    frames: list[FigmaFrame] = []
    text_layers: list[FigmaTextLayer] = []
