"""S3-backed object index: one JSON list of ids per cursor key under state/index/. Single writer per key (the connector
Lambda runs with reserved concurrency 1), so read-modify-write is safe. Replace with Postgres if it outgrows a JSON list."""
from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import quote

from common.s3._errors import is_missing


class S3ObjectIndex:
    def __init__(self, client: Any, bucket: str, prefix: str = "state/index") -> None:
        self._s3, self._bucket, self._prefix = client, bucket, prefix.strip("/")

    def _key(self, key: str) -> str:
        return f"{self._prefix}/{quote(key, safe='')}.json"

    def _read(self, key: str) -> set[str]:
        try:
            obj = self._s3.get_object(Bucket=self._bucket, Key=self._key(key))
        except Exception as exc:  # noqa: BLE001
            if is_missing(exc):
                return set()
            raise
        return set(json.loads(obj["Body"].read()).get("ids", []))

    def _write(self, key: str, ids: set[str]) -> None:
        self._s3.put_object(Bucket=self._bucket, Key=self._key(key), Body=json.dumps({"ids": sorted(ids)}).encode(),
                            ContentType="application/json")

    async def get(self, key: str) -> set[str]:
        return await asyncio.to_thread(self._read, key)

    async def add(self, key: str, ids: set[str]) -> None:
        if ids:
            await asyncio.to_thread(lambda: self._write(key, self._read(key) | ids))

    async def remove(self, key: str, ids: set[str]) -> None:
        if ids:
            await asyncio.to_thread(lambda: self._write(key, self._read(key) - ids))
