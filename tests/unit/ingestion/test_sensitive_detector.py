from __future__ import annotations

import pytest

from usep.ingestion.sensitive.detector import detect
from usep.ingestion.sensitive.patterns import luhn_is_valid

# Synthetic fixtures only — every value below is a widely recognised test/placeholder
# value (industry-standard test card number, a sequential Aadhaar-shaped number
# constructed solely to pass the Verhoeff checksum, the canonical example SSN used
# in countless public specimens, a fabricated PAN) and identifies no real person or
# credential. Never replace these with real values (section 5.6, 9).
TEST_VISA_CARD = "4111 1111 1111 1111"
SYNTHETIC_AADHAAR = "234567890124"  # Verhoeff-valid, sequential digits, not a real number
SYNTHETIC_PAN = "ABCDE1234F"
EXAMPLE_SSN = "123-45-6789"
FAKE_GITLAB_PAT = "glpat-" + "a" * 20  # SYNTHETIC
FAKE_ATLASSIAN_TOKEN = "ATATT3" + "x" * 25  # SYNTHETIC
FAKE_AWS_ACCESS_KEY = "AKIA" + "Q" * 16  # SYNTHETIC
FAKE_PEM_HEADER = "-----BEGIN RSA PRIVATE KEY-----"  # SYNTHETIC
FAKE_BEARER = "Bearer " + "b" * 24


def test_no_match_on_ordinary_text() -> None:
    result = detect("This issue is about the checkout flow timing out under load.")
    assert result.matched is False
    assert result.counts == {}


def test_detects_gitlab_personal_access_token() -> None:
    result = detect(f"token={FAKE_GITLAB_PAT}")
    assert result.matched is True
    assert result.counts == {"Q-SECRET": 1}


def test_detects_atlassian_api_token() -> None:
    result = detect(f"token={FAKE_ATLASSIAN_TOKEN}")
    assert result.counts == {"Q-SECRET": 1}


def test_detects_aws_access_key() -> None:
    result = detect(f"export AWS_ACCESS_KEY_ID={FAKE_AWS_ACCESS_KEY}")
    assert result.counts == {"Q-SECRET": 1}


def test_detects_pem_private_key_header() -> None:
    result = detect(f"{FAKE_PEM_HEADER}\nMIIBogIBAAJ...\n-----END RSA PRIVATE KEY-----")
    assert result.counts == {"Q-SECRET": 1}


def test_detects_bearer_token_in_free_text() -> None:
    result = detect(f"curl -H 'Authorization: {FAKE_BEARER}' https://example.invalid")
    assert result.counts == {"Q-SECRET": 1}


def test_detects_luhn_valid_card_number() -> None:
    result = detect(f"Card on file: {TEST_VISA_CARD}")
    assert result.counts == {"Q-PII": 1}


def test_does_not_match_luhn_invalid_number_of_card_length() -> None:
    result = detect("Order number: 4111 1111 1111 1112")  # last digit flipped, Luhn-invalid
    assert result.matched is False


def test_detects_verhoeff_valid_aadhaar_shaped_number() -> None:
    result = detect(f"Applicant ID {SYNTHETIC_AADHAAR} submitted the form.")
    assert result.counts == {"Q-PII": 1}


def test_does_not_match_aadhaar_shaped_number_with_bad_checksum() -> None:
    broken = SYNTHETIC_AADHAAR[:-1] + str((int(SYNTHETIC_AADHAAR[-1]) + 1) % 10)
    result = detect(f"Applicant ID {broken} submitted the form.")
    assert result.matched is False


def test_detects_pan() -> None:
    result = detect(f"PAN on file: {SYNTHETIC_PAN}")
    assert result.counts == {"Q-PII": 1}


def test_detects_plausible_ssn() -> None:
    result = detect(f"SSN: {EXAMPLE_SSN}")
    assert result.counts == {"Q-PII": 1}


def test_rejects_implausible_ssn_ranges() -> None:
    for value in ("000-12-3456", "666-12-3456", "900-12-3456", "123-00-4567", "123-45-0000"):
        result = detect(f"SSN: {value}")
        assert result.matched is False, value


def test_mixed_secret_and_pii_counts_both_reason_codes() -> None:
    text = f"token={FAKE_GITLAB_PAT} card={TEST_VISA_CARD}"
    result = detect(text)
    assert result.counts == {"Q-SECRET": 1, "Q-PII": 1}


def test_result_never_carries_the_matched_text() -> None:
    result = detect(f"token={FAKE_GITLAB_PAT}")
    for value in result.counts.values():
        assert isinstance(value, int)
    assert FAKE_GITLAB_PAT not in repr(result)


def _first_luhn_valid_epoch_millis() -> int:
    n = 1_700_000_000_000
    while not luhn_is_valid(str(n)):
        n += 1
    return n


def test_epoch_millisecond_timestamp_that_passes_luhn_is_not_a_card_number() -> None:
    timestamp = _first_luhn_valid_epoch_millis()

    assert detect(f'{{"updatedAt": {timestamp}}}').matched is False


def _first_luhn_valid(prefix: str, length: int) -> str:
    n = int(prefix.ljust(length, "0"))
    while not luhn_is_valid(str(n)):
        n += 1
    return str(n)


@pytest.mark.parametrize(
    "card",
    [
        "5555 5555 5555 4444",
        "3782 822463 10005",
        "6011 1111 1111 1117",
        _first_luhn_valid("7", 16),
        _first_luhn_valid("8", 16),
        _first_luhn_valid("9", 16),
        _first_luhn_valid("1", 15),  # UATP cards are the only ones starting with 1
    ],
)
def test_card_numbers_from_other_networks_are_still_detected(card: str) -> None:
    assert detect(f"card {card}").counts == {"Q-PII": 1}


def test_card_number_written_with_non_ascii_digits_is_still_detected() -> None:
    arabic_indic_visa = (
        "\u0664\u0661\u0661\u0661 \u0661\u0661\u0661\u0661 \u0661\u0661\u0661\u0661 \u0661\u0661\u0661\u0661"
    )

    assert detect(f"card {arabic_indic_visa}").counts == {"Q-PII": 1}
