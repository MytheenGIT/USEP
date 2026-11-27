"""GitLab merge request to a canonical `pull_request` record (system `git`)."""
from __future__ import annotations

from typing import Any, Mapping

from usep.pipeline.normalize.record import UNKNOWN_ACL, Record


def parse(raw: Mapping[str, Any], ref: str = "") -> list[Record]:
    commits = raw.get("commits") or []                       # the connector keeps sub-resources next to the MR
    raw = raw.get("merge_request", raw)                      # (older snapshots hold the bare MR)
    pid = raw.get("project_id")
    sid = f"{pid}!{raw['iid']}" if pid is not None else f"!{raw['iid']}"
    labels = [str(x).lower() for x in raw.get("labels") or []]
    text = "\n\n".join(p for p in [raw.get("title", ""), raw.get("description") or ""] if p)
    pr = {"id": sid, "title": raw.get("title", ""), "state": raw.get("state"), "iid": raw.get("iid"),
          "project_id": pid, "source_branch": raw.get("source_branch"), "target_branch": raw.get("target_branch")}
    rec = Record("git", "pull_request", sid, raw.get("updated_at") or "", raw.get("updated_at") or "",
                 raw.get("title", ""), text, UNKNOWN_ACL, labels, {k: v for k, v in pr.items() if v is not None})
    rec.link_fields = {"title": raw.get("title", ""), "branch": raw.get("source_branch") or "",
                       "description": raw.get("description") or "",
                       "commit": "\n".join(str(c.get("message", "")) for c in commits)}
    return [rec]
