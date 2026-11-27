from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from common.source_document import SourceDocument


class GitHubCommit(BaseModel):
    sha: str
    author: str | None = None
    authored_at: datetime | None = None
    message: str
    raw: dict[str, Any]


class GitHubReview(BaseModel):
    review_id: str
    reviewer: str | None = None
    state: str
    submitted_at: datetime | None = None
    raw: dict[str, Any]


class GitHubDocument(SourceDocument):
    """A pull request (source_type 'pull_request') or a repository ('repository')."""

    repo: str                                   # owner/name
    number: int | None = None
    state: str | None = None                    # opened | merged | closed (same words as GitLab, for one mapping)
    labels: list[str] = []
    private: bool | None = None
    commits: list[GitHubCommit] = []
    reviews: list[GitHubReview] = []
