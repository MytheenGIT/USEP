"""Store for downloaded binaries (Jira attachments, Figma frame exports).

The raw payload writer (owned by the connector runtime work) handles JSON
only. Binaries go through this small interface; the local default writes
under ``<output_dir>/binaries`` and should be swapped for the object-storage
implementation when that exists. Keys are stable, so an attachment that is
already stored is never downloaded again.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Protocol

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_key_part(value: str) -> str:
    return _UNSAFE.sub("_", value).strip("._") or "_"


class BinaryStore(Protocol):
    def exists(self, key: str) -> str | None:
        """Return the stored reference if ``key`` is already stored, else None."""
        ...

    def put(self, key: str, data: bytes) -> tuple[str, str]:
        """Store ``data`` under ``key``; return (reference, sha256)."""
        ...


class LocalBinaryStore:
    def __init__(self, root: str) -> None:
        self._root = Path(root)

    def _path(self, key: str) -> Path:
        parts = [safe_key_part(p) for p in key.split("/") if p]
        return self._root.joinpath(*parts)

    def exists(self, key: str) -> str | None:
        path = self._path(key)
        return f"file://{path.resolve()}" if path.is_file() else None

    def put(self, key: str, data: bytes) -> tuple[str, str]:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return f"file://{path.resolve()}", hashlib.sha256(data).hexdigest()
