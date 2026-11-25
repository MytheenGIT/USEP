"""Example GitLab connector: merge requests + commits + notes + approvals + diffs."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from gitlab.client import GitLabClient
from gitlab.models import GitLabApproval, GitLabCommit, GitLabDiff, GitLabDocument, GitLabNote
from common.source_document import SourceType


class GitLabConnector:
    source = SourceType.GITLAB

    def __init__(self, client: GitLabClient, project_ids: list[str], page_size: int = 50) -> None:
        self._client = client
        self._project_ids = project_ids
        self._page_size = page_size

    def _normalize_mr(
        self,
        project_id: str,
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

        return GitLabDocument(
            source=self.source,
            source_type="merge_request",
            source_object_id=f"{project_id}!{mr['iid']}",
            source_url=mr.get("web_url", ""),
            retrieved_at=datetime.now(UTC),
            raw_payload=mr,
            title=mr.get("title", ""),
            content=mr.get("description") or "",
            metadata={"updated_at": mr.get("updated_at"), "state": mr.get("state")},
            project_id=str(project_id),
            mr_iid=str(mr["iid"]),
            description=mr.get("description"),
            state=mr.get("state", ""),
            commits=commits,
            discussions=discussions,
            approvals=approvals,
            diffs=diffs,
        )

    async def _fetch_project(self, project_id: str, cursor: str | None) -> list[GitLabDocument]:
        merge_requests = await self._client.list_merge_requests(
            project_id, updated_after=cursor, per_page=self._page_size
        )
        documents: list[GitLabDocument] = []
        for mr in merge_requests:
            iid = mr["iid"]
            commits, notes, approvals, diffs = await asyncio.gather(
                self._client.list_mr_commits(project_id, iid),
                self._client.list_mr_notes(project_id, iid),
                self._client.list_mr_approvals(project_id, iid),
                self._client.get_mr_diffs(project_id, iid),
            )
            documents.append(self._normalize_mr(project_id, mr, commits, notes, approvals, diffs))
        return documents

    async def fetch(self, cursor: str | None) -> tuple[list[GitLabDocument], str | None]:
        per_project = await asyncio.gather(*(self._fetch_project(pid, cursor) for pid in self._project_ids))
        documents = [doc for docs in per_project for doc in docs]

        updated_values = [d.metadata.get("updated_at") for d in documents if d.metadata.get("updated_at")]
        new_cursor = max(updated_values) if updated_values else cursor
        return documents, new_cursor
