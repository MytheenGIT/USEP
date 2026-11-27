"""Wire shapes served to the UI. Must match ui/src/shared/api/types.ts. Nothing here ever carries a secret."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ConfigStatus = Literal["submitted", "processing", "ready", "failed"]
SourceState = Literal["pending", "success", "failed", "skipped"]
CredentialMode = Literal["provided", "server", "none"]


class LoginBody(BaseModel):
    username: str = Field(max_length=256)
    password: str = Field(max_length=1024)


class SessionOut(BaseModel):
    token: str
    username: str


class SourceStatus(BaseModel):
    source: str
    state: SourceState
    documents_count: int = 0
    detail: str | None = None


class ConnectorSummary(BaseModel):
    """What was configured for one connector. `credentials` says how it authenticates; the values are never kept here."""

    enabled: bool
    base_url: str | None = None
    email: str | None = None
    # Project keys (Jira), space keys (Confluence), repositories (GitLab) or files (Figma): as many as the admin gave.
    targets: list[str] = []
    jql_queries: list[str] = []  # Jira only: the admin's own JQL, each one a scope
    all_member_projects: bool = False  # GitLab and GitHub: also every repository the token's user can reach
    auth_method: str = "token"  # GitLab and GitHub: "token", or "ssh_key" (reads the commit history over SSH)
    encoded_query: str = ""  # ServiceNow only: an encoded query that narrows every table
    credentials: CredentialMode = "none"


class Configuration(BaseModel):
    id: str
    tenant_id: str
    name: str
    connectors: dict[str, ConnectorSummary]
    status: ConfigStatus
    status_detail: str | None = None
    created_at: str
    created_by: str
    sources: list[SourceStatus] = []


class ConnectorDefault(BaseModel):
    """What the server already holds for a connector, so the form can offer 'use server credentials'."""

    base_url: str | None = None
    credentials_configured: bool = False
    # Why this connector cannot be used at all right now (Figma until the DPIA is signed off), else null.
    blocked_reason: str | None = None
    # GitHub and GitLab: whether this server can read repositories over SSH (it needs its known hosts configured).
    ssh_available: bool = False


class ConnectionCheck(BaseModel):
    ok: bool
    message: str


class GraphNode(BaseModel):
    id: str
    concept: str
    name: str
    labels: list[str] = []
    properties: dict[str, Any] = {}
    source_system: str | None = None
    source_id: str | None = None
    confidence: float | None = None
    ontology_version: str | None = None


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    relation: str
    confidence: float
    evidence_ref: str | None = None
    source_system: str | None = None


class Graph(BaseModel):
    configuration_id: str
    generated_at: str
    ontology_version: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class RepositoryChoice(BaseModel):
    path: str
    name: str
    visibility: str | None = None
    description: str | None = None


class RepositoryList(BaseModel):
    """The repositories the token's user can reach, for choosing from. ``truncated`` is true when there were more."""

    repositories: list[RepositoryChoice]
    truncated: bool = False
