"""Source onboarding file (diagram section A, 'Source onboarding'): `config/sources.yaml`.

It holds what is safe to commit and review: which sources are on, how often they run, which scopes they read, and the
start of the first backfill. It never holds a secret: tokens, passwords and keys stay in the secrets manager and arrive as
USEP_INGESTION_* variables. A key that looks like a credential is an error. The pipeline reads the same file for
`acl_mappings` (src/usep/pipeline/sources_config.py). Environment variables still win over the file, so an operator can
override one value without editing it.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from config import Settings

SCOPE_FIELD = {"jira": "jql_queries", "gitlab": "project_ids", "confluence": "space_keys", "figma": "file_keys",
               "github": "repos", "servicenow": "tables", "ado": "projects"}
_SECRET_KEY = re.compile(r"(?i)(token|password|passwd|secret|pat|api_?key|credential)")
_ALLOWED = {"enabled", "interval_minutes", "scopes", "acl_mappings"}


class SourcesFileError(Exception):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


def load(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        return {"sources": {}}
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    problems: list[str] = []
    if not isinstance(doc, dict) or set(doc) - {"defaults", "sources"}:
        raise SourcesFileError(["top level must hold only defaults and sources"])
    for k in (doc.get("defaults") or {}):
        if k != "backfill_since":
            problems.append(f"defaults.{k}: unknown key")
    for name, body in (doc.get("sources") or {}).items():
        if name not in SCOPE_FIELD:
            problems.append(f"sources.{name}: unknown source")
            continue
        body = body or {}
        for k in body:
            if _SECRET_KEY.search(k) and k not in _ALLOWED:
                problems.append(f"sources.{name}.{k}: looks like a credential; secrets do not belong in this file")
            elif k not in _ALLOWED:
                problems.append(f"sources.{name}.{k}: unknown key")
        if "interval_minutes" in body and (not isinstance(body["interval_minutes"], int) or body["interval_minutes"] < 1):
            problems.append(f"sources.{name}.interval_minutes: must be a positive integer")
        if "enabled" in body and not isinstance(body["enabled"], bool):
            problems.append(f"sources.{name}.enabled: must be true or false")
        scopes = body.get("scopes")
        if scopes is not None and (not isinstance(scopes, list) or not all(isinstance(s, str) and s.strip() for s in scopes)):
            problems.append(f"sources.{name}.scopes: must be a list of non-empty strings")
        for scope, who in (body.get("acl_mappings") or {}).items():
            if not isinstance(who, list) or not who or not all(isinstance(x, str) and ":" in x for x in who):
                problems.append(f"sources.{name}.acl_mappings.{scope}: needs a list of principals like group:name")
    if problems:
        raise SourcesFileError(problems)
    return doc


def enabled(doc: dict[str, Any], source: str) -> bool:
    return bool(((doc.get("sources") or {}).get(source) or {}).get("enabled", True))


def apply(settings: Settings, doc: dict[str, Any]) -> Settings:
    """Copy file values onto settings unless an environment variable already set that field."""
    def from_env(*parts: str) -> bool:
        return ("USEP_INGESTION_" + "_".join(p.upper() for p in parts)) in os.environ

    since = (doc.get("defaults") or {}).get("backfill_since")
    if since and not from_env("backfill_since"):
        settings.backfill_since = str(since)
    for name, body in (doc.get("sources") or {}).items():
        body = body or {}
        block = getattr(settings, name)
        if body.get("scopes") is not None and not from_env(name, SCOPE_FIELD[name]):
            setattr(block, SCOPE_FIELD[name], list(body["scopes"]))
        if "interval_minutes" in body and not from_env("scheduler", name, "interval_minutes"):
            setattr(settings.scheduler, f"{name}_interval_minutes", body["interval_minutes"])
    return settings
