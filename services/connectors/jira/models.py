from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from common.source_document import SourceDocument


class JiraComment(BaseModel):
    comment_id: str
    author: str | None = None
    body: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    raw: dict[str, Any]


class JiraChangelogEntry(BaseModel):
    change_id: str
    author: str | None = None
    created_at: datetime | None = None
    field: str
    from_value: str | None = None
    to_value: str | None = None
    raw: dict[str, Any]


class JiraAttachmentMeta(BaseModel):
    """Metadata + link only. Binaries are never downloaded (out of scope)."""

    attachment_id: str
    filename: str
    mime_type: str | None = None
    size_bytes: int | None = None
    url: str
    created_at: datetime | None = None


class JiraDocument(SourceDocument):
    """Normalized Jira issue. Comments and changelog stay separate fields."""

    issue_key: str
    summary: str
    description: str | None = None
    status: str
    priority: str | None = None
    comments: list[JiraComment] = []
    changelog: list[JiraChangelogEntry] = []
    attachments: list[JiraAttachmentMeta] = []
