"""Merge the ACL attributes the connector harvested next to an object with what the parser read from the payload.

The connector stores a small `acl` dict on every document (it travels on the raw event). It states two different
things, which this module keeps apart because only one of them changes who may see the record:

  * a restriction the source stated  -> `known` access, with principals (a Jira security level, Confluence read-restriction
    groups, a GitLab or GitHub repository visibility). A restriction sets `restricted`.
  * a scope that governs access      -> `scopes` ("project:ABC", "space:ENG", "table:incident"). The query-time filter
    needs it, but naming a scope does not say who can read it, so it never makes an ACL known.

Nothing here infers access. Anything not stated stays unknown, which means owners only (HLD 4.5, fail closed).
Union only: the merged ACL is at least as restrictive as either input.
"""
from __future__ import annotations

from typing import Any, Mapping

from usep.pipeline.normalize.record import Acl


def from_connector(source: str, acl: Mapping[str, Any] | None) -> Acl:
    a = acl or {}
    scopes: list[str] = []
    principals: list[str] = []
    scheme, restricted, known = "", False, False

    def scope(kind: str, value: Any) -> None:
        if value not in (None, ""):
            scopes.append(f"{kind}:{value}")

    if source == "jira":
        scope("project", a.get("project_key"))
        if a.get("security_level"):
            principals.append(f"security_level:{a['security_level']}")
            scheme, restricted, known = "jira_issue_security", True, True
    elif source == "confluence":
        scope("space", a.get("space_key"))
        groups = [g for g in a.get("read_restriction_groups") or [] if g]
        if groups:
            principals += [f"group:{g}" for g in groups]
            scheme, restricted, known = "confluence_page_restriction", True, True
    elif source == "gitlab":
        scope("project", a.get("project_path") or a.get("project_id"))
        vis = a.get("visibility")
        if vis in ("private", "internal", "public"):
            principals.append(f"visibility:{vis}")
            scheme, restricted, known = "gitlab_project_visibility", vis == "private", True
    elif source == "github":
        scope("repo", a.get("repo"))
        if a.get("private") is not None:
            principals.append("visibility:private" if a["private"] else "visibility:public")
            scheme, restricted, known = "github_repo_visibility", bool(a["private"]), True
    elif source == "servicenow":
        scope("table", a.get("table"))
        scope("assignment_group", a.get("assignment_group"))
    elif source == "ado":
        scope("project", a.get("project"))
        scope("area_path", a.get("area_path"))
        scope("repository", a.get("repository"))
        vis = str(a.get("visibility") or "").lower()        # project visibility, present on pull requests only
        if vis in ("private", "public"):
            principals.append(f"visibility:{vis}")
            scheme, restricted, known = "ado_project_visibility", vis == "private", True
    elif source == "figma":
        scope("file", a.get("file_key"))
    return Acl(known, scheme, tuple(principals), restricted, tuple(scopes))


def merge(parsed: Acl, connector: Acl) -> Acl:
    """Union of the two. Restricted if either is; known if either is; principals and scopes combined, order kept."""
    def union(a: tuple[str, ...], b: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*a, *b)))

    return Acl(
        known=parsed.known or connector.known,
        scheme=parsed.scheme or connector.scheme,
        principals=union(parsed.principals, connector.principals),
        restricted=parsed.restricted or connector.restricted,
        scopes=union(parsed.scopes, connector.scopes),
    )
