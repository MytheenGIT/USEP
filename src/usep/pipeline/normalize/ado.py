"""Azure DevOps work item or pull request to canonical records (pull requests use system `git`)."""
from __future__ import annotations

from typing import Any, Mapping

from usep.pipeline.normalize.record import UNKNOWN_ACL, Record, html_to_text


def parse(raw: Mapping[str, Any], ref: str = "") -> list[Record]:
    if "pullRequestId" in raw:
        repo = raw.get("repository") or {}
        proj = (repo.get("project") or {}).get("name", "")
        sid = f"ado:{proj}/{repo.get('name', '')}!{raw['pullRequestId']}"
        state = {"active": "opened", "completed": "merged"}.get(raw.get("status", ""), "closed")
        branch = str(raw.get("sourceRefName") or "").removeprefix("refs/heads/")
        when = raw.get("closedDate") or raw.get("creationDate") or ""
        pr = {"id": sid, "title": raw.get("title", ""), "state": state, "iid": raw["pullRequestId"],
              "project_id": f"{proj}/{repo.get('name', '')}", "source_branch": branch or None}
        rec = Record("git", "pull_request", sid, when, when, raw.get("title", ""),
                     "\n\n".join(p for p in [raw.get("title", ""), raw.get("description") or ""] if p), UNKNOWN_ACL,
                     [str(x.get("name", "")).lower() for x in raw.get("labels") or []],
                     {k: v for k, v in pr.items() if v not in (None, "")})
        rec.link_fields = {"title": raw.get("title", ""), "branch": branch, "description": raw.get("description") or ""}
        return [rec]
    f = raw["fields"]
    proj = f.get("System.TeamProject", "")
    sid = f"{proj}#{raw['id']}"
    desc = html_to_text(f.get("System.Description") or "")
    title = f.get("System.Title", "")
    wi = {"id": sid, "title": title, "work_item_type": str(f.get("System.WorkItemType") or "").lower() or None,
          "state": f.get("System.State"), "project": proj}
    rec = Record("ado", "work_item", sid, f.get("System.ChangedDate") or "", f.get("System.ChangedDate") or "", title,
                 "\n\n".join(p for p in [title, desc] if p), UNKNOWN_ACL,
                 [t.strip().lower() for t in (f.get("System.Tags") or "").split(";") if t.strip()],
                 {k: v for k, v in wi.items() if v not in (None, "")})
    rec.link_fields = {"title": title, "description": desc}
    return [rec]
