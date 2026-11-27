"""Builds the figma client and connector from settings. Imported lazily by `registry`."""
from __future__ import annotations

from typing import Any

from config import Settings
from figma.client import FigmaClient
from figma.connector import FigmaConnector


def build(settings: Settings, binary_store: Any | None = None) -> tuple[FigmaClient, FigmaConnector]:
    c = settings.figma
    client = FigmaClient(base_url=c.base_url, access_token=c.access_token)
    return client, FigmaConnector(
        client, file_keys=c.file_keys, export_format=c.export_format, binary_store=binary_store,
        download_exports=c.download_exports, export_max_bytes=c.export_max_bytes)
