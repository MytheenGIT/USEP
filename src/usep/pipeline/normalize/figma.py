"""Figma file to a canonical `file` record. The payload has only the display name, so the file key comes from the event."""
from __future__ import annotations

from typing import Any, Mapping

from usep.pipeline.normalize.record import UNKNOWN_ACL, Record


def parse(raw: Mapping[str, Any], ref: str = "") -> list[Record]:
    key = ref                                    # the file key; the payload carries only the display name
    texts: list[str] = []

    def walk(n: Mapping[str, Any]) -> None:
        if n.get("type") == "TEXT" and n.get("characters"):
            texts.append(n["characters"])
        for c in n.get("children", []):
            walk(c)

    walk(raw.get("document") or {})
    return [Record("figma", "file", key, str(raw.get("version") or ""), raw.get("lastModified") or "",
                   raw.get("name", key), "\n".join(texts), UNKNOWN_ACL, [], {"name": raw.get("name", key)})]
