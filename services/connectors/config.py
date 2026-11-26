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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="USEP_INGESTION_", extra="ignore")

    database_url: str = "postgresql+asyncpg://usep:usep@localhost:5432/usep_ingestion"
    log_level: str = "INFO"
    output_dir: str = "output"
    # Bearer token every /sync and /results call must send. Value comes from the environment or Vault.
    api_token: str = ""
    # Local development only: serve /sync and /results without a token.
    auth_disabled: bool = False
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000", "http://localhost:5173"])

    jira: JiraSettings = Field(default_factory=JiraSettings)
    gitlab: GitLabSettings = Field(default_factory=GitLabSettings)
    confluence: ConfluenceSettings = Field(default_factory=ConfluenceSettings)
    figma: FigmaSettings = Field(default_factory=FigmaSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)


def get_settings() -> Settings:
    return Settings()
