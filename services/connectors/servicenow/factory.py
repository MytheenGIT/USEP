"""Builds the servicenow client and connector from settings. Imported lazily by `registry`."""
from __future__ import annotations

from typing import Any

from config import Settings
from servicenow.client import ServiceNowClient
from servicenow.connector import ServiceNowConnector


def build(settings: Settings, binary_store: Any | None = None) -> tuple[ServiceNowClient, ServiceNowConnector]:
    c = settings.servicenow
    client = ServiceNowClient(instance_url=c.instance_url, username=c.username, password=c.password)
    return client, ServiceNowConnector(client, instance_url=c.instance_url, tables=c.tables, page_size=c.page_size)
