"""ServiceNow connector: one scope per table (incident, change_request, problem, ...).

Changed records are found with ``sys_updated_on >= <day before the cursor>`` and the records older than the cursor are
dropped afterwards: the query date is read in a time zone that is not always UTC, so it steps back a day, as the
Confluence connector does. An optional encoded query (for example ``active=true^assignment_group=...``) narrows
every table. The raw record is kept as received (display and stored values) in ``raw_payload``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from common.client_base import error_detail
from common.connector_base import ObjectError, ScopeCheck, ScopeFetch, SourceCheck
from common.scopes import servicenow_table_problem
from common.source_document import SourceType
from common.timeutil import parse_ts, to_utc_iso
from servicenow.client import ServiceNowClient
from servicenow.models import ServiceNowDocument


def _shown(record: dict[str, Any], field: str) -> str | None:
    """The display text of a field fetched with ``sysparm_display_value=all`` ({value, display_value}), else the value."""
    item = record.get(field)
    if isinstance(item, dict):
        return item.get("display_value") or item.get("value") or None
    return item or None


def _stored(record: dict[str, Any], field: str) -> str | None:
    item = record.get(field)
    return (item.get("value") if isinstance(item, dict) else item) or None


class ServiceNowConnector:
    source = SourceType.SERVICENOW

    def __init__(self, client: ServiceNowClient, tables: list[str], encoded_query: str = "", page_size: int = 100) -> None:
        for table in tables:
            problem = servicenow_table_problem(table)
            if problem:
                raise ValueError(problem)
        self._client = client
        self._scopes = list(dict.fromkeys(t.strip() for t in tables if t.strip()))
        self._query = encoded_query.strip()
        self._page_size = page_size

    @property
    def scopes(self) -> list[str]:
        return list(self._scopes)

    def build_query(self, cursor: str | None) -> str:
        parts = []
        cursor_dt = parse_ts(cursor)
        if cursor_dt:
            parts.append(f"sys_updated_on>={(cursor_dt - timedelta(days=1)).strftime('%Y-%m-%d')} 00:00:00")
        if self._query:
            parts.append(self._query)
        return "^".join([*parts, "ORDERBYsys_updated_on"])

    async def check(self) -> SourceCheck:
        """Every table can be read by this user (a wrong password or a table it may not see shows up per table)."""
        results = []
        for table in self._scopes:
            try:
                await self._client.probe_table(table)
                results.append(ScopeCheck(scope=table, ok=True, detail="readable"))
            except Exception as exc:  # noqa: BLE001
                results.append(ScopeCheck(scope=table, ok=False, detail=error_detail(exc)))
        if not results:
            return SourceCheck(ok=False, detail="add at least one table to test the sign-in with")
        return SourceCheck(ok=all(r.ok for r in results), detail="signed in" if all(r.ok for r in results) else "see the scopes", scopes=results)

    def _normalize(self, table: str, scope: str, record: dict[str, Any], base_url: str) -> ServiceNowDocument:
        number = _stored(record, "number") or _stored(record, "sys_id") or ""
        sys_id = _stored(record, "sys_id") or number
        version = to_utc_iso(_stored(record, "sys_updated_on"))  # the stored value is UTC: "2026-11-26 10:00:00"
        return ServiceNowDocument(
            source=self.source,
            source_type=table,
            source_object_id=f"{table}:{number}",
            source_url=f"{base_url}/nav_to.do?uri={table}.do?sys_id={sys_id}",
            retrieved_at=datetime.now(UTC),
            raw_payload={"record": record},
            scope=scope,
            source_version=version,
            acl={"table": table, "assignment_group": _shown(record, "assignment_group")},
            title=_shown(record, "short_description") or number,
            content=_shown(record, "description") or "",
            metadata={"updated": version, "state": _shown(record, "state"), "table": table},
            table=table,
            number=number,
            sys_id=sys_id,
            short_description=_shown(record, "short_description") or "",
            description=_shown(record, "description"),
            state=_shown(record, "state"),
            priority=_shown(record, "priority"),
            category=_shown(record, "category"),
            assignment_group=_shown(record, "assignment_group"),
            assigned_to=_shown(record, "assigned_to"),
            configuration_item=_shown(record, "cmdb_ci"),
            opened_at=to_utc_iso(_stored(record, "opened_at")),
            closed_at=to_utc_iso(_stored(record, "closed_at")),
        )

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
        records = await self._client.list_records(scope, self.build_query(cursor), page_size=self._page_size)
        cursor_dt = parse_ts(cursor)
        base_url = str(self._client._client.base_url).rstrip("/")  # noqa: SLF001 -- the link back into the instance
        documents: list[ServiceNowDocument] = []
        errors: list[ObjectError] = []
        for record in records:
            updated = parse_ts(_stored(record, "sys_updated_on"))
            if cursor_dt and updated and updated < cursor_dt:
                continue  # inside the one-day safety margin of the query, but not newer than the cursor
            try:
                documents.append(self._normalize(scope, scope, record, base_url))
            except Exception as exc:  # noqa: BLE001 -- one bad record must not fail the table
                errors.append(ObjectError(scope=scope, object_id=str(_stored(record, "number")), source_version=to_utc_iso(_stored(record, "sys_updated_on")), error=str(exc)))
        return ScopeFetch(documents=documents, errors=errors)
