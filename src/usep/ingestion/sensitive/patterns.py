"""Pattern and checksum definitions for the sensitive-data detector (section 5.6).

Every pattern here detects a *shape*, never confirms identity — a Luhn- or
Verhoeff-valid number is still just a number that could plausibly be a real one, and
is treated as a match regardless. Passport, driver's-licence and patient-record
identifiers have no format defined in any source document and are deliberately not
implemented (open item, final report).
"""

from __future__ import annotations

import re

Q_SECRET = "Q-SECRET"  # noqa: S105 - a reason code, not a credential
Q_PII = "Q-PII"

# ---- secrets (Q-SECRET) -----------------------------------------------------------
GITLAB_PAT_RE = re.compile(r"glpat-[A-Za-z0-9_-]{20,}")
ATLASSIAN_TOKEN_RE = re.compile(r"ATATT3[A-Za-z0-9+/_=-]{20,}")
AWS_ACCESS_KEY_RE = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
PEM_PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
BEARER_TOKEN_RE = re.compile(r"Bearer\s+[A-Za-z0-9\-_.=]{20,}")

SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "gitlab_pat": GITLAB_PAT_RE,
    "atlassian_token": ATLASSIAN_TOKEN_RE,
    "aws_access_key": AWS_ACCESS_KEY_RE,
    "pem_private_key": PEM_PRIVATE_KEY_RE,
    "bearer_token": BEARER_TOKEN_RE,
}

# ---- personal data (Q-PII) ---------------------------------------------------------
CARD_CANDIDATE_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
AADHAAR_CANDIDATE_RE = re.compile(r"(?<!\d)[2-9]\d{11}(?!\d)")
PAN_RE = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
SSN_CANDIDATE_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")


def luhn_is_valid(digits: str) -> bool:
    """Standard Luhn check over a cleaned (digits-only) card-number candidate."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


_VERHOEFF_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_VERHOEFF_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def verhoeff_is_valid(digits: str) -> bool:
    """Standard Verhoeff check over a 12-digit Aadhaar-shaped candidate."""
    checksum = 0
    for i, ch in enumerate(reversed(digits)):
        checksum = _VERHOEFF_D[checksum][_VERHOEFF_P[i % 8][int(ch)]]
    return checksum == 0


def ssn_is_plausible(value: str) -> bool:
    """Excludes the invalid area/group/serial ranges (000, 666, 900-999 area; 00
    group; 0000 serial) so an obviously-not-an-SSN NNN-NN-NNNN string doesn't match."""
    area, group, serial = value.split("-")
    if area in ("000", "666") or int(area) >= 900:
        return False
    if group == "00":
        return False
    return serial != "0000"
