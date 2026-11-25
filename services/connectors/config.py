from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class JiraSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="USEP_INGESTION_JIRA_")

    base_url: str = ""
    email: str = ""
    api_token: str = ""
    jql: str = "order by updated asc"
    page_size: int = 50


class GitLabSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="USEP_INGESTION_GITLAB_")

    base_url: str = "https://gitlab.com"
    private_token: str = ""
    project_ids: list[str] = Field(default_factory=list)
    page_size: int = 50


class ConfluenceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="USEP_INGESTION_CONFLUENCE_")

    base_url: str = "https://example.atlassian.net"
    email: str = ""
    api_token: str = ""
    space_keys: list[str] = Field(default_factory=list)
    page_size: int = 25


class FigmaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="USEP_INGESTION_FIGMA_")

    base_url: str = "https://api.figma.com"
    access_token: str = ""
    file_keys: list[str] = Field(default_factory=list)


class SchedulerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="USEP_INGESTION_SCHEDULER_")

    enabled: bool = True
    jira_interval_minutes: int = 30
    gitlab_interval_minutes: int = 30
    confluence_interval_minutes: int = 60
    figma_interval_minutes: int = 60


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="USEP_INGESTION_", extra="ignore")

    database_url: str = "postgresql+asyncpg://usep:usep@localhost:5432/usep_ingestion"
    log_level: str = "INFO"
    output_dir: str = "output"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000", "http://localhost:5173"])

    jira: JiraSettings = Field(default_factory=JiraSettings)
    gitlab: GitLabSettings = Field(default_factory=GitLabSettings)
    confluence: ConfluenceSettings = Field(default_factory=ConfluenceSettings)
    figma: FigmaSettings = Field(default_factory=FigmaSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)


def get_settings() -> Settings:
    return Settings()
