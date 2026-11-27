"""Jira issue to canonical records: the issue, plus one record per issue link (an edge)."""
from __future__ import annotations

from typing import Any, Mapping

from usep.pipeline.normalize.record import Acl, UNKNOWN_ACL, Record, adf_to_text, named


def parse(raw: Mapping[str, Any], ref: str = "") -> list[Record]:
    f = raw.get("fields") or {}
    key = raw["key"]
    labels = [str(x).lower() for x in f.get("labels") or []]
    security = named(f.get("security"))
    project = (f.get("project") or {}).get("key")
    if security:
        acl = Acl(True, "jira_issue_security", (f"security_level:{security}",), True)
    else:
        acl = UNKNOWN_ACL           # project roles are not in the issue payload, and access is never inferred from them
    comments = [adf_to_text(c.get("body")) for c in (f.get("comment") or {}).get("comments", [])]
    text = "\n\n".join(p for p in [f.get("summary", ""), adf_to_text(f.get("description")), *comments] if p)
    version = f"{f.get('updated') or ''}"
    issue = {"key": key, "summary": f.get("summary", ""), "issue_type": (named(f.get("issuetype")) or "").lower() or None,
             "status": named(f.get("status")), "priority": named(f.get("priority")), "project": project}
    rec = Record("jira", "issue", key, version, f.get("updated") or "", f.get("summary", ""), text, acl, labels,
                 {k: v for k, v in issue.items() if v is not None})
    rec.link_fields = {"title": f.get("summary", ""), "description": adf_to_text(f.get("description")),
                       "comment": "\n".join(comments)}
    # Native remote links (the connector stores them next to the issue): their URLs are scanned for Confluence pages.
    rec.link_fields["remote_link"] = "\n".join(
        str((rl.get("object") or {}).get("url", "")) for rl in raw.get("remote_links") or [])
    out = [rec]
    for ln in f.get("issuelinks") or []:
        lt = ln.get("type") or {}
        for side, other, label in (("outwardIssue", "outward", lt.get("outward")), ("inwardIssue", "inward", lt.get("inward"))):
            target = (ln.get(side) or {}).get("key")
            if not target or not label:
                continue
            link_type = str(label).lower().strip()
            if side == "inwardIssue":                   # "X is implemented by Y" is "Y implements X": flip it
                link_type = _INVERSE.get(link_type, "")
                if not link_type:
                    continue
                src, dst = target, key
            else:
                src, dst = key, target
            link_type = _CANON_LINK.get(link_type, link_type)
            sid = f"{src}->{dst}:{link_type}"
            out.append(Record("jira", "issue_link", sid, version, rec.event_time, sid, "", acl, [], {
                "link_type": link_type, "from": src, "to": dst}, links=[{"from": src, "to": dst}]))
    return out


_INVERSE = {"is implemented by": "implements"}
_CANON_LINK = {"implements": "implements"}
