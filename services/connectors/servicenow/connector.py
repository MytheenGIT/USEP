"""ServiceNow connector: one scope per table. incident -> Incident, change_request -> Change. Read-only, incremental on
sys_updated_on (the instance stores UTC as 'YYYY-MM-DD HH:MM:SS'; versions here are normalized to ISO UTC)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from common.connector_base import ObjectError, ScopeFetch
from common.source_document import SourceType
from common.timeutil import parse_ts, to_utc_iso
from servicenow.client import ServiceNowClient
from servicenow.models import ServiceNowDocument

DEFAULT_TABLES = ("incident", "change_request")


def _s(v: Any) -> str | None:
    if isinstance(v, dict):                      # a reference when links are not excluded
        v = v.get("value")
    return str(v) if v not in (None, "") else None


class ServiceNowConnector:
    source = SourceType.SERVICENOW

    def __init__(self, client: ServiceNowClient, instance_url: str, tables: tuple[str, ...] | list[str] = DEFAULT_TABLES,
                 page_size: int = 100) -> None:
        self._client, self._base = client, instance_url.rstrip("/")
        self._tables, self._page_size = tuple(tables), page_size

    @property
    def scopes(self) -> list[str]:
        return list(self._tables)

    def _doc(self, table: str, r: dict[str, Any]) -> ServiceNowDocument:
        sys_id, number = str(r["sys_id"]), str(r.get("number") or r["sys_id"])
        version = to_utc_iso(r.get("sys_updated_on"))
        return ServiceNowDocument(
            scope=table, source_version=version, acl={"table": table, "assignment_group": _s(r.get("assignment_group"))},
            source=self.source, source_type=table, source_object_id=number,
            source_url=f"{self._base}/nav_to.do?uri={table}.do?sys_id={sys_id}", retrieved_at=datetime.now(UTC),
            raw_payload=r, title=r.get("short_description") or number, content=r.get("description") or "",
            metadata={"updated": version}, table=table, number=number, sys_id=sys_id,
            state=_s(r.get("state")), priority=_s(r.get("priority")), assignment_group=_s(r.get("assignment_group")),
            cmdb_ci=_s(r.get("cmdb_ci")), caused_by=_s(r.get("caused_by")))

    async def list_ids(self, scope: str) -> set[str]:
        """Every record number in the table right now (for delete reconciliation). Numbers only."""
        ids: set[str] = set()
        offset = 0
        while True:
            rows = await self._client.query_table(scope, None, offset, self._page_size, fields="number,sys_id")
            ids |= {str(r.get("number") or r["sys_id"]) for r in rows}
            if len(rows) < self._page_size:
                return ids
            offset += self._page_size

    async def fetch_scope(self, scope: str, cursor: str | None) -> ScopeFetch:
        since = parse_ts(cursor).strftime("%Y-%m-%d %H:%M:%S") if cursor else None
        docs: list[ServiceNowDocument] = []
        errors: list[ObjectError] = []
        offset = 0
        while True:
            rows = await self._client.query_table(scope, since, offset, self._page_size)   # failure fails this scope only
            for r in rows:
                try:
                    docs.append(self._doc(scope, r))
                except Exception as exc:                                # noqa: BLE001 - one bad row must not fail the table
                    errors.append(ObjectError(scope=scope, object_id=str(r.get("number") or r.get("sys_id")),
                                              source_version=to_utc_iso(r.get("sys_updated_on")), error=str(exc)))
            if len(rows) < self._page_size:
                return ScopeFetch(documents=docs, errors=errors)
            offset += self._page_size
