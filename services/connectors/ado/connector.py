"""Azure DevOps connector: one scope per project. Work items (-> Requirement / Change by type) and pull requests (-> Change).

Work items are incremental on System.ChangedDate. A pull request has no updated time in the API, so active PRs are
re-read each run (their snapshots are checksum-keyed, so an unchanged PR adds no new snapshot) and completed or
abandoned PRs are read by closed time since the cursor.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ado.client import AdoClient
from ado.models import AdoDocument
from common.connector_base import ObjectError, ScopeFetch
from common.source_document import SourceType
from common.timeutil import to_utc_iso

PR_STATE = {"active": "opened", "completed": "merged", "abandoned": "closed"}


def _chunks(seq: list[int], n: int):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


class AdoConnector:
    source = SourceType.ADO

    def __init__(self, client: AdoClient, organization_url: str, projects: list[str], page_size: int = 100) -> None:
        self._client, self._org, self._projects, self._page = client, organization_url.rstrip("/"), projects, page_size

    @property
    def scopes(self) -> list[str]:
        return [p for p in self._projects if p.strip()]

    def _wi_doc(self, project: str, wi: dict[str, Any]) -> AdoDocument:
        f = wi.get("fields", {})
        proj = f.get("System.TeamProject", project)
        version = to_utc_iso(f.get("System.ChangedDate"))
        return AdoDocument(
            scope=project, source_version=version, acl={"project": proj, "area_path": f.get("System.AreaPath")},
            source=self.source, source_type="work_item", source_object_id=f"{proj}#{wi['id']}",
            source_url=(wi.get("_links", {}).get("html", {}) or {}).get("href") or f"{self._org}/{proj}/_workitems/edit/{wi['id']}",
            retrieved_at=datetime.now(UTC), raw_payload=wi, title=f.get("System.Title", ""),
            content=f.get("System.Description") or "", metadata={"changed": version},
            project=proj, work_item_type=f.get("System.WorkItemType"), state=f.get("System.State"),
            labels=[t.strip() for t in (f.get("System.Tags") or "").split(";") if t.strip()],
            relation_count=len(wi.get("relations") or []))

    def _pr_doc(self, project: str, pr: dict[str, Any]) -> AdoDocument:
        repo = pr.get("repository", {}) or {}
        proj = (repo.get("project") or {}).get("name", project)
        state = PR_STATE.get(pr.get("status", ""), "closed")
        version = to_utc_iso(pr.get("closedDate") or pr.get("creationDate"))
        return AdoDocument(
            scope=project, source_version=version, acl={"project": proj, "repository": repo.get("name")},
            source=self.source, source_type="pull_request",
            source_object_id=f"ado:{proj}/{repo.get('name', '')}!{pr['pullRequestId']}",
            source_url=f"{repo.get('webUrl', self._org)}/pullrequest/{pr['pullRequestId']}", retrieved_at=datetime.now(UTC),
            raw_payload=pr, title=pr.get("title", ""), content=pr.get("description") or "",
            metadata={"changed": version, "state": state},
            project=proj, state=state, repository=repo.get("name"), labels=[l.get("name", "") for l in pr.get("labels", [])])

    async def _work_items(self, project: str, cursor: str | None) -> tuple[list[AdoDocument], list[ObjectError]]:
        ids = await self._client.wiql_ids(project, cursor)
        out: list[AdoDocument] = []
        errors: list[ObjectError] = []
        for chunk in _chunks(ids, 200):               # the batch endpoint takes at most 200 ids
            for wi in await self._client.work_items(chunk):
                try:
                    out.append(self._wi_doc(project, wi))
                except Exception as exc:              # noqa: BLE001 - one bad item must not fail the project
                    errors.append(ObjectError(scope=project, object_id=f"{project}#{wi.get('id')}",
                                              source_version=to_utc_iso((wi.get("fields") or {}).get("System.ChangedDate")),
                                              error=str(exc)))
        return out, errors

    async def _pull_requests(self, project: str, cursor: str | None) -> tuple[list[AdoDocument], list[ObjectError]]:
        out: list[AdoDocument] = []
        errors: list[ObjectError] = []
        for repo in await self._client.list_repositories(project):
            for status in ("active", "completed", "abandoned"):
                skip = 0
                while True:
                    prs = await self._client.list_pull_requests(project, repo["id"], status, cursor, self._page, skip)
                    for p in prs:
                        try:
                            out.append(self._pr_doc(project, p))
                        except Exception as exc:      # noqa: BLE001 - one bad PR must not fail the project
                            errors.append(ObjectError(scope=project, object_id=f"ado:{project}!{p.get('pullRequestId')}",
                                                      source_version=to_utc_iso(p.get("closedDate") or p.get("creationDate")),
                                                      error=str(exc)))
                    if len(prs) < self._page:
                        break
                    skip += self._page
        return out, errors

    async def fetch_scope(self, scope: str, cursor: str | None) -> ScopeFetch:
        docs: list[AdoDocument] = []
        errors: list[ObjectError] = []
        for fetch in (self._work_items, self._pull_requests):
            got, errs = await fetch(scope, cursor)
            docs += got
            errors += errs
        return ScopeFetch(documents=docs, errors=errors)
