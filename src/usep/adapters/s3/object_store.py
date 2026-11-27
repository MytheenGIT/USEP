"""`ObjectStorePort` over S3 (or any S3-compatible store). boto3 calls are blocking, so each
runs in a worker thread. Objects arrive already encrypted by the raw payload writer.
"""

from __future__ import annotations

import asyncio
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from usep.core.errors import ConfigError


class S3ObjectStore:
    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    async def put(self, key: str, data: bytes) -> None:
        await asyncio.to_thread(self._client.put_object, Bucket=self._bucket, Key=key, Body=data)

    async def get(self, key: str) -> bytes:
        def _get() -> bytes:
            return bytes(self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read())

        return await asyncio.to_thread(_get)

    async def exists(self, key: str) -> bool:
        try:
            await asyncio.to_thread(self._client.head_object, Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
        return True

    async def check(self) -> list[str]:
        """Fail fast if the bucket cannot be used; return warnings about write-once protection.

        The HLD calls the evidence store write-once (Object Lock, versioning). The bucket's
        settings belong to infrastructure, so a missing protection is reported, not refused.
        """
        try:
            await asyncio.to_thread(self._client.head_bucket, Bucket=self._bucket)
        except (ClientError, BotoCoreError) as exc:
            code = exc.response.get("Error", {}).get("Code", "") if isinstance(exc, ClientError) else type(exc).__name__
            raise ConfigError(f"cannot use S3 bucket {self._bucket!r} ({code}); check the bucket name, region and credentials") from exc

        warnings: list[str] = []
        try:
            versioning = await asyncio.to_thread(self._client.get_bucket_versioning, Bucket=self._bucket)
            if versioning.get("Status") != "Enabled":
                warnings.append("bucket versioning is not enabled")
        except ClientError:
            warnings.append("could not read the bucket versioning setting")
        try:
            await asyncio.to_thread(self._client.get_object_lock_configuration, Bucket=self._bucket)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            warnings.append(
                "object lock is not configured" if code == "ObjectLockConfigurationNotFoundError"
                else "could not read the bucket object lock setting"
            )
        return warnings
