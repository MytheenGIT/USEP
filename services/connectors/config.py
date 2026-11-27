from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class JiraSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="USEP_INGESTION_JIRA_")

    base_url: str = ""
    email: str = ""
    api_token: str = ""
    jql: str = "order by updated asc"
    # One scope per query (spec Module 1: one or more JQL queries). Empty means [jql].
    jql_queries: list[str] = Field(default_factory=list)
    page_size: int = 50
    download_attachments: bool = True
    # LLD Table 13, Q-SIZE: files over 1 MB are not stored; metadata is kept.
    attachment_max_bytes: int = 1_048_576
    # One extra call per issue for its remote links (native Jira to Confluence links). Turn off to save API calls.
    fetch_remote_links: bool = True


class GitLabSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="USEP_INGESTION_GITLAB_")

    base_url: str = "https://gitlab.com"
    private_token: str = ""
    # Numeric ids, "group/project" paths, or repository URLs.
    project_ids: list[str] = Field(default_factory=list)
    page_size: int = 50


class ConfluenceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="USEP_INGESTION_CONFLUENCE_")

    base_url: str = "https://example.atlassian.net"
    email: str = ""
    api_token: str = ""
    space_keys: list[str] = Field(default_factory=list)
    page_size: int = 25
    fetch_version_history: bool = True
    version_history_limit: int = 50


class FigmaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="USEP_INGESTION_FIGMA_")

    base_url: str = "https://api.figma.com"
    access_token: str = ""
    # File keys or file URLs; a URL with ?node-id=... limits the pull to those pages/frames.
    file_keys: list[str] = Field(default_factory=list)
    export_format: str = "png"
    download_exports: bool = False
    export_max_bytes: int = 10_485_760


class GitHubSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="USEP_INGESTION_GITHUB_")

    base_url: str = "https://api.github.com"        # GitHub Enterprise Server: https://<host>/api/v3
    web_url: str = "https://github.com"
    token: str = ""
    repos: list[str] = Field(default_factory=list)   # owner/name
    page_size: int = 50


class ServiceNowSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="USEP_INGESTION_SERVICENOW_")

    instance_url: str = ""                           # https://<instance>.service-now.com
    username: str = ""
    password: str = ""
    tables: list[str] = Field(default_factory=lambda: ["incident", "change_request"])
    page_size: int = 100


class AdoSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="USEP_INGESTION_ADO_")

    organization_url: str = ""                       # https://dev.azure.com/<org>
    pat: str = ""
    projects: list[str] = Field(default_factory=list)
    page_size: int = 100


class SchedulerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="USEP_INGESTION_SCHEDULER_")

    enabled: bool = True
    jira_interval_minutes: int = 30
    gitlab_interval_minutes: int = 30
    confluence_interval_minutes: int = 60
    figma_interval_minutes: int = 60
    # Optional per-scope override: {"<source>:<scope>": minutes}, e.g. {"jira:project = ABC": 10}.
    scope_interval_minutes: dict[str, int] = Field(default_factory=dict)
    # Random delay added to each run so per-scope jobs don't all hit a source at once.
    jitter_seconds: int = 60
    github_interval_minutes: int = 30
    servicenow_interval_minutes: int = 30
    ado_interval_minutes: int = 30


class S3Settings(BaseSettings):
    """Raw store, cursor store and event bus on S3. Leave ``bucket`` empty to run on the non-durable dev stubs.
    Credentials come from the workload identity (default AWS credential chain), never from these settings."""

    model_config = SettingsConfigDict(env_prefix="USEP_INGESTION_S3_")

    bucket: str = ""
    region: str = ""
    endpoint_url: str = ""          # for MinIO / on-prem S3-compatible storage
    raw_prefix: str = "raw"
    cursor_prefix: str = "state/connectors"
    index_prefix: str = "state/index"
    bus_prefix: str = "bus"
    bus_partitions: int = 16


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="USEP_INGESTION_", extra="ignore")

    database_url: str = "postgresql+asyncpg://usep:usep@localhost:5432/usep_ingestion"
    log_level: str = "INFO"
    output_dir: str = "output"
    # Bearer token every /sync and /results call must send. Value comes from the environment or Vault.
    api_token: str = ""
    # Local development only: serve /sync and /results without a token.
    auth_disabled: bool = False
    # Backfill: where a scope with no stored cursor starts (ISO 8601 UTC). Empty means everything.
    backfill_since: str = ""
    # Land at most this many objects per scope per run (oldest first), so a large first sync resumes over several runs.
    # 0 means no cap.
    max_documents_per_scope: int = 0
    # Reconciliation refuses a scope where more than this share of known objects is missing (looks like an auth problem).
    reconcile_max_missing_fraction: float = 0.3
    tenant_id: str = ""             # required when s3.bucket is set: tenant id is in every event (ADR-10)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000", "http://localhost:5173"])

    jira: JiraSettings = Field(default_factory=JiraSettings)
    gitlab: GitLabSettings = Field(default_factory=GitLabSettings)
    confluence: ConfluenceSettings = Field(default_factory=ConfluenceSettings)
    figma: FigmaSettings = Field(default_factory=FigmaSettings)
    github: GitHubSettings = Field(default_factory=GitHubSettings)
    servicenow: ServiceNowSettings = Field(default_factory=ServiceNowSettings)
    ado: AdoSettings = Field(default_factory=AdoSettings)
    s3: S3Settings = Field(default_factory=S3Settings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)


def get_settings() -> Settings:
    import os

    import sources_file
    settings = Settings()
    return sources_file.apply(settings, sources_file.load(os.environ.get("USEP_SOURCES_FILE", "config/sources.yaml")))
