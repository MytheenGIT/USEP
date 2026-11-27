"""Labelling: sensitivity, ACL state and owner restriction for one record (C-02 'classify').

Sensitivity is the core 0..3 vocabulary (0 public, 1 internal, 2 confidential, 3 restricted). The result only ever
goes up: a rule can raise it, nothing here lowers it. Labels that mark regulated content (pci, pii, ...) and secrets
found by redaction raise it; personal data found raises it to confidential. The default is `internal`, because the
source is an enterprise system and no source here states that content is public.

ACL: unknown or stale means the entity is visible to its owners only until the next sync (HLD 4.5).
`owners_only` is set in that case so the fabric writer and the context engine can enforce it without re-deriving it.
The thresholds and label lists are configuration (`ClassificationPolicy`), proposals until the data owners set them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from usep.pipeline.normalize import Acl
from usep.pipeline.redact import RedactionReport


@dataclass(frozen=True)
class ClassificationPolicy:
    default_sensitivity: int = 1
    label_sensitivity: dict[str, int] = field(default_factory=lambda: {
        "public": 0, "internal": 1, "confidential": 2, "pii": 2, "gdpr": 2, "restricted": 3, "pci": 3,
        "secret": 3, "security": 2, "hr": 3})
    pii_floor: int = 2
    secret_floor: int = 3
    restricted_acl_floor: int = 2         # something deliberately restricted at source is at least confidential


@dataclass(frozen=True)
class Labels:
    sensitivity: int
    acl_state: str                        # known | unknown | stale
    owners_only: bool
    acl_ref: str | None
    reasons: tuple[str, ...]


def classify(labels: list[str], acl: Acl, report: RedactionReport,
             policy: ClassificationPolicy = ClassificationPolicy()) -> Labels:
    level, reasons = policy.default_sensitivity, ["default"]

    def raise_to(n: int, why: str) -> None:
        nonlocal level
        if n > level:
            level = n
        reasons.append(f"{why}>={n}")

    for lab in labels:
        if lab in policy.label_sensitivity:
            raise_to(policy.label_sensitivity[lab], f"label:{lab}")
    if report.found_secret:
        raise_to(policy.secret_floor, "secret")
    if report.found_pii:
        raise_to(policy.pii_floor, "pii")
    if acl.known and acl.restricted:
        raise_to(policy.restricted_acl_floor, "acl_restricted")
    state = "known" if acl.known else "unknown"
    acl_ref = f"{acl.scheme}:{','.join(acl.principals)}" if acl.known and acl.principals else None
    return Labels(level, state, owners_only=state != "known" or acl.restricted, acl_ref=acl_ref, reasons=tuple(reasons))
