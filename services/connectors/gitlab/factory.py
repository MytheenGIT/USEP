"""Builds the gitlab client and connector from settings. Imported lazily by `registry`."""
from __future__ import annotations

from typing import Any

from config import Settings
from gitlab.client import GitLabClient
from gitlab.connector import GitLabConnector


def build(settings: Settings, binary_store: Any | None = None) -> tuple[GitLabClient, GitLabConnector]:
    c = settings.gitlab
    client = GitLabClient(base_url=c.base_url, private_token=c.private_token)
    return client, GitLabConnector(client, project_ids=c.project_ids, page_size=c.page_size)
