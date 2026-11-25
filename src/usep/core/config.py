from __future__ import annotations

from typing import Any, Mapping


class Config:
    """Read-only dotted-key view over a mapping, e.g. Config({"ontology": {"dir": "ontology"}}).get("ontology.dir")."""

    def __init__(self, data: Mapping[str, Any] | None = None) -> None:
        self._data = dict(data or {})

    def get(self, key: str, default: Any = None) -> Any:
        cur: Any = self._data
        for part in key.split("."):
            if not isinstance(cur, Mapping) or part not in cur:
                return default
            cur = cur[part]
        return cur
