"""Secret and personal-data redaction (C-02, 'Normalize -> classify -> redact').

Runs before the normalized text is stored or sent to any model (diagram B4: source ACL and redaction policy must
apply before external model egress). It replaces a match with [REDACTED:<kind>] and reports kinds and counts, never
the matched value. The raw snapshot in S3 is untouched: whether the write-once store may hold secrets is an open
design point (HLD 4.6, Appendix A) and needs an ADR before it changes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S)),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("gitlab_token", re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/\-]{20,}=*")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("credential_assignment", re.compile(
        r"(?i)\b(password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)\b(\s*[:=]\s*)(?!\[REDACTED)[^\s\"',;]{4,}")),
    ("connection_string_password", re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^\s:/@]+:)[^\s@/]+(@)")),
)
PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("card_number", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
)


@dataclass
class RedactionReport:
    secrets: dict[str, int] = field(default_factory=dict)
    pii: dict[str, int] = field(default_factory=dict)

    @property
    def found_secret(self) -> bool:
        return bool(self.secrets)

    @property
    def found_pii(self) -> bool:
        return bool(self.pii)

    def merge(self, other: "RedactionReport") -> None:
        for mine, theirs in ((self.secrets, other.secrets), (self.pii, other.pii)):
            for k, n in theirs.items():
                mine[k] = mine.get(k, 0) + n

    def as_dict(self) -> dict[str, dict[str, int]]:
        return {"secrets": dict(self.secrets), "pii": dict(self.pii)}


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total, alt = total + d, not alt
    return total % 10 == 0


def redact_text(text: str) -> tuple[str, RedactionReport]:
    report = RedactionReport()
    for kind, pat in SECRET_PATTERNS:
        def sub(m: re.Match[str], kind: str = kind) -> str:
            report.secrets[kind] = report.secrets.get(kind, 0) + 1
            if kind == "credential_assignment":
                return f"{m.group(1)}{m.group(2)}[REDACTED:{kind}]"
            if kind == "connection_string_password":
                return f"{m.group(1)}[REDACTED:{kind}]{m.group(2)}"
            return f"[REDACTED:{kind}]"
        text = pat.sub(sub, text)
    for kind, pat in PII_PATTERNS:
        def sub_pii(m: re.Match[str], kind: str = kind) -> str:
            if kind == "card_number" and not _luhn(re.sub(r"\D", "", m.group(0))):
                return m.group(0)
            report.pii[kind] = report.pii.get(kind, 0) + 1
            return f"[REDACTED:{kind}]"
        text = pat.sub(sub_pii, text)
    return text, report


def redact_value(value: Any) -> tuple[Any, RedactionReport]:
    """Redact every string inside a JSON-like value. Keys are kept."""
    report = RedactionReport()
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            out[k], r = redact_value(v)
            report.merge(r)
        return out, report
    if isinstance(value, (list, tuple)):
        items = []
        for v in value:
            nv, r = redact_value(v)
            items.append(nv)
            report.merge(r)
        return items, report
    return value, report
