"""Normalise what an admin typed into a clean target: a Jira project key, Confluence space key,
GitLab project (path or numeric id) or Figma file key. Each entry may be the bare value or a pasted URL.

Every value is checked against a strict pattern before it reaches a query or a request path, so a typed
entry cannot inject JQL or path segments.
"""

from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

from common.scopes import repo_path_from_link

JIRA_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,19}$")
CONFLUENCE_SPACE = re.compile(r"^[~A-Za-z0-9_.-]{1,255}$")
GITLAB_PATH = re.compile(r"^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)+$")
GITLAB_ID = re.compile(r"^\d{1,12}$")
FIGMA_KEY = re.compile(r"^[A-Za-z0-9]{10,64}$")
GITHUB_REPO = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]{1,100}$")
SERVICENOW_TABLE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
_SSH_LINK = re.compile(r"^(?:ssh://)?git@[A-Za-z0-9.-]+[:/].+$")


class TargetError(ValueError):
    """The entry cannot be used. The message is safe to show the admin."""


def _path_of(entry: str) -> str | None:
    """The URL path when `entry` looks like a URL, else None."""
    if "://" not in entry:
        return None
    parts = urlsplit(entry)
    if parts.scheme not in ("http", "https"):
        raise TargetError("Only https:// links are accepted")
    return unquote(parts.path)


def jira_project_key(entry: str) -> str:
    entry = entry.strip()
    path = _path_of(entry)
    if path is not None:
        match = re.search(r"/projects/([^/?#]+)", path)
        entry = match.group(1) if match else ""
    if not JIRA_KEY.match(entry):
        raise TargetError(f"'{entry[:40]}' is not a Jira project key (letters, digits, underscore; for example PAY)")
    return entry.upper()


def confluence_space_key(entry: str) -> str:
    entry = entry.strip()
    path = _path_of(entry)
    if path is not None:
        match = re.search(r"/spaces/([^/?#]+)", path)
        entry = match.group(1) if match else ""
    if not CONFLUENCE_SPACE.match(entry):
        raise TargetError(f"'{entry[:40]}' is not a Confluence space key (for example PAY)")
    return entry


def gitlab_project(entry: str) -> str:
    """Return 'group/project' (any depth) or a numeric project id. An https link or an SSH link is accepted."""
    entry = entry.strip()
    if _SSH_LINK.match(entry):
        entry = repo_path_from_link(entry)
    path = _path_of(entry)
    if path is not None:
        entry = path.strip("/").split("/-/")[0]
    entry = entry.strip("/").removesuffix(".git")
    if not (GITLAB_ID.match(entry) or GITLAB_PATH.match(entry)):
        raise TargetError(f"'{entry[:40]}' is not a GitLab project (use group/project or the numeric id)")
    return entry


def github_repository(entry: str) -> str:
    """Return 'owner/repo' from that, an https link (also GitHub Enterprise) or an SSH link (git@github.com:owner/repo.git)."""
    entry = entry.strip()
    if _SSH_LINK.match(entry):
        entry = repo_path_from_link(entry)
    path = _path_of(entry)
    if path is not None:
        entry = "/".join(path.strip("/").split("/")[:2])
    entry = entry.strip("/").removesuffix(".git")
    if not GITHUB_REPO.match(entry):
        raise TargetError(f"'{entry[:40]}' is not a GitHub repository (use owner/repo, or paste its link)")
    return entry


def servicenow_table(entry: str) -> str:
    entry = entry.strip().lower()
    if not SERVICENOW_TABLE.match(entry):
        raise TargetError(f"'{entry[:40]}' is not a ServiceNow table name (for example incident or change_request)")
    return entry


def figma_file_key(entry: str) -> str:
    entry = entry.strip()
    path = _path_of(entry)
    if path is not None:
        host = (urlsplit(entry).hostname or "").lower()
        if host not in ("figma.com", "www.figma.com"):
            raise TargetError("Figma links must be on figma.com")
        match = re.match(r"^/(?:file|design|proto|board)/([^/?#]+)", path)
        entry = match.group(1) if match else ""
    if not FIGMA_KEY.match(entry):
        raise TargetError(f"'{entry[:40]}' is not a Figma file key (the part after /design/ in the link)")
    return entry
