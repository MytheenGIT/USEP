"""The repositories a token's user can reach, so the admin can tick the ones to read instead of typing each path."""

from __future__ import annotations

from collections.abc import Callable

from common.client_base import ClientRuntime, error_detail
from config import Settings
from console_api.models import RepositoryChoice, RepositoryList
from console_api.validation import ConnectorSpec, ParsedConnector, server_credentials
from github.client import GitHubClient
from gitlab.client import GitLabClient

LIMIT = 500


class RepositoryListError(Exception):
    """The list could not be fetched. The message is safe to show the admin."""


async def list_repositories(
    spec: ConnectorSpec, parsed: ParsedConnector, settings: Settings,
    runtime_for: Callable[[str, str], ClientRuntime | None] | None = None,
) -> RepositoryList:
    if spec.key not in ("github", "gitlab"):
        raise RepositoryListError(f"{spec.label} has no repositories to choose from")
    if parsed.summary.auth_method == "ssh_key":
        raise RepositoryListError("Choosing from your repositories needs a token: an SSH key cannot list them")
    creds = parsed.credentials or server_credentials(settings, spec.key)
    if creds is None or not creds.secret:
        raise RepositoryListError(f"Enter the {spec.label} token first")
    runtime = runtime_for(spec.key, parsed.base_url) if runtime_for else None
    if spec.key == "github":
        client: GitHubClient | GitLabClient = GitHubClient(parsed.base_url, creds.secret, runtime=runtime)
    else:
        client = GitLabClient(parsed.base_url, creds.secret, runtime=runtime)
    try:
        try:
            if isinstance(client, GitHubClient):
                raw = await client.list_member_repos(LIMIT + 1)
                items = [RepositoryChoice(path=r["full_name"], name=r.get("name", r["full_name"]), visibility="private" if r.get("private") else "public", description=r.get("description")) for r in raw]
            else:
                raw = await client.list_member_projects(LIMIT + 1)
                items = [RepositoryChoice(path=r["path_with_namespace"], name=r.get("name", r["path_with_namespace"]), visibility=r.get("visibility"), description=r.get("description")) for r in raw]
        except Exception as exc:  # noqa: BLE001 -- shown as a message
            raise RepositoryListError(f"Could not list repositories: {error_detail(exc)}") from exc
    finally:
        await client.aclose()
    items.sort(key=lambda r: r.path.lower())
    return RepositoryList(repositories=items[:LIMIT], truncated=len(items) > LIMIT)
