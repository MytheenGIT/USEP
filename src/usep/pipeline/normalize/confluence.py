"""Confluence page to a canonical `page` record: labels, read restrictions as ACL, parent page."""
from __future__ import annotations

from typing import Any, Mapping

from usep.pipeline.normalize.record import Acl, UNKNOWN_ACL, Record, html_to_text


def parse(raw: Mapping[str, Any], ref: str = "") -> list[Record]:
    raw = raw.get("page", raw)                               # the connector wraps the page with children and versions
    pid = str(raw["id"])
    labels = [str(r.get("name", "")).lower() for r in ((raw.get("metadata") or {}).get("labels") or {}).get("results", [])]
    read = ((raw.get("restrictions") or {}).get("read") or {}).get("restrictions") or {}
    principals = tuple([f"user:{u.get('accountId') or u.get('username') or u.get('displayName')}"
                        for u in (read.get("user") or {}).get("results", [])]
                       + [f"group:{g.get('name')}" for g in (read.get("group") or {}).get("results", [])])
    acl = Acl(True, "confluence_page_restriction", principals, True) if principals else UNKNOWN_ACL
    ver = raw.get("version") or {}
    body = html_to_text(((raw.get("body") or {}).get("storage") or {}).get("value", ""))
    text = "\n\n".join(p for p in [raw.get("title", ""), body] if p)
    page = {"id": pid, "title": raw.get("title", ""), "space": (raw.get("space") or {}).get("key")}
    rec = Record("confluence", "page", pid, str(ver.get("number", "")), ver.get("when") or "",
                 raw.get("title", ""), text, acl, labels, {k: v for k, v in page.items() if v})
    rec.link_fields = {"title": raw.get("title", ""),
                       "body": ((raw.get("body") or {}).get("storage") or {}).get("value", "")}   # raw XHTML keeps hrefs
    anc = raw.get("ancestors") or []
    rec.parent_id = str(anc[-1]["id"]) if anc and anc[-1].get("id") else None
    return [rec]
