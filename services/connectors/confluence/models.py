from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from common.source_document import SourceDocument


class ConfluenceVersion(BaseModel):
    number: int
    author: str | None = None
    when: datetime | None = None
    message: str | None = None


class ConfluenceChildRef(BaseModel):
    """A reference to a child page, preserving hierarchy without inlining its body."""

    page_id: str
    title: str
    url: str


class ConfluenceDocument(SourceDocument):
    """Normalized Confluence page. Title/content/labels/version/children stay separate."""

    space_key: str
    page_id: str
    content: str = ""
    labels: list[str] = []
    version: ConfluenceVersion
    ancestors: list[ConfluenceChildRef] = []
    children: list[ConfluenceChildRef] = []
