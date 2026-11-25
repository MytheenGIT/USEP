from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from common.source_document import SourceDocument


class GitLabCommit(BaseModel):
    sha: str
    author: str | None = None
    authored_at: datetime | None = None
    message: str
    url: str
    raw: dict[str, Any]


class GitLabNote(BaseModel):
    """A merge request discussion note/comment."""

    note_id: str
    author: str | None = None
    body: str
    created_at: datetime | None = None
    system: bool = False
    raw: dict[str, Any]


class GitLabApproval(BaseModel):
    approver: str
    approved_at: datetime | None = None
    raw: dict[str, Any]


class GitLabDiff(BaseModel):
    old_path: str
    new_path: str
    diff: str
    new_file: bool = False
    renamed_file: bool = False
    deleted_file: bool = False


class GitLabDocument(SourceDocument):
    """Normalized GitLab merge request. Commits/discussions/diffs stay separate."""

    project_id: str
    mr_iid: str
    description: str | None = None
    state: str
    commits: list[GitLabCommit] = []
    discussions: list[GitLabNote] = []
    approvals: list[GitLabApproval] = []
    diffs: list[GitLabDiff] = []
