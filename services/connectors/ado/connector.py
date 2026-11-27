"""Connector for Azure DevOps: work items, pull requests and repositories."""

from __future__ import annotations

from datetime import UTC, datetime

from common.client_base import ClientRuntime
from common.connector_base import ObjectError, ScopeFetch, SourceCheck
from common.source_document import SourceDocument, SourceType

from .client import AdoClient
from .models import AdoPullRequest, AdoRepository, AdoWorkItem

# The work items batch-get endpoint accepts at most this many ids per call.
_WORK_ITEM_BATCH = 200


class AdoConnector:
    def __init__(
        self,
        client: AdoClient,
        base_url: str,
        project_names: list[str],
        page_size: int = 100,
    ) -> None:
        self.client = client
        self.base_url = base_url
        self._projects = project_names
        self.page_size = page_size

    @property
    def scopes(self) -> list[str]:
        return self._projects

    async def check(self) -> SourceCheck:
        try:
            projects = await self.client.list_projects()
            project_names = {p["name"] for p in projects}
            missing = [p for p in self._projects if p not in project_names]
            if missing:
                return SourceCheck(ok=False, detail=f"Projects not found: {', '.join(missing)}")
            return SourceCheck(ok=True, detail=f"Found {len(self._projects)} project(s)")
        except Exception as exc:
            return SourceCheck(ok=False, detail=str(exc))

    async def refresh_scopes(self) -> None:
        """ADO scopes are project names and are static; nothing to refresh."""
        pass

    # shortcut: every run re-reads every work item, repository and pull request in the project; cursor is accepted
    # but not used for incremental filtering yet. Upgrade if a project's full size makes that too slow.
    async def fetch_scope(self, scope: str, cursor: str | None) -> ScopeFetch:
        documents: list[SourceDocument] = []
        errors: list[ObjectError] = []

        try:
            ids = await self.client.list_work_item_ids(scope)
        except Exception as exc:
            errors.append(ObjectError(scope=scope, object_id="work-items", error=str(exc)))
            ids = []

        for start in range(0, len(ids), _WORK_ITEM_BATCH):
            batch = ids[start : start + _WORK_ITEM_BATCH]
            try:
                items = await self.client.get_work_items_batch(scope, batch)
            except Exception as exc:
                errors.append(ObjectError(scope=scope, object_id=f"work-items[{start}:{start + len(batch)}]", error=str(exc)))
                continue
            for item in items:
                item_id = item.get("id")
                try:
                    fields = item.get("fields", {})
                    documents.append(AdoWorkItem(
                        source=SourceType.ADO,
                        source_type="work_item",
                        source_object_id=str(item_id),
                        source_url=f"{self.base_url}/{scope}/_workitems/edit/{item_id}",
                        retrieved_at=datetime.now(UTC),
                        raw_payload=item,
                        scope=scope,
                        source_version=fields.get("System.ChangedDate", ""),
                        acl={"project": scope},
                        title=fields.get("System.Title", f"Work item {item_id}"),
                        content=fields.get("System.Description", "") or "",
                    ))
                except Exception as exc:
                    errors.append(ObjectError(scope=scope, object_id=str(item_id), error=str(exc)))

        try:
            repos = await self.client.list_repositories(scope)
        except Exception as exc:
            errors.append(ObjectError(scope=scope, object_id="repositories", error=str(exc)))
            repos = []

        for repo in repos:
            repo_id = repo.get("id")
            repo_name = repo.get("name", str(repo_id))
            try:
                documents.append(AdoRepository(
                    source=SourceType.ADO,
                    source_type="repository",
                    source_object_id=str(repo_id),
                    source_url=repo.get("webUrl", f"{self.base_url}/{scope}/_git/{repo_name}"),
                    retrieved_at=datetime.now(UTC),
                    raw_payload=repo,
                    scope=scope,
                    source_version=repo.get("defaultBranch", "") or "",
                    acl={"project": scope},
                    title=repo_name,
                ))
            except Exception as exc:
                errors.append(ObjectError(scope=scope, object_id=f"repo:{repo_id}", error=str(exc)))

            try:
                pulls = await self.client.list_pull_requests(scope, repo_id)
            except Exception as exc:
                errors.append(ObjectError(scope=scope, object_id=f"repo:{repo_id}#pulls", error=str(exc)))
                continue
            for pr in pulls:
                pr_id = pr.get("pullRequestId")
                try:
                    documents.append(AdoPullRequest(
                        source=SourceType.ADO,
                        source_type="pull_request",
                        source_object_id=str(pr_id),
                        source_url=f"{self.base_url}/{scope}/_git/{repo_name}/pullrequest/{pr_id}",
                        retrieved_at=datetime.now(UTC),
                        raw_payload=pr,
                        scope=scope,
                        source_version=(pr.get("lastMergeCommit") or {}).get("commitId", ""),
                        acl={"project": scope},
                        title=pr.get("title", f"Pull request {pr_id}"),
                        content=pr.get("description", "") or "",
                    ))
                except Exception as exc:
                    errors.append(ObjectError(scope=scope, object_id=f"repo:{repo_id}#pr:{pr_id}", error=str(exc)))

        return ScopeFetch(documents=documents, errors=errors)
