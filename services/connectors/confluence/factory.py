"""Builds the confluence client and connector from settings. Imported lazily by `registry`."""
from __future__ import annotations

from typing import Any

from config import Settings
from confluence.client import ConfluenceClient
from confluence.connector import ConfluenceConnector


def build(settings: Settings, binary_store: Any | None = None) -> tuple[ConfluenceClient, ConfluenceConnector]:
    c = settings.confluence
    client = ConfluenceClient(base_url=c.base_url, email=c.email, api_token=c.api_token)
    return client, ConfluenceConnector(
        client, base_url=c.base_url, space_keys=c.space_keys, page_size=c.page_size,
        fetch_version_history=c.fetch_version_history, version_history_limit=c.version_history_limit)
