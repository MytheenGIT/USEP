"""S3 raw snapshot writer (diagram B2: "S3 raw: immutable snapshots, source versions, hashes").

Key: <prefix>/<source>/<url-quoted object id>/<sha256>.json. The checksum is in the key, so a changed object gets a
new snapshot and an unchanged one is a no-op. Snapshots are never overwritten (conditional put). Bucket versioning and
Object Lock are bucket settings owned by platform-iac. Credentials come from the workload identity.
"""
from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

from common.checksum import canonical_bytes, payload_checksum
from common.s3._errors import is_precondition_failed


class S3RawPayloadWriter:
    def __init__(self, client: Any, bucket: str, prefix: str = "raw") -> None:
        self._s3, self._bucket, self._prefix = client, bucket, prefix.strip("/")

    async def write(self, source: str, source_object_id: str, raw_payload: dict[str, Any]) -> str:
        key = f"{self._prefix}/{source}/{quote(source_object_id, safe='')}/{payload_checksum(raw_payload)}.json"
        await asyncio.to_thread(self._put, key, canonical_bytes(raw_payload))
        return f"s3://{self._bucket}/{key}"

    def _put(self, key: str, body: bytes) -> None:
        try:
            self._s3.put_object(Bucket=self._bucket, Key=key, Body=body, ContentType="application/json",
                                ServerSideEncryption="aws:kms", IfNoneMatch="*")
        except Exception as exc:  # noqa: BLE001 - botocore ClientError
            if not is_precondition_failed(exc):
                raise                       # already stored is fine; anything else must fail the sync
