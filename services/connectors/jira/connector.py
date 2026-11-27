"""Jira connector: one scope per JQL query.

The admin gives JQL queries, project keys, or both. Each project key becomes the query for that
whole project, so several projects are several scopes with a cursor each. With neither, there are no
scopes: nothing is read, and the service refuses to start with Jira selected (``Settings.source_problems``).

Incremental fetch adds ``updated >= "<cursor>"`` to the query. JQL date
literals have minute precision and are read in the API user's time zone,
so the UTC cursor is converted to that zone first. Because ``>=`` on a
minute boundary re-returns issues from that minute, issues older than the
cursor are dropped before any further calls.

Comments and changelog embedded in the search response are capped by Jira;
when they are truncated the full lists are paged from their own endpoints.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import structlog

from common.binary_store import BinaryStore
from common.client_base import PayloadTooLarge
from common.client_base import error_detail
from common.connector_base import ObjectError, ScopeCheck, ScopeFetch, SourceCheck
from common.scopes import jira_project_scope
from common.source_document import SourceType, hash_payload
from common.timeutil import parse_ts, to_utc_iso
from jira.adf import adf_to_markdown
from jira.client import JiraClient
from jira.models import JiraAttachmentMeta, JiraChangelogEntry, JiraComment, JiraDocument

logger = structlog.get_logger(__name__)

_ORDER_BY = re.compile(r"\border\s+by\b", re.IGNORECASE)


def split_order_by(jql: str) -> tuple[str, str]:
    """Split ``jql`` into (filter, order clause). The order clause keeps its ``ORDER BY`` prefix."""
    match = _ORDER_BY.search(jql)
    if not match:
        return jql.strip(), ""
    return jql[: match.start()].strip(), jql[match.start() :].strip()


def build_scopes(jql: str, jql_queries: list[str], project_keys: list[str]) -> list[str]:
    """Every query to run: the free-form JQL queries, then one per project key, without repeats."""
    candidates = [*jql_queries, *([jql] if jql.strip() else []), *(jira_project_scope(k) for k in project_keys)]
    return list(dict.fromkeys(q.strip() for q in candidates if q.strip()))


class JiraConnector:
    source = SourceType.JIRA

    def __init__(
        self,
        client: JiraClient,
        base_url: str,
        jql_queries: list[str] | None = None,
        base_url_for_links: str | None = None,
        page_size: int = 50,
        binary_store: BinaryStore | None = None,
        download_attachments: bool = True,
        attachment_max_bytes: int = 1_048_576,
        fetch_remote_links: bool = False,
    ) -> None:
        self._client = client
        self._queries = list(dict.fromkeys(q.strip() for q in (jql_queries or []) if q.strip()))
        self._base_url = (base_url_for_links or base_url).rstrip("/")
        self._page_size = page_size
        self._binary_store = binary_store
        self._fetch_remote_links = fetch_remote_links
        self._download_attachments = download_attachments and binary_store is not None
        self._attachment_max_bytes = attachment_max_bytes
        self._user_tz: ZoneInfo | None = None
        self._user_tz_known = False

    @property
    def scopes(self) -> list[str]:
        return list(self._queries)

    async def check(self) -> SourceCheck:
        """Credentials, then every query run for one issue (Jira rejects a bad JQL or an unknown project)."""
        try:
            await self._client.get_myself()
        except Exception as exc:  # noqa: BLE001 -- reported, not raised
            return SourceCheck(ok=False, detail=f"cannot sign in: {error_detail(exc)}")
        results = []
        for scope in self._queries:
            try:
                await self._client.search_issues(await self.build_jql(scope, None), max_results=1, fields=["summary"])
                results.append(ScopeCheck(scope=scope, ok=True, detail="query accepted"))
            except Exception as exc:  # noqa: BLE001
                results.append(ScopeCheck(scope=scope, ok=False, detail=error_detail(exc)))
        return SourceCheck(ok=all(r.ok for r in results), detail="signed in", scopes=results)

    # ----- JQL -------------------------------------------------------------

    async def _jql_cursor_literal(self, cursor: str) -> str:
        """Cursor as a JQL date literal ``yyyy-MM-dd HH:mm`` in the API user's time zone."""
        cursor_dt = parse_ts(cursor)
        assert cursor_dt is not None
        if not self._user_tz_known:
            try:
                tz_name = (await self._client.get_myself()).get("timeZone")
                self._user_tz = ZoneInfo(tz_name) if tz_name else None
            except Exception as exc:  # noqa: BLE001 -- includes ZoneInfoNotFoundError
                logger.warning("jira.timezone_lookup_failed", error=str(exc))
                self._user_tz = None
            self._user_tz_known = True
        if self._user_tz is None:
            # Unknown zone: step back a full day so no offset (max 14 h) can skip updates.
            return (cursor_dt - timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
        return cursor_dt.astimezone(self._user_tz).strftime("%Y-%m-%d %H:%M")

    async def build_jql(self, scope: str, cursor: str | None) -> str:
        where, order = split_order_by(scope)
        order = order or "ORDER BY updated ASC"
        if cursor:
            clause = f'updated >= "{await self._jql_cursor_literal(cursor)}"'
            where = f"({where}) AND {clause}" if where else clause
        return f"{where} {order}".strip()

    # ----- normalization ----------------------------------------------------

    async def _comments(self, issue_key: str, block: dict[str, Any]) -> list[dict[str, Any]]:
        embedded = block.get("comments", []) or []
        if block.get("total", len(embedded)) > len(embedded):
            return await self._client.get_all_comments(issue_key)
        return embedded

    async def _histories(self, issue_key: str, block: dict[str, Any]) -> list[dict[str, Any]]:
        embedded = block.get("histories", []) or []
        if block.get("total", len(embedded)) > len(embedded):
            return await self._client.get_all_changelog(issue_key)
        return embedded

    async def _attachment(
        self, issue_key: str, version: str | None, raw: dict[str, Any], scope: str, errors: list[ObjectError]
    ) -> JiraAttachmentMeta:
        meta = JiraAttachmentMeta(
            attachment_id=str(raw["id"]),
            filename=raw.get("filename", ""),
            mime_type=raw.get("mimeType"),
            size_bytes=raw.get("size"),
            url=raw.get("content", ""),
            created_at=raw.get("created"),
        )
        if not self._download_attachments or not meta.url:
            meta.skipped_reason = "disabled"
            return meta
        if meta.size_bytes is not None and meta.size_bytes > self._attachment_max_bytes:
            meta.skipped_reason = "Q-SIZE"
            return meta
        assert self._binary_store is not None
        key = f"jira/{issue_key}/{meta.attachment_id}/{meta.filename}"
        # Attachment ids are immutable, so an already stored binary is never fetched again.
        existing = self._binary_store.exists(key)
        if existing:
            meta.stored_ref = existing
            return meta
        try:
            data = await self._client.download_attachment(meta.url, self._attachment_max_bytes)
            meta.stored_ref, meta.content_hash = self._binary_store.put(key, data)
        except PayloadTooLarge:
            meta.skipped_reason = "Q-SIZE"
        except Exception as exc:  # noqa: BLE001
            meta.skipped_reason = "download_failed"
            errors.append(
                ObjectError(
                    scope=scope,
                    object_id=f"{issue_key}/attachment/{meta.attachment_id}",
                    source_version=version,
                    error=f"attachment download failed: {exc}",
                )
            )
        return meta

    async def _normalize_issue(self, scope: str, issue: dict[str, Any], errors: list[ObjectError]) -> JiraDocument:
        key = issue["key"]
        fields = issue.get("fields", {}) or {}
        version = to_utc_iso(fields.get("updated"))

        raw_comments = await self._comments(key, fields.get("comment") or {})
        raw_histories = await self._histories(key, issue.get("changelog") or {})

        comments = [
            JiraComment(
                comment_id=str(c["id"]),
                author=(c.get("author") or {}).get("displayName"),
                body=adf_to_markdown(c.get("body")),
                created_at=c.get("created"),
                updated_at=c.get("updated"),
                raw=c,
            )
            for c in raw_comments
        ]
        changelog = [
            JiraChangelogEntry(
                change_id=str(history["id"]),
                author=(history.get("author") or {}).get("displayName"),
                created_at=history.get("created"),
                field=item.get("field", ""),
                from_value=item.get("fromString"),
                to_value=item.get("toString"),
                raw=history,
            )
            for history in raw_histories
            for item in history.get("items", [])
        ]
        attachments = [
            await self._attachment(key, version, a, scope, errors) for a in (fields.get("attachment") or [])
        ]

        description = adf_to_markdown(fields.get("description"))
        project = fields.get("project") or {}
        security = fields.get("security") or {}
        status = (fields.get("status") or {}).get("name", "")
        # Raw payload carries the complete comment and changelog lists, not the truncated embedded ones.
        raw_payload = {**issue, "comments_all": raw_comments, "changelog_all": raw_histories}
        if self._fetch_remote_links:
            raw_payload["remote_links"] = await self._client.get_remote_links(key)

        return JiraDocument(
            source=self.source,
            source_type="issue",
            source_object_id=key,
            source_url=f"{self._base_url}/browse/{key}",
            retrieved_at=datetime.now(UTC),
            raw_payload=raw_payload,
            scope=scope,
            source_version=version,
            content_hash=hash_payload(raw_payload),
            acl={"project_key": project.get("key"), "security_level": security.get("name")},
            title=fields.get("summary", "") or "",
            content=description,
            metadata={"status": status, "updated": version},
            issue_key=key,
            summary=fields.get("summary", "") or "",
            description=description or None,
            status=status,
            priority=(fields.get("priority") or {}).get("name"),
            issue_type=(fields.get("issuetype") or {}).get("name"),
            project_key=project.get("key"),
            labels=list(fields.get("labels") or []),
            components=[c.get("name", "") for c in fields.get("components") or []],
            fix_versions=[v.get("name", "") for v in fields.get("fixVersions") or []],
            parent_key=(fields.get("parent") or {}).get("key"),
            resolution=(fields.get("resolution") or {}).get("name"),
            created_at=fields.get("created"),
            updated_at=fields.get("updated"),
            comments=comments,
            changelog=changelog,
            attachments=attachments,
        )

    async def list_ids(self, scope: str) -> set[str]:
        """Every issue key the scope's query matches right now (for delete reconciliation). Keys only: no comments,
        no changelog."""
        jql = await self.build_jql(scope, None)
        issues = await self._client.search_issues_paginated(jql, page_size=self._page_size, fields=["summary"],
                                                            expand=["names"])
        return {i["key"] for i in issues}

    async def fetch_scope(self, scope: str, cursor: str | None) -> ScopeFetch:
        jql = await self.build_jql(scope, cursor)
        raw_issues = await self._client.search_issues_paginated(jql, page_size=self._page_size)

        documents: list[JiraDocument] = []
        errors: list[ObjectError] = []
        for issue in raw_issues:
            version = to_utc_iso(((issue.get("fields") or {}).get("updated")))
            if cursor and version and version < cursor:
                continue  # re-returned only because JQL rounds to the minute
            try:
                documents.append(await self._normalize_issue(scope, issue, errors))
            except Exception as exc:  # noqa: BLE001 -- one bad issue must not fail the scope
                errors.append(ObjectError(scope=scope, object_id=issue.get("key"), source_version=version, error=str(exc)))
        return ScopeFetch(documents=documents, errors=errors)
