"""S3 adapter for the object store port. Writes are conditional (never overwrite) and KMS-encrypted."""
from __future__ import annotations

from typing import Any

from usep.core.errors import PipelineError


class S3ObjectStore:
    def __init__(self, client: Any, bucket: str) -> None:
        self._s3, self._bucket = client, bucket

    def get(self, ref: str) -> bytes:
        if not ref.startswith("s3://"):
            raise PipelineError(f"unsupported snapshot_ref: {ref!r}")
        bucket, _, key = ref[5:].partition("/")
        if not bucket or not key:
            raise PipelineError(f"malformed snapshot_ref: {ref!r}")
        try:
            return self._s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        except Exception as exc:                               # noqa: BLE001
            raise PipelineError(f"cannot read {ref}: {exc}") from exc

    def put_if_absent(self, key: str, body: bytes) -> str:
        try:
            self._s3.put_object(Bucket=self._bucket, Key=key, Body=body, ContentType="application/json",
                                ServerSideEncryption="aws:kms", IfNoneMatch="*")
        except Exception as exc:                               # noqa: BLE001
            code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            if code not in {"PreconditionFailed", "412", "ConditionalRequestConflict"}:
                raise PipelineError(f"cannot write {key}: {exc}") from exc
        return f"s3://{self._bucket}/{key}"
