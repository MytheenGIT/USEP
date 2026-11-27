"""GitHub pull request or repository to canonical records (system `git`, same state words as GitLab)."""
from __future__ import annotations

from typing import Any, Mapping

from usep.pipeline.normalize.record import Acl, UNKNOWN_ACL, Record


def _gh_acl(private: Any) -> Acl:
    """Repository visibility is a real, stated scope. Private means members only (the members are not in the payload)."""
    if private is None:
        return UNKNOWN_ACL
    return Acl(True, "github_repo_visibility", ("visibility:private" if private else "visibility:public",), bool(private))


def parse(raw: Mapping[str, Any], ref: str = "") -> list[Record]:
    commits = raw.get("commits") or []
    raw = raw.get("pull_request", raw)                       # the connector keeps commits and reviews next to the PR
    if "number" in raw:                                            # pull request
        base = raw.get("base") or {}
        repo = (base.get("repo") or {}).get("full_name") or ""
        sid = f"github:{repo}#{raw['number']}"
        state = "merged" if raw.get("merged_at") else ("opened" if raw.get("state") == "open" else "closed")
        labels = [str(x.get("name", "")).lower() for x in raw.get("labels") or []]
        body = raw.get("body") or ""
        pr = {"id": sid, "title": raw.get("title", ""), "state": state, "iid": raw["number"], "project_id": repo,
              "source_branch": (raw.get("head") or {}).get("ref"), "target_branch": base.get("ref")}
        rec = Record("git", "pull_request", sid, raw.get("updated_at") or "", raw.get("updated_at") or "",
                     raw.get("title", ""), "\n\n".join(p for p in [raw.get("title", ""), body] if p),
                     _gh_acl((base.get("repo") or {}).get("private")), labels,
                     {k: v for k, v in pr.items() if v is not None})
        rec.link_fields = {"title": raw.get("title", ""), "branch": pr["source_branch"] or "", "description": body,
                           "commit": "\n".join(str((c.get("commit") or {}).get("message", "")) for c in commits)}
        return [rec]
    full = raw["full_name"]                                        # repository
    sid = f"github:{full}"
    return [Record("git", "repository", sid, raw.get("updated_at") or "", raw.get("updated_at") or "",
                   raw.get("name", full), "\n\n".join(p for p in [raw.get("name", ""), raw.get("description") or ""] if p),
                   _gh_acl(raw.get("private")), [str(t).lower() for t in raw.get("topics") or []],
                   {"id": sid, "name": raw.get("name", full), "url": raw.get("html_url") or f"https://github.com/{full}"})]
