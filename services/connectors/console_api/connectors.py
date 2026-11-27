"""Builds the connector for one source from what the admin entered (or the server holds).

One place for it, so "test connection" and "process the configuration" read exactly the same scopes.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from common.client_base import BaseAPIClient, ClientRuntime
from ado.client import AdoClient
from ado.connector import AdoConnector
from common.git_ssh import load_known_hosts, ssh_host_for
from common.source_document import SourceType
from config import Settings
from confluence.client import ConfluenceClient
from confluence.connector import ConfluenceConnector
from console_api.secrets_store import Credentials
from figma.client import FigmaClient
from figma.connector import FigmaConnector
from github.client import GitHubClient
from github.connector import GitHubConnector
from gitlab.client import GitLabClient
from gitlab.connector import GitLabConnector
from gitrepo.connector import GitSshConnector
from jira.client import JiraClient
from jira.connector import JiraConnector, build_scopes
from servicenow.client import ServiceNowClient
from servicenow.connector import ServiceNowConnector


class _NoClient:
    """SSH access has no HTTP client to close."""

    async def aclose(self) -> None:
        return None


def build_connector(
    key: str,
    *,
    base_url: str,
    creds: Credentials,
    targets: list[str],
    jql_queries: list[str] = (),  # type: ignore[assignment]
    all_member_projects: bool = False,
    settings: Settings,
    runtime: ClientRuntime | None = None,
    auth_method: str = "token",
    encoded_query: str = "",
) -> tuple[Any, BaseAPIClient]:
    """The connector and its client (the caller closes the client)."""
    if auth_method == "ssh_key" and key in ("github", "gitlab"):
        known_hosts = load_known_hosts(settings.ssh_known_hosts, settings.ssh_known_hosts_file)
        connector = GitSshConnector(SourceType(key), targets, ssh_host_for(key, base_url), creds.ssh_key, known_hosts)
        return connector, _NoClient()  # type: ignore[return-value]
    if key == "ado":
        client = AdoClient(base_url=base_url, pat=creds.secret, runtime=runtime)
        return AdoConnector(client, base_url=base_url, project_names=targets), client
    if key == "jira":
        client = JiraClient(base_url=base_url, email=creds.email, api_token=creds.secret, runtime=runtime)
        return JiraConnector(client, base_url, jql_queries=build_scopes("", list(jql_queries), targets), page_size=settings.jira.page_size), client
    if key == "confluence":
        client = ConfluenceClient(base_url=base_url, email=creds.email, api_token=creds.secret, runtime=runtime)
        connector = ConfluenceConnector(
            client, base_url=base_url, space_keys=targets, page_size=settings.confluence.page_size,
            fetch_version_history=settings.confluence.fetch_version_history,
            version_history_limit=settings.confluence.version_history_limit,
        )
        return connector, client
    if key == "gitlab":
        client = GitLabClient(base_url=base_url, private_token=creds.secret, runtime=runtime)
        connector = GitLabConnector(
            client, project_ids=targets, page_size=settings.gitlab.page_size, all_member_projects=all_member_projects,
            max_member_projects=settings.gitlab.max_member_projects,
        )
        return connector, client
    if key == "github":
        github = GitHubClient(base_url=base_url, token=creds.secret, runtime=runtime)
        return GitHubConnector(
            github, repositories=targets, page_size=settings.github.page_size, all_member_projects=all_member_projects,
            max_member_projects=settings.github.max_member_projects,
        ), github
    if key == "servicenow":
        snow = ServiceNowClient(base_url=base_url, username=creds.email, password=creds.secret, runtime=runtime)
        return ServiceNowConnector(snow, tables=targets, encoded_query=encoded_query, page_size=settings.servicenow.page_size), snow
    client = FigmaClient(base_url=base_url, access_token=creds.secret, runtime=runtime)
    return FigmaConnector(client, file_keys=targets), client
