from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from common.source_document import SourceDocument


class GitFileChange(BaseModel):
    status: str  # A, M, D, R...
    path: str


class GitCommitDocument(SourceDocument):
    """One commit read straight from the repository (SSH access, no hosting-platform API)."""

    repository: str
    sha: str
    author: str | None = None
    committed_at: datetime | None = None
    message: str
    files: list[GitFileChange] = []
