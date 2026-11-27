"""GitLab connector: one scope per configured repository.

A scope can be a numeric project id, a ``group/project`` path or a
repository URL. Every list (MRs, commits, notes, diffs) is paged to the
end, so large MRs are not silently truncated. The MR's sub-resource
responses are kept in ``raw_payload`` next to the MR itself, so the raw
landing holds everything needed to re-normalize later.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from common.connector_base import ObjectError, ScopeFetch
from common.source_document import SourceType
from common.timeutil import to_utc_iso
from gitlab.client import GitLabClient
from gitlab.models import GitLabApproval, GitLabCommit, GitLabDiff, GitLabDocument, GitLabNote


def project_ref_from_scope(scope: str) -> str:
    """Numeric id or ``group/sub/project`` path from an id, path or repository URL."""
    value = scope.strip()
    if value.isdigit():
        return value
    if "://" in value:
        value = urlparse(value).path
    value = value.strip("/")
    value = value.split("/-/", 1)[0]
    if value.endswith(".git"):
        value = value[:-4]
    return value


class GitLabConnector:
    source = SourceType.GITLAB

    def __init__(self, client: GitLabClient, project_ids: list[str], page_size: int = 100, mr_concurrency: int = 4) -> None:
        self._client = client
        self._scopes = [p for p in project_ids if str(p).strip()]
        self._page_size = page_size
        self._mr_concurrency = max(1, mr_concurrency)

    @property
    def scopes(self) -> list[str]:
        return list(self._scopes)

    def _normalize_mr(
        self,
        scope: str,
        project: dict[str, Any],
        mr: dict[str, Any],
        raw_commits: list[dict[str, Any]],
        raw_notes: list[dict[str, Any]],
        raw_approvals: dict[str, Any],
        raw_diffs: list[dict[str, Any]],
    ) -> GitLabDocument:
        commits = [
            GitLabCommit(
                sha=c["id"],
                author=c.get("author_name"),
                authored_at=c.get("authored_date"),
                message=c.get("message", ""),
                url=c.get("web_url", mr.get("web_url", "")),
                raw=c,
            )
            for c in raw_commits
        ]
        discussions = [
            GitLabNote(
                note_id=str(n["id"]),
                author=(n.get("author") or {}).get("username"),
                body=n.get("body", ""),
                created_at=n.get("created_at"),
                system=bool(n.get("system", False)),
                raw=n,
            )
            for n in raw_notes
        ]
        approvals = [
            GitLabApproval(
                approver=(a.get("user") or {}).get("username", ""),
                approved_at=a.get("approved_at"),
                raw=a,
            )
            for a in raw_approvals.get("approved_by", [])
        ]
        diffs = [
            GitLabDiff(
                old_path=d.get("old_path", ""),
                new_path=d.get("new_path", ""),
                diff=d.get("diff", ""),
                new_file=bool(d.get("new_file", False)),
                renamed_file=bool(d.get("renamed_file", False)),
                deleted_file=bool(d.get("deleted_file", False)),
            )
            for d in raw_diffs
        ]
        project_id = str(project["id"])
        version = to_utc_iso(mr.get("updated_at"))

        return GitLabDocument(
            source=self.source,
            source_type="merge_request",
            source_object_id=f"{project_id}!{mr['iid']}",
            source_url=mr.get("web_url", ""),
            retrieved_at=datetime.now(UTC),
            raw_payload={
                "merge_request": mr,
                "commits": raw_commits,
                "notes": raw_notes,
                "approvals": raw_approvals,
                "diffs": raw_diffs,
            },
            scope=scope,
            source_version=version,
            acl={"project_id": project_id, "project_path": project.get("path_with_namespace"), "visibility": project.get("visibility")},
            title=mr.get("title", ""),
            content=mr.get("description") or "",
            metadata={"updated_at": version, "state": mr.get("state"), "project_path": project.get("path_with_namespace")},
            project_id=project_id,
            project_path=project.get("path_with_namespace"),
            mr_iid=str(mr["iid"]),
            description=mr.get("description"),
            state=mr.get("state", ""),
            source_branch=mr.get("source_branch"),
            target_branch=mr.get("target_branch"),
            merged_at=mr.get("merged_at"),
            commits=commits,
            discussions=discussions,
            approvals=approvals,
            diffs=diffs,
        )

    async def _fetch_mr(self, scope: str, project: dict[str, Any], mr: dict[str, Any]) -> GitLabDocument:
        pid, iid = str(project["id"]), mr["iid"]
        commits, notes, approvals, diffs = await asyncio.gather(
            self._client.list_mr_commits(pid, iid),
            self._client.list_mr_notes(pid, iid),
            self._client.list_mr_approvals(pid, iid),
            self._client.get_mr_diffs(pid, iid),
        )
        return self._normalize_mr(scope, project, mr, commits, notes, approvals, diffs)

    async def list_ids(self, scope: str) -> set[str]:
        """Every merge request id in the project right now, in the same form documents use (for delete reconciliation)."""
        project = await self._client.get_project(project_ref_from_scope(scope))
        mrs = await self._client.list_merge_requests(str(project["id"]), per_page=self._page_size)
        return {f"{project['id']}!{mr['iid']}" for mr in mrs}

    async def fetch_scope(self, scope: str, cursor: str | None) -> ScopeFetch:
        project = await self._client.get_project(project_ref_from_scope(scope))
        merge_requests = await self._client.list_merge_requests(str(project["id"]), updated_after=cursor, per_page=self._page_size)

        semaphore = asyncio.Semaphore(self._mr_concurrency)

        async def one(mr: dict[str, Any]) -> GitLabDocument | ObjectError:
            async with semaphore:
                try:
                    return await self._fetch_mr(scope, project, mr)
                except Exception as exc:  # noqa: BLE001 -- one bad MR must not fail the scope
                    return ObjectError(
                        scope=scope,
                        object_id=f"{project['id']}!{mr.get('iid')}",
                        source_version=to_utc_iso(mr.get("updated_at")),
                        error=str(exc),
                    )

        results = await asyncio.gather(*(one(mr) for mr in merge_requests))
        return ScopeFetch(
            documents=[r for r in results if isinstance(r, GitLabDocument)],
            errors=[r for r in results if isinstance(r, ObjectError)],
        )
