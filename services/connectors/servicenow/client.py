from __future__ import annotations

from typing import Any

import httpx

from common.client_base import BaseAPIClient, ClientRuntime

# Enough to understand a record and link it to others. Journal comments and attachments live in other tables and are not read.
FIELDS = (
    "sys_id,number,short_description,description,state,priority,urgency,impact,category,assignment_group,assigned_to,"
    "cmdb_ci,opened_at,closed_at,sys_created_on,sys_updated_on"
)


class ServiceNowClient(BaseAPIClient):
    """ServiceNow Table API with basic authentication (a username and password for a read-only integration user)."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        runtime: ClientRuntime | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url, headers={"Accept": "application/json"}, timeout=timeout, auth=(username, password),
            transport=transport, runtime=runtime,
        )

    async def list_records(
        self, table: str, query: str, page_size: int = 100, max_items: int | None = None
    ) -> list[dict[str, Any]]:
        """Records matching an encoded query, paged with sysparm_limit and sysparm_offset until a short page."""
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            body = await self.get_json(
                f"/api/now/table/{table}",
                params={
                    "sysparm_query": query, "sysparm_fields": FIELDS, "sysparm_display_value": "all",
                    "sysparm_exclude_reference_link": "true", "sysparm_limit": page_size, "sysparm_offset": offset,
                },
            )
            batch = body.get("result", [])
            rows.extend(batch)
            if len(batch) < page_size or (max_items is not None and len(rows) >= max_items):
                return rows[:max_items] if max_items is not None else rows
            offset += page_size

    async def probe_table(self, table: str) -> None:
        """One record, no fields: proves the user can sign in and read this table."""
        await self.get_json(f"/api/now/table/{table}", params={"sysparm_limit": 1, "sysparm_fields": "sys_id"})
