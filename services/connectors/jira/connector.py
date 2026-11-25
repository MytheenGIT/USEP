"""Example Jira connector: JQL search + pagination + comments/changelog/attachments."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from jira.client import JiraClient
from jira.models import JiraAttachmentMeta, JiraChangelogEntry, JiraComment, JiraDocument
from common.source_document import SourceType


def _adf_to_text(value: Any) -> str:
    """Best-effort plain-text extraction from an Atlassian Document Format field."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts: list[str] = []
        if "text" in value:
            parts.append(str(value["text"]))
        for child in value.get("content", []):
            parts.append(_adf_to_text(child))
        return " ".join(p for p in parts if p)
    return str(value)


class JiraConnector:
    source = SourceType.JIRA

    def __init__(self, client: JiraClient, base_url: str, jql: str, base_url_for_links: str | None = None, page_size: int = 50) -> None:
        self._client = client
        self._jql = jql
        self._base_url = base_url_for_links or base_url
        self._page_size = page_size

    def _build_jql(self, cursor: str | None) -> str:
        if not cursor:
            return self._jql
        return f"({self._jql}) AND updated >= '{cursor}'"

    def _normalize_issue(self, issue: dict[str, Any]) -> JiraDocument:
        fields = issue.get("fields", {})
        comments_block = fields.get("comment", {}) or {}
        comments = [
            JiraComment(
                comment_id=str(c["id"]),
                author=(c.get("author") or {}).get("displayName"),
                body=_adf_to_text(c.get("body")),
                created_at=c.get("created"),
                updated_at=c.get("updated"),
                raw=c,
            )
            for c in comments_block.get("comments", [])
        ]

        changelog: list[JiraChangelogEntry] = []
        for history in issue.get("changelog", {}).get("histories", []):
            for item in history.get("items", []):
                changelog.append(
                    JiraChangelogEntry(
                        change_id=str(history["id"]),
                        author=(history.get("author") or {}).get("displayName"),
                        created_at=history.get("created"),
                        field=item.get("field", ""),
                        from_value=item.get("fromString"),
                        to_value=item.get("toString"),
                        raw=history,
                    )
                )

        attachments = [
            JiraAttachmentMeta(
                attachment_id=str(a["id"]),
                filename=a.get("filename", ""),
                mime_type=a.get("mimeType"),
                size_bytes=a.get("size"),
                url=a.get("content", ""),
                created_at=a.get("created"),
            )
            for a in fields.get("attachment", [])
        ]

        return JiraDocument(
            source=self.source,
            source_type="issue",
            source_object_id=issue["key"],
            source_url=f"{self._base_url}/browse/{issue['key']}",
            retrieved_at=datetime.now(UTC),
            raw_payload=issue,
            title=fields.get("summary", ""),
            content=_adf_to_text(fields.get("description")),
            metadata={"status": (fields.get("status") or {}).get("name"), "updated": fields.get("updated")},
            issue_key=issue["key"],
            summary=fields.get("summary", ""),
            description=_adf_to_text(fields.get("description")) or None,
            status=(fields.get("status") or {}).get("name", ""),
            priority=(fields.get("priority") or {}).get("name"),
            comments=comments,
            changelog=changelog,
            attachments=attachments,
        )

    async def fetch(self, cursor: str | None) -> tuple[list[JiraDocument], str | None]:
        jql = self._build_jql(cursor)
        raw_issues = await self._client.search_issues_paginated(jql, page_size=self._page_size)
        documents = [self._normalize_issue(issue) for issue in raw_issues]

        updated_values = [d.metadata.get("updated") for d in documents if d.metadata.get("updated")]
        new_cursor = max(updated_values) if updated_values else cursor
        return documents, new_cursor
