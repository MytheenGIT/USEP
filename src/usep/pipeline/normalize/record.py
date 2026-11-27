"""Canonical record and the helpers every source parser shares (text extraction, ACL)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import unescape
from typing import Any, Mapping

_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")


@dataclass(frozen=True)
class Acl:
    """Harvested source permissions. `known` is true only when the source stated a restriction or a scope.
    Anything else is unknown, which means owners only until the next sync (HLD 4.5, fail closed)."""
    known: bool
    scheme: str = ""
    principals: tuple[str, ...] = ()
    restricted: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"known": self.known, "scheme": self.scheme, "principals": list(self.principals),
                "restricted": self.restricted}


UNKNOWN_ACL = Acl(False)


@dataclass
class Record:
    source_system: str
    source_object: str
    source_id: str
    source_version: str
    event_time: str
    title: str
    text: str
    acl: Acl
    labels: list[str] = field(default_factory=list)
    scope: dict[str, Any] = field(default_factory=dict)       # the object-named block mappings read, e.g. 'issue'
    links: list[dict[str, str]] = field(default_factory=list)
    link_text: str = ""                                       # raw text scanned for keys and URLs; never stored
    link_fields: dict[str, str] = field(default_factory=dict)  # field name -> text, for per-field confidence
    parent_id: str | None = None

    def mapping_payload(self) -> dict[str, Any]:
        return {self.source_object: {**self.scope, "label": self.labels}, "label": self.labels}


def html_to_text(html: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>|</p>|</h[1-6]>|</li>|</tr>", "\n", html or "")
    text = unescape(_TAGS.sub("", text))
    return "\n".join(_WS.sub(" ", ln).strip() for ln in text.splitlines()).strip()


def adf_to_text(node: Any) -> str:
    """Atlassian Document Format to plain text. A plain string passes through."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        parts = [str(node["text"])] if "text" in node else []
        parts += [adf_to_text(c) for c in node.get("content", [])]
        return " ".join(p for p in parts if p)
    return ""


def named(d: Any) -> str | None:
    return d.get("name") if isinstance(d, Mapping) else None
