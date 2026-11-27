"""GitLab connector: one scope per repository.

The admin can list repositories, ask for every repository the token's user is a member of, or both.
Discovered repositories are scopes by numeric project id (a rename does not change it) and are
refreshed by ``refresh_scopes``; one that is also listed explicitly is not read twice.

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

import structlog

from common.client_base import error_detail
from common.connector_base import ObjectError, ScopeCheck, ScopeFetch, SourceCheck
from common.scopes import repo_path_from_link
from common.source_document import SourceType
from common.timeutil import to_utc_iso
from gitlab.client import GitLabClient
from gitlab.models import GitLabApproval, GitLabCommit, GitLabDiff, GitLabDocument, GitLabNote


logger = structlog.get_logger(__name__)


def project_ref_from_scope(scope: str) -> str:
    """Numeric id or ``group/sub/project`` path from an id, path or repository URL."""
    value = scope.strip()
    if value.isdigit():
        return value
    return repo_path_from_link(value)


class GitLabConnector:
    source = SourceType.GITLAB

    def __init__(
        self,
        client: GitLabClient,
        project_ids: list[str],
        page_size: int = 100,
        mr_concurrency: int = 4,
        all_member_projects: bool = False,
        max_member_projects: int = 500,
    ) -> None:
        self._client = client
        self._explicit = list(dict.fromkeys(str(p).strip() for p in project_ids if str(p).strip()))
        self._page_size = page_size
        self._mr_concurrency = max(1, mr_concurrency)
        self._all_member_projects = all_member_projects
        self._max_member_projects = max_member_projects
        self._discovered: list[str] = []

    @property
    def scopes(self) -> list[str]:
        return [*self._explicit, *self._discovered]

    async def refresh_scopes(self) -> None:
        """Find every project the token's user is a member of. A failure keeps the previous list."""
        if not self._all_member_projects:
            return
        projects = await self._client.list_member_projects(self._max_member_projects)
        listed = {project_ref_from_scope(s).lower() for s in self._explicit}
        self._discovered = [
            str(p["id"])
            for p in projects
            if str(p["id"]) not in listed and str(p.get("path_with_namespace", "")).lower() not in listed
        ]
        if len(projects) >= self._max_member_projects:
            logger.warning("gitlab.member_projects_truncated", limit=self._max_member_projects)
        logger.info("gitlab.member_projects", discovered=len(self._discovered), listed=len(self._explicit))

    async def check(self) -> SourceCheck:
        """The token works, then every listed repository can be opened. Discovered ones are only counted:
        the token's membership list is what produced them, and opening each of up to hundreds would be a lot of calls."""
        try:
            await self._client.get_current_user()
            await self.refresh_scopes()
        except Exception as exc:  # noqa: BLE001
            return SourceCheck(ok=False, detail=f"cannot use the token: {error_detail(exc)}")
        results = []
        for scope in self._explicit:
            try:
                project = await self._client.get_project(project_ref_from_scope(scope))
                results.append(ScopeCheck(scope=scope, ok=True, detail=project.get("path_with_namespace", "found")))
            except Exception as exc:  # noqa: BLE001
                results.append(ScopeCheck(scope=scope, ok=False, detail=error_detail(exc)))
        ok = all(r.ok for r in results)
        found = f"{len(self._discovered)} more found from membership" if self._all_member_projects else "signed in"
        return SourceCheck(ok=ok, detail=found, scopes=results)

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
