"""Egress policy: may this record's text leave for an external model or embedding service?

Embeddings are treated as restricted data (HLD 8), and redaction is pattern-based, so the answer is decided here, from the
labels, and recorded on every evidence object as `egress`. A consumer (chunker, embedder, LLM caller) must check it with
`assert_allowed` before sending text anywhere outside the platform boundary. Nothing in this repository calls an external
model yet, so this is a flag and a helper; enforcement belongs in the model gateway (C-09) when it exists.

Fail closed: an unknown ACL means owners only, which is blocked by default. That blocks most records today, because ACL
harvest is partial. Relaxing it is a policy change for the data owners, not a code change: `EgressPolicy`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from usep.pipeline.classify import Labels
from usep.pipeline.redact import RedactionReport


class EgressDenied(Exception):
    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__("egress denied: " + ", ".join(reasons))


@dataclass(frozen=True)
class EgressPolicy:
    max_sensitivity: int = 1             # internal. Confidential (2) and restricted (3) stay inside.
    allow_owners_only: bool = False      # unknown or restricted ACL
    allow_secret_hit: bool = False       # redaction found a secret: the source held one, so hold the whole record back
    allow_pii_hit: bool = False          # redaction found personal data: pattern redaction is not enough proof


def decide(labels: Labels, report: RedactionReport, policy: EgressPolicy = EgressPolicy()) -> dict[str, Any]:
    reasons: list[str] = []
    if labels.sensitivity > policy.max_sensitivity:
        reasons.append(f"sensitivity_{labels.sensitivity}")
    if labels.owners_only and not policy.allow_owners_only:
        reasons.append("owners_only")
    if report.found_secret and not policy.allow_secret_hit:
        reasons.append("secret_found")
    if report.found_pii and not policy.allow_pii_hit:
        reasons.append("pii_found")
    return {"external_model": not reasons, "reasons": reasons}


def assert_allowed(evidence: Mapping[str, Any]) -> None:
    """Raise EgressDenied unless this evidence object may be sent to an external model or embedding service.
    A missing or malformed `egress` block is a denial."""
    egress = evidence.get("egress")
    if not isinstance(egress, Mapping) or egress.get("external_model") is not True:
        raise EgressDenied(list((egress or {}).get("reasons", [])) or ["no_egress_decision"])
