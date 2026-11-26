"""The sensitive-data detector: a pure function over text, returning counts and
reason codes only (D3, section 5.6). It never returns matched text, and its result
must never be logged or stored beyond the counts themselves.
"""

from __future__ import annotations

from usep.ingestion.domain.sensitive import DetectionResult
from usep.ingestion.sensitive import patterns as p


def _count_secrets(text: str) -> int:
    return sum(len(pattern.findall(text)) for pattern in p.SECRET_PATTERNS.values())


def _count_pii(text: str) -> int:
    count = 0
    for match in p.CARD_CANDIDATE_RE.finditer(text):
        cleaned = "".join(ch for ch in match.group() if ch.isdigit())
        if 13 <= len(cleaned) <= 19 and p.luhn_is_valid(cleaned):
            count += 1
    for match in p.AADHAAR_CANDIDATE_RE.finditer(text):
        if p.verhoeff_is_valid(match.group()):
            count += 1
    count += len(p.PAN_RE.findall(text))
    for match in p.SSN_CANDIDATE_RE.finditer(text):
        if p.ssn_is_plausible(match.group()):
            count += 1
    return count


def detect(text: str) -> DetectionResult:
    """Scan `text` for secret and personal-data shapes. Returns counts keyed by
    reason code (`Q-SECRET`, `Q-PII`) with zero-count keys omitted, and `matched`
    true if either count is non-zero.

    Passport, driver's-licence and patient-record identifiers are not detected —
    no format is defined in any source document (section 5.6: "Do not guess").
    """
    raw_counts = {"Q-SECRET": _count_secrets(text), "Q-PII": _count_pii(text)}
    counts = {code: count for code, count in raw_counts.items() if count}
    return DetectionResult(counts=counts, matched=bool(counts))
