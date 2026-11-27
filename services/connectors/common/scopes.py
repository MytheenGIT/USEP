"""What an admin may enter for each source, and the checks that keep it safe to use in a query.

Project keys and space keys end up inside JQL and CQL text, so only plain keys are accepted and
quotes or operators can never be smuggled in. A free-form JQL query is the admin's own query and
is passed to Jira as written (Jira itself rejects a bad one, and ``check`` reports it).
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

PROJECT_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_]{1,49}")
SPACE_KEY = re.compile(r"~?[A-Za-z0-9][A-Za-z0-9._:-]{0,254}")
_GITLAB_PATH = re.compile(r"[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)+")
_GITHUB_REPO = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]{1,100}")
_SSH_LINK = re.compile(r"^(?:ssh://)?git@([A-Za-z0-9.-]+)[:/](.+)$")
SERVICENOW_TABLE = re.compile(r"[a-z][a-z0-9_]{0,79}")
_PAGE_URL = re.compile(r"/pages/(\d+)")
_SPACE_URL = re.compile(r"/spaces/([^/]+)")


def is_http_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


def valid_project_key(key: str) -> bool:
    return PROJECT_KEY.fullmatch(key) is not None


def jira_project_scope(key: str) -> str:
    """The JQL for every issue of one project, oldest change first (the cursor clause is added later)."""
    if not valid_project_key(key):
        raise ValueError(f"not a Jira project key: {key!r}")
    return f'project = "{key}" ORDER BY updated ASC'


def confluence_scope_problem(scope: str) -> str | None:
    """Why a Confluence scope (space key, space URL or page URL) cannot be used, or None."""
    value = scope.strip()
    if "://" in value:
        if not is_http_url(value):
            return f"{scope!r} is not a valid URL"
        path = urlparse(value).path
        if _PAGE_URL.search(path):
            return None
        space = _SPACE_URL.search(path)
        if space and SPACE_KEY.fullmatch(space.group(1)):
            return None
        return f"{scope!r} is not a Confluence space or page URL"
    return None if SPACE_KEY.fullmatch(value) else f"{scope!r} is not a valid space key"


def repo_path_from_link(value: str) -> str:
    """``group/project`` from an https or SSH repository link (``git@host:group/project.git``); other text unchanged."""
    text = value.strip()
    ssh = _SSH_LINK.match(text)
    if ssh:
        text = ssh.group(2)
    elif "://" in text:
        text = urlparse(text).path
    return text.strip("/").split("/-/", 1)[0].removesuffix(".git")


def ssh_link_host(value: str) -> str | None:
    """The host of an SSH repository link, or None when the text is not one."""
    match = _SSH_LINK.match(value.strip())
    return match.group(1) if match else None


def github_scope_problem(scope: str) -> str | None:
    """Why a GitHub scope (``owner/repo``, an https link or an SSH link) cannot be used, or None."""
    text = scope.strip()
    if "://" in text and not text.startswith("ssh://") and not is_http_url(text):
        return f"{scope!r} is not a valid URL"
    path = repo_path_from_link(text)
    return None if _GITHUB_REPO.fullmatch(path) else f"{scope!r} is not a GitHub repository (use owner/repo or a link)"


def servicenow_table_problem(table: str) -> str | None:
    """Why a ServiceNow table name cannot be used, or None. Names go into a request path, so only plain names pass."""
    return None if SERVICENOW_TABLE.fullmatch(table.strip()) else f"{table!r} is not a ServiceNow table name (for example incident)"


def gitlab_scope_problem(scope: str) -> str | None:
    """Why a GitLab scope (project id, ``group/project`` path, repository URL or SSH link) cannot be used, or None."""
    value = scope.strip()
    if value.isdigit():
        return None
    if _SSH_LINK.match(value):
        return None if _GITLAB_PATH.fullmatch(repo_path_from_link(value)) else f"{scope!r} is not a project id, path or repository link"
    if "://" in value:
        if not is_http_url(value):
            return f"{scope!r} is not a valid URL"
        value = urlparse(value).path.strip("/").split("/-/", 1)[0].removesuffix(".git")
    return None if _GITLAB_PATH.fullmatch(value) else f"{scope!r} is not a project id, path or repository URL"
