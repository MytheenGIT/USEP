from __future__ import annotations

from uuid import UUID

import pytest

from usep.core.errors import ConfigError
from usep.ingestion.sensitive.settings_guard import load_settings

DEV_PLACEHOLDER = UUID("00000000-0000-7000-8000-000000000000")
FAKE_GITLAB_PAT = "glpat-" + "a" * 20  # SYNTHETIC


def test_load_settings_passes_with_clean_values() -> None:
    settings = load_settings(_env_file=None, environment="dev", tenant_id=DEV_PLACEHOLDER)  # type: ignore[call-arg]
    assert settings.environment == "dev"


def test_config_rejects_plaintext_secret_without_echo() -> None:
    """POC §2, D5: a credential-shaped value in any string config field is rejected
    at load time, and the error never echoes the value itself."""
    with pytest.raises(ConfigError) as exc_info:
        load_settings(
            _env_file=None,  # type: ignore[call-arg]
            environment="dev",
            tenant_id=DEV_PLACEHOLDER,
            kms_key_alias=FAKE_GITLAB_PAT,
        )
    message = str(exc_info.value)
    assert FAKE_GITLAB_PAT not in message
    assert "kms_key_alias" in message
    assert "gitlab_pat" in message


def test_config_rejects_plaintext_secret_in_nested_field() -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_settings(
            _env_file=None,  # type: ignore[call-arg]
            environment="dev",
            tenant_id=DEV_PLACEHOLDER,
            vault_addr=f"https://vault.internal/{FAKE_GITLAB_PAT}",
        )
    assert FAKE_GITLAB_PAT not in str(exc_info.value)


def test_missing_required_setting_raises_config_error_naming_the_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("USEP_TENANT_ID", raising=False)

    with pytest.raises(ConfigError, match="tenant_id: missing"):
        load_settings(_env_file=None, environment="dev")  # type: ignore[call-arg]


def test_invalid_setting_raises_config_error_without_echoing_the_input() -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_settings(_env_file=None, environment="dev", tenant_id=FAKE_GITLAB_PAT)  # type: ignore[call-arg]

    assert "tenant_id" in str(exc_info.value)
    assert FAKE_GITLAB_PAT not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
