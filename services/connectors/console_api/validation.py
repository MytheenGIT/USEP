"""Parse and validate what the console form sends. The API is the control; the UI repeats these checks for feedback.

Field errors are keyed "<connector>.<field>" (for example "jira.project_keys") or "name".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from common.git_ssh import SshKeyError, load_known_hosts, require_host_key, ssh_host_for, validate_private_key
from config import Settings
from console_api.models import ConnectorSummary
from console_api.netguard import UnsafeUrlError, check_outbound_url, resolve_host
from console_api.secrets_store import Credentials
from console_api.targets import (
    TargetError,
    confluence_space_key,
    figma_file_key,
    github_repository,
    gitlab_project,
    jira_project_key,
    servicenow_table,
)

MAX_TARGETS = 200
MAX_NAME = 80
MAX_JQL = 2000
FIGMA_DPIA_MESSAGE = "Figma cannot be used until the DPIA is signed off (ADR-025). Ask the operator to record the approval."
GITHUB_WEBSITE_HOST_MESSAGE = (
    "That is the github.com website, not its API: use https://api.github.com "
    "(or https://<your-host>/api/v3 for GitHub Enterprise)."
)


@dataclass(frozen=True)
class ConnectorSpec:
    key: str
    label: str
    needs_base_url: bool
    needs_email: bool  # an identity next to the secret: an email (Atlassian) or a username (ServiceNow)
    target_field: str
    target_label: str
    normalise: Callable[[str], str]
    secret_label: str
    identity_kind: str = "email"  # "email" or "username"
    supports_ssh: bool = False  # GitHub and GitLab: an SSH key may be given instead of a token
    supports_all: bool = False  # GitHub and GitLab: "every repository I can reach"


SPECS: dict[str, ConnectorSpec] = {
    "ado": ConnectorSpec("ado", "Azure DevOps", True, False, "project_names", "Projects", lambda x: x.strip(), "Token"),
    "jira": ConnectorSpec("jira", "Jira", True, True, "project_keys", "Project keys", jira_project_key, "Token"),
    "confluence": ConnectorSpec("confluence", "Confluence", True, True, "space_keys", "Space keys", confluence_space_key, "Token"),
    "gitlab": ConnectorSpec("gitlab", "GitLab", True, False, "project_paths", "Projects", gitlab_project, "Token", supports_ssh=True, supports_all=True),
    "github": ConnectorSpec("github", "GitHub", True, False, "repositories", "Repositories", github_repository, "Token", supports_ssh=True, supports_all=True),
    "servicenow": ConnectorSpec("servicenow", "ServiceNow", True, True, "tables", "Tables", servicenow_table, "Password", identity_kind="username"),
    "figma": ConnectorSpec("figma", "Figma", False, False, "file_keys", "Files", figma_file_key, "Token"),
}


def server_credentials(settings: Settings, source: str) -> Credentials | None:
    """Credentials the operator configured on the server, if complete."""
    if source == "ado" and settings.ado.pat:
        return Credentials("", settings.ado.pat)
    if source == "jira" and settings.jira.email and settings.jira.api_token:
        return Credentials(settings.jira.email, settings.jira.api_token)
    if source == "confluence" and settings.confluence.email and settings.confluence.api_token:
        return Credentials(settings.confluence.email, settings.confluence.api_token)
    if source == "gitlab" and settings.gitlab.private_token:
        return Credentials("", settings.gitlab.private_token)
    if source == "github" and settings.github.token:
        return Credentials("", settings.github.token)
    if source == "servicenow" and settings.servicenow.username and settings.servicenow.password:
        return Credentials(settings.servicenow.username, settings.servicenow.password)
    if source == "figma" and settings.figma.access_token:
        return Credentials("", settings.figma.access_token)
    return None


def server_base_url(settings: Settings, source: str) -> str:
    return {
        "ado": settings.ado.base_url,
        "jira": settings.jira.base_url, "confluence": settings.confluence.base_url, "gitlab": settings.gitlab.base_url,
        "github": settings.github.base_url, "servicenow": settings.servicenow.base_url, "figma": settings.figma.base_url,
    }[source]


def _jql_queries(entries: Any, key: str, errors: dict[str, str]) -> list[str]:
    """The admin's own JQL queries: any number, each its own scope. Jira itself judges the syntax (a test shows it)."""
    if not isinstance(entries, list):
        return []
    queries: list[str] = []
    for entry in entries:
        text = entry.strip() if isinstance(entry, str) else ""
        if not text:
            continue
        if len(text) > MAX_JQL or any(ord(c) < 32 and c not in "\t\n" for c in text):
            errors[f"{key}.jql_queries"] = f"A JQL query must be plain text of at most {MAX_JQL} characters"
            return []
        if text not in queries:
            queries.append(text)
    if len(queries) > MAX_TARGETS:
        errors[f"{key}.jql_queries"] = f"At most {MAX_TARGETS} queries"
        return []
    return queries


@dataclass
class ParsedConnector:
    summary: ConnectorSummary
    base_url: str = ""  # the URL requests go to (guarded when typed by the admin)
    credentials: Credentials | None = None  # None means: use the server's


@dataclass
class ParsedConfig:
    name: str = ""
    connectors: dict[str, ParsedConnector] = field(default_factory=dict)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


async def parse_connector(
    spec: ConnectorSpec, raw: dict[str, Any], settings: Settings, errors: dict[str, str],
    resolver: Callable[[str], Awaitable[list[str]]] = resolve_host, require_targets: bool = True,
) -> ParsedConnector:
    """Validate one connector section. Appends to `errors`; never raises for bad input."""
    key = spec.key
    use_server = raw.get("use_server_credentials") is True
    email, secret = _text(raw.get("email")), raw.get("api_token") if isinstance(raw.get("api_token"), str) else ""
    secret = secret.strip()

    # connection
    base_url = ""
    typed_url = _text(raw.get("base_url"))
    if spec.needs_base_url:
        if typed_url:
            try:
                base_url = await check_outbound_url(
                    typed_url, allow_private=settings.allow_private_source_hosts,
                    allowed_hosts=settings.allowed_source_hosts, resolver=resolver,
                )
                # The one host every admin already knows by a different name: the website is not the API.
                if key == "github" and base_url.rstrip("/").lower() in ("https://github.com", "https://www.github.com"):
                    errors[f"{key}.base_url"] = GITHUB_WEBSITE_HOST_MESSAGE
                    base_url = ""
            except UnsafeUrlError as exc:
                errors[f"{key}.base_url"] = str(exc)
        elif server_base_url(settings, key):
            base_url = server_base_url(settings, key)
        else:
            errors[f"{key}.base_url"] = f"{spec.label} URL is required"
    else:
        base_url = server_base_url(settings, key)

    # how it signs in
    method = raw.get("auth_method") if spec.supports_ssh and raw.get("auth_method") in ("token", "ssh_key") else "token"
    ssh_key = raw.get("ssh_key") if isinstance(raw.get("ssh_key"), str) else ""

    # credentials
    creds: Credentials | None = None
    mode = "none"
    if method == "ssh_key":
        # An SSH key reads the commit history with git; it cannot call the platform API, so there is no account to list
        # repositories from, and the server's own credentials are tokens.
        try:
            if not base_url:
                raise SshKeyError(f"Enter the {spec.label} address first: it says which host to connect to")
            require_host_key(load_known_hosts(settings.ssh_known_hosts, settings.ssh_known_hosts_file), ssh_host_for(key, base_url))
            creds = Credentials("", "", ssh_key=validate_private_key(ssh_key))
            mode = "provided"
        except SshKeyError as exc:
            errors[f"{key}.ssh_key"] = str(exc)
        if use_server:
            errors[f"{key}.api_token"] = "The server's credentials are tokens: choose the token option to use them"
    elif use_server:
        if server_credentials(settings, key) is None:
            errors[f"{key}.api_token"] = f"The server has no {spec.label} credentials configured"
        else:
            mode = "server"
    else:
        if spec.needs_email and spec.identity_kind == "username":
            if not email:
                errors[f"{key}.email"] = "Username is required"
            elif len(email) > 100 or any(c.isspace() for c in email):
                errors[f"{key}.email"] = "Enter a valid username"
        elif spec.needs_email:
            if not email:
                errors[f"{key}.email"] = "Account email is required"
            elif "@" not in email or len(email) > 320:
                errors[f"{key}.email"] = "Enter a valid email address"
        if not secret:
            errors[f"{key}.api_token"] = f"{spec.secret_label} is required"
        elif len(secret) > 1024:
            errors[f"{key}.api_token"] = f"{spec.secret_label} is too long"
        else:
            creds = Credentials(email, secret)
            mode = "provided"

    # Figma: no live data before the DPIA is signed off (ADR-025), so it cannot be configured or tested until then.
    if key == "figma" and not settings.figma.dpia_approved:
        errors["figma.file_keys"] = FIGMA_DPIA_MESSAGE

    # extra choices some connectors have
    jql_queries = _jql_queries(raw.get("jql_queries"), key, errors) if key == "jira" else []
    all_member_projects = spec.supports_all and raw.get("all_member_projects") is True
    if all_member_projects and method == "ssh_key":
        errors[f"{key}.all_member_projects"] = "Choosing every repository needs a token: an SSH key cannot list your repositories"
        all_member_projects = False
    encoded_query = ""
    if key == "servicenow":
        encoded_query = _text(raw.get("encoded_query"))
        if len(encoded_query) > 1000 or any(ord(c) < 32 for c in encoded_query):
            errors["servicenow.encoded_query"] = "The query must be plain text of at most 1000 characters"
            encoded_query = ""

    # targets
    entries = raw.get(spec.target_field)
    targets: list[str] = []
    if not isinstance(entries, list):
        entries = []
    if len(entries) > MAX_TARGETS:
        errors[f"{key}.{spec.target_field}"] = f"At most {MAX_TARGETS} entries"
    else:
        problems = []
        for entry in entries:
            try:
                normalised = spec.normalise(entry if isinstance(entry, str) else "")
            except TargetError as exc:
                problems.append(str(exc))
                continue
            if normalised not in targets:
                targets.append(normalised)
        if problems:
            errors[f"{key}.{spec.target_field}"] = problems[0]
        elif not targets and require_targets and not (jql_queries or all_member_projects) and f"{key}.{spec.target_field}" not in errors:
            errors[f"{key}.{spec.target_field}"] = {
                "jira": "Add at least one project key or a JQL query",
                "gitlab": "Add at least one repository, or choose all repositories you are a member of",
                "github": "Add at least one repository, or choose all repositories you can reach",
                "servicenow": "Add at least one table, for example incident",
            }.get(key, f"Add at least one: {spec.target_label.lower()}")

    shown_url = (base_url or None) if spec.needs_base_url else None
    return ParsedConnector(
        summary=ConnectorSummary(
            enabled=True, base_url=shown_url, email=email or None if spec.needs_email and not use_server else None,
            targets=targets, jql_queries=jql_queries, all_member_projects=all_member_projects,
            auth_method=method, encoded_query=encoded_query,
            credentials=mode,  # type: ignore[arg-type]
        ),
        base_url=base_url, credentials=creds,
    )


async def parse_config(
    raw: dict[str, Any], settings: Settings, resolver: Callable[[str], Awaitable[list[str]]] = resolve_host
) -> tuple[ParsedConfig, dict[str, str]]:
    errors: dict[str, str] = {}
    name = _text(raw.get("name"))
    if not name:
        errors["name"] = "Name is required"
    elif len(name) > MAX_NAME:
        errors["name"] = f"Name must be {MAX_NAME} characters or fewer"

    # No connector is mandatory: an admin may have no Jira or no Figma. A selected connector must be complete,
    # and at least one must be selected, or there is nothing to read.
    parsed = ParsedConfig(name=name)
    connectors = raw.get("connectors")
    connectors = connectors if isinstance(connectors, dict) else {}
    for key, spec in SPECS.items():
        section = connectors.get(key)
        section = section if isinstance(section, dict) else {}
        if section.get("enabled") is True:
            parsed.connectors[key] = await parse_connector(spec, section, settings, errors, resolver)
        else:
            parsed.connectors[key] = ParsedConnector(summary=ConnectorSummary(enabled=False))
    if not any(c.summary.enabled for c in parsed.connectors.values()):
        errors["connectors"] = "Select at least one connector"
    return parsed, errors
