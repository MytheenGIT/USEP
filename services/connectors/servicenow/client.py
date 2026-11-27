from __future__ import annotations

import base64
from typing import Any

import httpx

from common.client_base import BaseAPIClient


class ServiceNowClient(BaseAPIClient):
    """ServiceNow Table API, read-only. Use a dedicated integration user with read ACLs on the tables only."""

    def __init__(self, instance_url: str, username: str, password: str, timeout: float = 60.0,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        super().__init__(base_url=instance_url, timeout=timeout, transport=transport,
                         headers={"Authorization": f"Basic {token}", "Accept": "application/json"})

    async def query_table(self, table: str, since: str | None, offset: int = 0, limit: int = 100,
                          fields: str | None = None) -> list[dict[str, Any]]:
        # sys_updated_on is UTC 'YYYY-MM-DD HH:MM:SS'. >= re-reads the boundary second (idempotent) so none is missed.
        query = (f"sys_updated_on>={since}^" if since else "") + "ORDERBYsys_updated_on^ORDERBYsys_id"
        params: dict[str, Any] = {
            "sysparm_query": query, "sysparm_limit": limit, "sysparm_offset": offset,
            "sysparm_display_value": "false", "sysparm_exclude_reference_link": "true"}
        if fields:
            params["sysparm_fields"] = fields                  # a narrow read, for listing ids without the full rows
        body = await self.get_json(f"/api/now/table/{table}", params=params)
        return body.get("result", [])
