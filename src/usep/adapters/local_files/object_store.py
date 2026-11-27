"""`ObjectStorePort` on the local file system, for inspecting what lands before S3 is connected.

Same keys and same encrypted bytes as the S3 adapter, so switching to S3 changes the
setting and nothing else. A key becomes a path under one root folder; anything that
could leave that folder (``..``, an absolute path) is refused.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path


class FileObjectStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def _path(self, key: str) -> Path:
        if not key or "\0" in key or key.startswith("/") or any(part in ("", ".", "..") for part in key.split("/")):
            raise ValueError(f"not a safe object key: {key!r}")
        path = (self._root / key).resolve()
        if not path.is_relative_to(self._root):
            raise ValueError(f"object key leaves the store: {key!r}")
        return path

    async def put(self, key: str, data: bytes) -> None:
        path = self._path(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".part-")
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                os.replace(tmp, path)  # a reader never sees half a file
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise

        await asyncio.to_thread(_write)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).is_file)

    async def check(self) -> list[str]:
        """Fail fast if the folder cannot be written."""

        def _probe() -> None:
            self._root.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self._root, prefix=".probe-")
            os.close(fd)
            Path(tmp).unlink()

        await asyncio.to_thread(_probe)
        return []
