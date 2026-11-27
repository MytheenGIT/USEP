"""Builds the ado client and connector from settings. Imported lazily by `registry`."""
from __future__ import annotations

from typing import Any

from config import Settings
from ado.client import AdoClient
from ado.connector import AdoConnector


def build(settings: Settings, binary_store: Any | None = None) -> tuple[AdoClient, AdoConnector]:
    c = settings.ado
    client = AdoClient(organization_url=c.organization_url, pat=c.pat)
    return client, AdoConnector(client, organization_url=c.organization_url, projects=c.projects, page_size=c.page_size)
