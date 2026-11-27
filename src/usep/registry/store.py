"""Where the registry keeps releases and pin records. Releases and pins are written once and never overwritten.

Layout under one prefix:
    releases/<kind>/<id>/<version>/bundle.zip       written first
    releases/<kind>/<id>/<version>/manifest.json    written second, so a visible manifest always has its bundle
    pins/<tenant_id>/<seq:010d>.json                 append-only history; the highest sequence is current
`S3RegistryStore` is the deployed one (conditional puts; S3 Object Lock on the bucket is the platform's second line);
`LocalRegistryStore` is a directory with the same behaviour, for development and tests.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol

from usep.registry.errors import RegistryError


class RegistryStore(Protocol):
    def put_if_absent(self, key: str, body: bytes) -> bool: ...      # True if written, False if it already existed
    def get(self, key: str) -> bytes | None: ...
    def list(self, prefix: str) -> list[str]: ...                    # keys in lexical order


def _safe(key: str) -> str:
    if key.startswith("/") or ".." in Path(key).parts:
        raise RegistryError(f"unsafe registry key: {key!r}")
    return key


class LocalRegistryStore:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def put_if_absent(self, key: str, body: bytes) -> bool:
        p = self._root / _safe(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            return False
        with os.fdopen(fd, "wb") as f:
            f.write(body)
        return True

    def get(self, key: str) -> bytes | None:
        p = self._root / _safe(key)
        return p.read_bytes() if p.is_file() else None

    def list(self, prefix: str) -> list[str]:
        base = self._root / _safe(prefix.rstrip("/") or ".")
        return sorted(p.relative_to(self._root).as_posix() for p in base.rglob("*") if p.is_file()) if base.exists() else []


class S3RegistryStore:
    def __init__(self, client: Any, bucket: str, prefix: str = "registry") -> None:
        self._s3, self._bucket, self._prefix = client, bucket, prefix.strip("/")

    def _k(self, key: str) -> str:
        return f"{self._prefix}/{_safe(key)}"

    def put_if_absent(self, key: str, body: bytes) -> bool:
        try:
            self._s3.put_object(Bucket=self._bucket, Key=self._k(key), Body=body, ServerSideEncryption="aws:kms", IfNoneMatch="*")
            return True
        except Exception as exc:                                       # noqa: BLE001
            code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            if code in {"PreconditionFailed", "412", "ConditionalRequestConflict"}:
                return False
            raise RegistryError(f"cannot write {key}: {exc}") from exc

    def get(self, key: str) -> bytes | None:
        try:
            return self._s3.get_object(Bucket=self._bucket, Key=self._k(key))["Body"].read()
        except Exception as exc:                                       # noqa: BLE001
            code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            if code in {"NoSuchKey", "404"}:
                return None
            raise RegistryError(f"cannot read {key}: {exc}") from exc

    def list(self, prefix: str) -> list[str]:
        out: list[str] = []
        after = ""
        full = self._k(prefix)
        while True:
            kw = {"Bucket": self._bucket, "Prefix": full, "MaxKeys": 1000}
            if after:
                kw["StartAfter"] = after
            got = self._s3.list_objects_v2(**kw).get("Contents", [])
            out += [c["Key"][len(self._prefix) + 1:] for c in got]
            if len(got) < 1000:
                return out
            after = got[-1]["Key"]
