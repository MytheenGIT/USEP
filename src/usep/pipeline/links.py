"""Deterministic cross-system links (C-02), the first and most precise of three methods:
rules, then native API links, then (later, not built) model-proposed links.

Rules, all over text the connectors already fetched:
  * a Jira issue key (PROJ-123) in an MR title, branch name or description, or in a Jira issue's own text, or in a page
    body, becomes a `references` edge to that issue;
  * a repository URL in a decision page's body becomes a `documents` edge to the Service that holds that repository.
Native links are the Jira `issuelinks` already handled in normalize.py. Jira remote links and the GitLab commit list are
separate API calls the connectors do not make yet, so they are not covered.

Every edge states how it was found: `provenance = {method, rule, evidence}` and a `confidence`. A key in a title or
branch is the author's explicit act (1.0); in prose it is a mention that could be incidental (0.9 description or body,
0.8 comment). The target is named by source key only. Its concept type is unknown until the entity resolver has seen
the target (the key does not say whether it is a Story or a Task), so the edge is published `pending_resolution`
and the resolver types it, may upgrade `references` to `implements`, and re-validates against the ontology.

Evidence is the matched token (a key or a URL), never the surrounding text.
Identity: people are not linked here. `Person` is role-only in the core (HLD 6 Table 9), so there is no
author-to-person edge and no alias table; ownership comes from CODEOWNERS and group mappings through `owns`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from usep.ontology_runtime.model import OntologyBundle
from usep.pipeline.normalize import Record

# Branch names run on ("ABC-43-add-bus", "bugfix-ABC-12"), so a dash may border a key; letters and digits may not.
JIRA_KEY = re.compile(r"(?<![A-Za-z0-9_])([A-Z][A-Z0-9]{1,9}-[1-9][0-9]{0,6})(?![A-Za-z0-9_])(?!-[0-9])")
# Look-alikes that are not Jira keys. Prefer an explicit project-key allowlist (config) over this list.
NOT_JIRA = frozenset({"UTF", "ISO", "SHA", "MD", "RFC", "CVE", "CWE", "TLS", "SSL", "AES", "RSA", "PEP", "HTTP", "IPV",
                      "JDK", "JVM", "ECMA", "WCAG", "ARIA", "IEEE", "OWASP", "GPT", "LLM", "COVID", "ES", "PCI"})
URL = re.compile(r"https?://[^\s\"'<>)\]]+")
_REPO_STOP = re.compile(r"/(-|blob|tree|merge_requests|issues|commit|commits|pipelines|wikis)(/|$)")
CONFIDENCE = {"title": 1.0, "branch": 1.0, "commit": 0.9, "description": 0.9, "body": 0.9, "comment": 0.8}


@dataclass(frozen=True)
class Link:
    rel: str
    from_type: str
    to: dict                      # {"source_system", "source_id"} or {"type", "source_system", "repository_ref"}
    confidence: float
    provenance: dict


def repo_url(url: str, hosts: tuple[str, ...]) -> str | None:
    """Normalize a URL on a known repository host to the repository root, or None. Hosts are configuration."""
    p = urlparse(url.rstrip(".,;"))
    if p.hostname is None or p.hostname.lower() not in hosts:
        return None
    path = _REPO_STOP.split(p.path, 1)[0].rstrip("/")
    path = path[:-4] if path.endswith(".git") else path
    if path.count("/") < 2:                                  # needs at least group/project
        return None
    return f"https://{p.hostname.lower()}{path}"


def scan(rec: Record, hosts: tuple[str, ...] = (), project_keys: tuple[str, ...] = ()) -> tuple[dict[str, tuple[str, float]], dict[str, tuple[str, float]]]:
    """Keys and repository URLs found in a record, each mapped to (field, confidence). The best field wins."""
    keys: dict[str, tuple[str, float]] = {}
    repos: dict[str, tuple[str, float]] = {}
    for fld, text in rec.link_fields.items():
        conf = CONFIDENCE.get(fld, 0.8)
        for m in JIRA_KEY.finditer(text or ""):
            k = m.group(1)
            prefix = k.split("-")[0]
            if (project_keys and prefix not in project_keys) or (not project_keys and prefix in NOT_JIRA):
                continue
            if rec.source_system == "jira" and k == rec.source_id:
                continue                                      # an issue does not reference itself
            if k not in keys or conf > keys[k][1]:
                keys[k] = (fld, conf)
        for m in URL.finditer(text or ""):
            r = repo_url(m.group(0), hosts)
            if r and (r not in repos or conf > repos[r][1]):
                repos[r] = (fld, conf)
    return keys, repos


def extract(bundle: OntologyBundle, rec: Record, concept: str, hosts: tuple[str, ...] = (),
            project_keys: tuple[str, ...] = ()) -> list[Link]:
    """Links for a record that became a node of `concept`. A relationship the pinned ontology lacks, or whose from-type
    does not allow this concept, produces no link (the worker records that on the evidence)."""
    keys, repos = scan(rec, hosts, project_keys)
    out: list[Link] = []
    ancestors = set(bundle.ancestors(concept))
    ref = bundle.relationships.get("references")
    if ref and ancestors & set(ref.from_types):
        for k, (fld, conf) in sorted(keys.items()):
            out.append(Link("references", concept, {"source_system": "jira", "source_id": k}, conf,
                            {"method": "rule", "rule": f"jira_key_in_{fld}", "evidence": k}))
    doc = bundle.relationships.get("documents")
    if doc and ancestors & set(doc.from_types):
        for r, (fld, conf) in sorted(repos.items()):
            out.append(Link("documents", concept, {"type": "Service", "source_system": "git", "repository_ref": r},
                            conf, {"method": "rule", "rule": f"repo_url_in_{fld}", "evidence": r}))
    return out


def refs_for_evidence(rec: Record, hosts: tuple[str, ...] = (), project_keys: tuple[str, ...] = ()) -> dict:
    """What a record cites, for the evidence object. Lets the resolver and projectors link text that created no entity
    (an unlabelled page is evidence only). Also carries the page parent, since the core has no child_of."""
    keys, repos = scan(rec, hosts, project_keys)
    out: dict = {"jira_keys": sorted(keys), "repo_urls": sorted(repos)}
    if rec.parent_id:
        out["parent_id"] = rec.parent_id
    return out
