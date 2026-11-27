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
    url: str
    raw: dict[str, Any]


class GitHubComment(BaseModel):
    """A comment on the pull request conversation, or a review comment on the diff."""

    comment_id: str
    author: str | None = None
    body: str
    created_at: datetime | None = None
    kind: str = "conversation"  # or "review_comment"
    path: str | None = None  # review comments: the file the comment is on
    raw: dict[str, Any]


class GitHubReview(BaseModel):
    reviewer: str | None = None
    state: str = ""  # APPROVED, CHANGES_REQUESTED, COMMENTED, ...
    body: str = ""
    submitted_at: datetime | None = None
    raw: dict[str, Any]


class GitHubFile(BaseModel):
    filename: str
    status: str = ""
    additions: int = 0
    deletions: int = 0
    patch: str = ""


class GitHubDocument(SourceDocument):
    """Normalized GitHub pull request. Commits, comments, reviews and files stay separate."""

    repository: str
    pr_number: str
    description: str | None = None
    state: str
    draft: bool = False
    base_branch: str | None = None
    head_branch: str | None = None
    merged_at: datetime | None = None
    commits: list[GitHubCommit] = []
    comments: list[GitHubComment] = []
    reviews: list[GitHubReview] = []
    files: list[GitHubFile] = []
