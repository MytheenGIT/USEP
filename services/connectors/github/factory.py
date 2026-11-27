"""Builds the github client and connector from settings. Imported lazily by `registry`."""
from __future__ import annotations

from typing import Any

from config import Settings
from github.client import GitHubClient
from github.connector import GitHubConnector


def build(settings: Settings, binary_store: Any | None = None) -> tuple[GitHubClient, GitHubConnector]:
    c = settings.github
    client = GitHubClient(base_url=c.base_url, token=c.token)
    return client, GitHubConnector(client, repos=c.repos, web_url=c.web_url, page_size=c.page_size)
