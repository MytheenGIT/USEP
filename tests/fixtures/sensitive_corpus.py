"""The seeded secret/PII corpus used by `test_seeded_secret_corpus_blocked_before_write`
(section 9, CC-05) and by the raw-writer quarantine tests (PR 6). Every entry is
synthetic: an industry-standard test number, a checksum-valid-but-fabricated
sequence, or a fabricated token shape — never a real credential or a real person's
data (section 5.6, 9: "Never commit a real number.").
"""

from __future__ import annotations

SEEDED_SECRET_CORPUS: list[tuple[str, str]] = [
    # (payload text containing the match, expected reason code)
    (f"token: glpat-{'a' * 20}", "Q-SECRET"),  # SYNTHETIC
    (f"token: ATATT3{'x' * 25}", "Q-SECRET"),  # SYNTHETIC
    (f"key: AKIA{'Q' * 16}", "Q-SECRET"),  # SYNTHETIC
    ("-----BEGIN RSA PRIVATE KEY-----\nMIIB...\n-----END RSA PRIVATE KEY-----", "Q-SECRET"),  # SYNTHETIC
    (f"Authorization: Bearer {'b' * 24}", "Q-SECRET"),
    ("card on file: 4111 1111 1111 1111", "Q-PII"),  # industry-standard test Visa number
    ("applicant id 234567890124 submitted the form", "Q-PII"),  # Verhoeff-valid, sequential, synthetic
    ("pan: ABCDE1234F", "Q-PII"),
    ("ssn: 123-45-6789", "Q-PII"),  # the canonical example SSN used in public specimens
]
