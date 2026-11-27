"""Runtime policy files (diagram section A, 'Runtime policy'): classification, egress, redaction and resolution.

One directory (default config/runtime/), four YAML files. A missing file means the built-in defaults, which are the values
in the shipped files, so behaviour does not change until an owner edits one. Fail closed on anything unclear: an unknown
key, a value out of range or a bad regular expression raises PolicyConfigError and the service does not start.
Redaction can only be extended, never reduced.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import yaml

from usep.pipeline.classify import ClassificationPolicy
from usep.pipeline.egress import EgressPolicy
from usep.pipeline.redact import RedactionPolicy


class PolicyConfigError(Exception):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


@dataclass(frozen=True)
class ResolutionPolicy:
    auto_link_threshold: float = 0.92
    review_threshold: float = 0.75
    below_review: str = "new_entity"
    pending_link_retry_minutes: int = 60


@dataclass(frozen=True)
class RuntimePolicy:
    classification: ClassificationPolicy
    egress: EgressPolicy
    redaction: RedactionPolicy
    resolution: ResolutionPolicy


def _read(path: Path, problems: list[str]) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        problems.append(f"{path.name}: must be a mapping")
        return {}
    return data


def _unknown(name: str, data: dict[str, Any], allowed: set[str], problems: list[str]) -> None:
    for k in sorted(set(data) - allowed):
        problems.append(f"{name}: unknown key {k}")


def _level(name: str, v: Any, problems: list[str]) -> int:
    if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 3:
        problems.append(f"{name}: must be an integer from 0 to 3")
        return 1
    return v


def load_runtime_policy(directory: str | Path = "config/runtime") -> RuntimePolicy:
    d = Path(directory)
    problems: list[str] = []

    c = _read(d / "classification.yaml", problems)
    allowed = {f.name for f in fields(ClassificationPolicy)}
    _unknown("classification.yaml", c, allowed, problems)
    base = ClassificationPolicy()
    labels = dict(c.get("label_sensitivity", base.label_sensitivity))
    for k, v in labels.items():
        _level(f"classification.yaml label_sensitivity.{k}", v, problems)
    classification = ClassificationPolicy(
        _level("default_sensitivity", c.get("default_sensitivity", base.default_sensitivity), problems), labels,
        _level("pii_floor", c.get("pii_floor", base.pii_floor), problems),
        _level("secret_floor", c.get("secret_floor", base.secret_floor), problems),
        _level("restricted_acl_floor", c.get("restricted_acl_floor", base.restricted_acl_floor), problems))

    e = _read(d / "egress.yaml", problems)
    _unknown("egress.yaml", e, {f.name for f in fields(EgressPolicy)}, problems)
    be = EgressPolicy()
    for k in ("allow_owners_only", "allow_secret_hit", "allow_pii_hit"):
        if not isinstance(e.get(k, getattr(be, k)), bool):
            problems.append(f"egress.yaml {k}: must be true or false")
    egress = EgressPolicy(_level("egress max_sensitivity", e.get("max_sensitivity", be.max_sensitivity), problems),
                          bool(e.get("allow_owners_only", be.allow_owners_only)),
                          bool(e.get("allow_secret_hit", be.allow_secret_hit)),
                          bool(e.get("allow_pii_hit", be.allow_pii_hit)))

    r = _read(d / "redaction.yaml", problems)
    _unknown("redaction.yaml", r, {"extra_patterns"}, problems)
    secret, pii = [], []
    for i, row in enumerate(r.get("extra_patterns") or []):
        where = f"redaction.yaml extra_patterns[{i}]"
        if not isinstance(row, dict) or set(row) != {"name", "pattern", "category"}:
            problems.append(f"{where}: needs exactly name, pattern, category")
            continue
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,40}", str(row["name"])):
            problems.append(f"{where}: name must be lower_snake_case")
        if row["category"] not in ("secret", "pii"):
            problems.append(f"{where}: category must be secret or pii")
        try:
            pat = re.compile(str(row["pattern"]))
        except re.error as exc:
            problems.append(f"{where}: bad pattern ({exc})")
            continue
        if pat.search(""):
            problems.append(f"{where}: pattern matches the empty string")
        (secret if row["category"] == "secret" else pii).append((str(row["name"]), pat))
    redaction = RedactionPolicy(tuple(secret), tuple(pii))

    x = _read(d / "resolution.yaml", problems)
    _unknown("resolution.yaml", x, {f.name for f in fields(ResolutionPolicy)}, problems)
    bx = ResolutionPolicy()
    auto, review = x.get("auto_link_threshold", bx.auto_link_threshold), x.get("review_threshold", bx.review_threshold)
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (auto, review)) or not 0 < review < auto <= 1:
        problems.append("resolution.yaml: need 0 < review_threshold < auto_link_threshold <= 1")
        auto, review = bx.auto_link_threshold, bx.review_threshold
    if x.get("below_review", bx.below_review) not in ("new_entity", "unresolved"):
        problems.append("resolution.yaml below_review: must be new_entity or unresolved")
    minutes = x.get("pending_link_retry_minutes", bx.pending_link_retry_minutes)
    if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes < 1:
        problems.append("resolution.yaml pending_link_retry_minutes: must be a positive integer")
        minutes = bx.pending_link_retry_minutes
    resolution = ResolutionPolicy(float(auto), float(review), x.get("below_review", bx.below_review), int(minutes))

    if problems:
        raise PolicyConfigError(problems)
    return RuntimePolicy(classification, egress, redaction, resolution)
