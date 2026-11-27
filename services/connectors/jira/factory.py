"""Builds the jira client and connector from settings. Imported lazily by `registry`."""
from __future__ import annotations

from typing import Any

from config import Settings
from jira.client import JiraClient
from jira.connector import JiraConnector


def build(settings: Settings, binary_store: Any | None = None) -> tuple[JiraClient, JiraConnector]:
    c = settings.jira
    client = JiraClient(base_url=c.base_url, email=c.email, api_token=c.api_token)
    return client, JiraConnector(
        client, base_url=c.base_url, jql=c.jql, jql_queries=c.jql_queries, page_size=c.page_size,
        binary_store=binary_store, download_attachments=c.download_attachments,
        attachment_max_bytes=c.attachment_max_bytes,
        fetch_remote_links=c.fetch_remote_links)
