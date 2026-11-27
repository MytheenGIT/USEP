from __future__ import annotations

import json
import re
from typing import Annotated, ClassVar, Literal
from uuid import UUID

from pydantic import BeforeValidator, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from common.scopes import (
    confluence_scope_problem,
    github_scope_problem,
    gitlab_scope_problem,
    is_http_url,
    servicenow_table_problem,
    valid_project_key,
)


APP_VERSION = "0.1.0"


def _unique(items: object) -> list[str]:
    return list(dict.fromkeys(str(i).strip() for i in items if str(i).strip()))  # type: ignore[attr-defined]


def _keys(value: object) -> list[str]:
    """A list from JSON (``["A","B"]``) or from plain text separated by commas, semicolons or new lines."""
    if isinstance(value, str):
        text = value.strip()
        value = json.loads(text) if text.startswith("[") else re.split(r"[,;\n]", text)
    return _unique(value or [])


def _queries(value: object) -> list[str]:
    """JQL queries from JSON or one per line. Never split on commas: a query may contain them."""
    if isinstance(value, str):
        text = value.strip()
        value = json.loads(text) if text.startswith("[") else text.split("\n")
    return _unique(value or [])


KeyList = Annotated[list[str], NoDecode, BeforeValidator(_keys)]
QueryList = Annotated[list[str], NoDecode, BeforeValidator(_queries)]


class _Source(BaseSettings):
    """A source is optional: it is read only when the admin selects it (``enabled``), and then it must be complete."""

    enabled: bool = False
    _fields: ClassVar[tuple[str, ...]] = ()  # the settings an admin fills in, used to notice a filled-in but unselected source

    def _env(self, name: str) -> str:
        return f"{self.model_config['env_prefix']}{name.upper()}"

    def _required(self, *names: str) -> list[str]:
        return [f"{self._env(n)} is required" for n in names if not getattr(self, n)]

    def _check(self) -> list[str]:
        return []

    def problems(self) -> list[str]:
        """What is missing or wrong. Empty when the source is not selected, or is complete."""
        return self._check() if self.enabled else []

    def filled_but_not_selected(self) -> bool:
        return not self.enabled and any(getattr(self, n) for n in self._fields)


class AdoSettings(_Source):
    model_config = SettingsConfigDict(env_prefix="USEP_INGESTION_ADO_")
    _fields: ClassVar[tuple[str, ...]] = ("pat", "project_names")

    base_url: str = ""  # e.g., https://dev.azure.com/myorganization
    pat: str = ""  # Personal Access Token
    project_names: KeyList = Field(default_factory=list)
    requests_per_second: float = 10.0

    def _check(self) -> list[str]:
        out = self._required("base_url", "pat", "project_names")
        if self.base_url and not is_http_url(self.base_url):
            out.append(f"{self._env('base_url')} must be an http(s) URL")
        return out


class JiraSettings(_Source):
    model_config = SettingsConfigDict(env_prefix="USEP_INGESTION_JIRA_")
    _fields: ClassVar[tuple[str, ...]] = ("email", "api_token", "jql", "jql_queries", "project_keys")

    base_url: str = ""
    email: str = ""
    api_token: str = ""
    # What to read, any mix of the three. A project key reads that whole project; several keys are several scopes.
    # The JQL is the admin's own query (one scope per query); write it without a cursor, the service adds one.
    jql: str = ""
    jql_queries: QueryList = Field(default_factory=list)
    project_keys: KeyList = Field(default_factory=list)
    page_size: int = 50
    download_attachments: bool = True
    # LLD Table 13, Q-SIZE: files over 1 MB are not stored; metadata is kept.
    attachment_max_bytes: int = 1_048_576
    # Requests per second this service allows itself against the source (conservative; check the vendor limit).
    requests_per_second: float = 5.0

    def _check(self) -> list[str]:
        out = self._required("base_url", "email", "api_token")
        if self.base_url and not is_http_url(self.base_url):
            out.append(f"{self._env('base_url')} must be an http(s) URL")
        if not (self.jql.strip() or self.jql_queries or self.project_keys):
            out.append(f"give at least one of {self._env('jql')}, {self._env('jql_queries')} or {self._env('project_keys')}")
        bad = [k for k in self.project_keys if not valid_project_key(k)]
        if bad:
            out.append(f"{self._env('project_keys')} has values that are not Jira project keys: {bad}")
        return out


class GitLabSettings(_Source):
    model_config = SettingsConfigDict(env_prefix="USEP_INGESTION_GITLAB_")
    _fields: ClassVar[tuple[str, ...]] = ("private_token", "project_ids", "all_member_projects")

    base_url: str = "https://gitlab.com"
    private_token: str = ""
    # Numeric ids, "group/project" paths, or repository URLs: as many as the admin works in.
    project_ids: KeyList = Field(default_factory=list)
    # Also read every repository the token's user is a member of (archived ones are skipped). The set is
    # re-discovered on a schedule. Off by default: it can pull in repositories nobody approved (LLD 4.1).
    all_member_projects: bool = False
    max_member_projects: int = 500
    page_size: int = 50
    # Requests per second this service allows itself against the source (conservative; check the vendor limit).
    requests_per_second: float = 10.0

    def _check(self) -> list[str]:
        out = self._required("base_url", "private_token")
        if self.base_url and not is_http_url(self.base_url):
            out.append(f"{self._env('base_url')} must be an http(s) URL")
        if not (self.project_ids or self.all_member_projects):
            out.append(f"give {self._env('project_ids')} or set {self._env('all_member_projects')}=true")
        out += [f"{self._env('project_ids')}: {p}" for s in self.project_ids if (p := gitlab_scope_problem(s))]
        return out


class ConfluenceSettings(_Source):
    model_config = SettingsConfigDict(env_prefix="USEP_INGESTION_CONFLUENCE_")
    _fields: ClassVar[tuple[str, ...]] = ("email", "api_token", "space_keys")

    base_url: str = ""
    email: str = ""
    api_token: str = ""
    # Space keys (or space or page URLs): as many as the admin needs, each its own scope with its own cursor.
    space_keys: KeyList = Field(default_factory=list)
    page_size: int = 25
    fetch_version_history: bool = True
    version_history_limit: int = 50
    # Requests per second this service allows itself against the source (conservative; check the vendor limit).
    requests_per_second: float = 5.0

    def _check(self) -> list[str]:
        out = self._required("base_url", "email", "api_token", "space_keys")
        if self.base_url and not is_http_url(self.base_url):
            out.append(f"{self._env('base_url')} must be an http(s) URL")
        out += [f"{self._env('space_keys')}: {p}" for s in self.space_keys if (p := confluence_scope_problem(s))]
        return out


class GitHubSettings(_Source):
    model_config = SettingsConfigDict(env_prefix="USEP_INGESTION_GITHUB_")
    _fields: ClassVar[tuple[str, ...]] = ("token", "repositories", "all_member_projects")

    # https://api.github.com, or https://<host>/api/v3 for GitHub Enterprise.
    base_url: str = "https://api.github.com"
    token: str = ""
    # owner/repo, links, or SSH links: as many as the admin works in.
    repositories: KeyList = Field(default_factory=list)
    # Also read every repository the token's user can reach (archived ones skipped). Off by default for the same
    # reason as GitLab: it can pull in repositories nobody approved.
    all_member_projects: bool = False
    max_member_projects: int = 500
    page_size: int = 50
    requests_per_second: float = 10.0

    def _check(self) -> list[str]:
        out = self._required("base_url", "token")
        if self.base_url and not is_http_url(self.base_url):
            out.append(f"{self._env('base_url')} must be an http(s) URL")
        if not (self.repositories or self.all_member_projects):
            out.append(f"give {self._env('repositories')} or set {self._env('all_member_projects')}=true")
        out += [f"{self._env('repositories')}: {p}" for s in self.repositories if (p := github_scope_problem(s))]
        return out


class ServiceNowSettings(_Source):
    model_config = SettingsConfigDict(env_prefix="USEP_INGESTION_SERVICENOW_")
    _fields: ClassVar[tuple[str, ...]] = ("username", "password", "tables")

    base_url: str = ""  # https://<instance>.service-now.com
    username: str = ""
    password: str = ""
    # Tables to read, each its own scope: incident, change_request, problem, ...
    tables: KeyList = Field(default_factory=list)
    # Optional encoded query that narrows every table, for example active=true^priority<=2.
    query: str = ""
    page_size: int = 100
    requests_per_second: float = 5.0

    def _check(self) -> list[str]:
        out = self._required("base_url", "username", "password", "tables")
        if self.base_url and not is_http_url(self.base_url):
            out.append(f"{self._env('base_url')} must be an http(s) URL")
        out += [f"{self._env('tables')}: {p}" for t in self.tables if (p := servicenow_table_problem(t))]
        return out


class FigmaSettings(_Source):
    model_config = SettingsConfigDict(env_prefix="USEP_INGESTION_FIGMA_")
    _fields: ClassVar[tuple[str, ...]] = ("access_token", "file_keys")

    base_url: str = "https://api.figma.com"
    access_token: str = ""
    # File keys or file URLs; a URL with ?node-id=... limits the pull to those pages/frames.
    file_keys: KeyList = Field(default_factory=list)
    # ADR-025 / open item O-05: no live Figma data before the DPIA is signed off. A selected Figma stays off until true.
    dpia_approved: bool = False
    export_format: str = "png"
    download_exports: bool = False
    export_max_bytes: int = 10_485_760
    # Requests per second this service allows itself against the source (conservative; check the vendor limit).
    requests_per_second: float = 1.0

    def _check(self) -> list[str]:
        return self._required("access_token", "file_keys")


class SchedulerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="USEP_INGESTION_SCHEDULER_")

    enabled: bool = True
    jira_interval_minutes: int = 30
    gitlab_interval_minutes: int = 30
    confluence_interval_minutes: int = 60
    figma_interval_minutes: int = 60
    github_interval_minutes: int = 30
    servicenow_interval_minutes: int = 30
    # Optional per-scope override: {"<source>:<scope>": minutes}, e.g. {"jira:project = ABC": 10}.
    scope_interval_minutes: dict[str, int] = Field(default_factory=dict)
    # Random delay added to each run so per-scope jobs don't all hit a source at once.
    jitter_seconds: int = 60
    # How often to look again for scopes that appear on their own (GitLab repositories the token's user joins).
    scope_refresh_minutes: int = 60


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="USEP_INGESTION_", extra="ignore")

    database_url: str = "postgresql+asyncpg://usep:usep@localhost:5432/usep_ingestion"
    log_level: str = "INFO"
    output_dir: str = "output"
    # For checking while S3 is not connected: also write every run, with its documents, as readable JSON under
    # ``output_dir``. Documents the writer quarantined are left out, but the files are not encrypted, so turn this
    # off before real data. ``output/`` is git-ignored.
    json_sink_enabled: bool = True

    # Single-tenant pilot: every row, key and event carries this id. Required; the service will not start without it.
    tenant_id: UUID | None = None
    # Admin console (the UI's API). Fail closed: with no admin credentials set, nobody can sign in.
    admin_username: str = ""
    admin_password: str = ""
    session_ttl_hours: int = 8
    # Hosts typed into the console. Private or internal hosts are refused unless this is true (an on-prem Jira or
    # GitLab); allowed_source_hosts, when set, is the only list of hosts the console will call.
    allow_private_source_hosts: bool = False
    allowed_source_hosts: KeyList = Field(default_factory=list)

    # Read-only SSH access for GitHub and GitLab repositories (an admin may give an SSH key instead of a token). The
    # server must know the hosts' keys: with neither of these set, SSH access is refused (never "trust whoever answers").
    ssh_known_hosts: str = ""
    ssh_known_hosts_file: str = ""

    # Where raw objects land, encrypted: ``file`` (a folder under ``output_dir``, for checking now) or ``s3``.
    raw_store: Literal["file", "s3"] = "file"
    raw_store_dir: str = ""  # default: <output_dir>/raw
    # Where the audit trail lands: ``file`` (JSON lines under ``audit_dir``, kept in the repo's output folder for now),
    # ``postgres`` (the append-only audit_event table) or ``s3`` (one object per event, needs the s3 settings below).
    audit_store: Literal["file", "postgres", "s3"] = "file"
    audit_dir: str = ""  # default: <output_dir>/audit
    # Used when raw_store is ``s3`` (boto3 finds credentials the usual way: environment or role).
    s3_bucket: str = ""
    s3_region: str = "us-east-1"
    # Overlap window re-read on every run to absorb clock skew; the writer drops the duplicates (LLD 2.1).
    cursor_overlap_seconds: int = 300
    # DEVELOPMENT ONLY: base64 of a 32-byte key-encryption key, until Vault or KMS is chosen (open item O-04).
    dev_kek_b64: str = ""
    # Bearer token every /sync and /results call must send. Value comes from the environment or Vault.
    api_token: str = ""
    # Local development only: serve /sync and /results without a token.
    auth_disabled: bool = False
    @field_validator("tenant_id", mode="before")
    @classmethod
    def _blank_tenant_is_missing(cls, value: object) -> object:
        return value or None  # an empty line in .env should give the "missing setting" message

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000", "http://localhost:5173"])

    ado: AdoSettings = Field(default_factory=AdoSettings)


    jira: JiraSettings = Field(default_factory=JiraSettings)
    gitlab: GitLabSettings = Field(default_factory=GitLabSettings)
    github: GitHubSettings = Field(default_factory=GitHubSettings)
    servicenow: ServiceNowSettings = Field(default_factory=ServiceNowSettings)
    confluence: ConfluenceSettings = Field(default_factory=ConfluenceSettings)
    figma: FigmaSettings = Field(default_factory=FigmaSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)


SOURCES = ("ado", "jira", "confluence", "gitlab", "github", "servicenow", "figma")


def source_problems(settings: Settings) -> dict[str, list[str]]:
    """What is missing or wrong for each source the admin selected. A source nobody selected is never listed."""
    return {name: found for name in SOURCES if (found := getattr(settings, name).problems())}


def enabled_sources(settings: Settings) -> list[str]:
    return [name for name in SOURCES if getattr(settings, name).enabled]


def get_settings() -> Settings:
    return Settings()
