"""S3-backed cursor store: one small object per cursor key (source and scope). Single writer per source (the scheduler runs one job per
source), so read-modify-write is safe. Replace with Postgres if cursors need transactions with other state."""
from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import quote

from common.s3._errors import is_missing


class S3CursorManager:
    def __init__(self, client: Any, bucket: str, prefix: str = "state/connectors") -> None:
        self._s3, self._bucket, self._prefix = client, bucket, prefix.strip("/")

    def _key(self, source: str) -> str:
        # SyncService keys cursors "<source>:<scope>", and a scope can be a JQL query or a URL: quote it for a safe S3 key.
        return f"{self._prefix}/{quote(source, safe='')}.json"

    async def get_cursor(self, source: str) -> str | None:
        return await asyncio.to_thread(self._get, source)

    def _get(self, source: str) -> str | None:
        try:
            obj = self._s3.get_object(Bucket=self._bucket, Key=self._key(source))
        except Exception as exc:  # noqa: BLE001
            if is_missing(exc):
                return None
            raise
        return json.loads(obj["Body"].read()).get("cursor")

    async def set_cursor(self, source: str, cursor: str) -> None:
        await asyncio.to_thread(
            self._s3.put_object, Bucket=self._bucket, Key=self._key(source),
            Body=json.dumps({"cursor": cursor}).encode(), ContentType="application/json")
