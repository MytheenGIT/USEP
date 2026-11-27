from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from usep.core.config import Config, RetryRuntimeSettings, Settings, is_valid_secret_ref
from usep.core.errors import ConfigError

DEV_PLACEHOLDER = "00000000-0000-7000-8000-000000000000"
A_REAL_V7 = "01932f3e-7a21-7f3e-8a21-0123456789ab"


def test_config_get_maps_dotted_key_to_env_var() -> None:
    config = Config(env={"USEP_ONTOLOGY__DIR": "ontology", "USEP_ONTOLOGY__PACKS": "pack-a,pack-b"})
    assert config.get("ontology.dir") == "ontology"
    assert config.get("ontology.packs") == "pack-a,pack-b"


def test_config_get_returns_default_when_unset() -> None:
    config = Config(env={})
    assert config.get("ontology.dir") is None
    assert config.get("ontology.allow_reference_packs", False) is False


def test_settings_defaults_load_with_minimal_env() -> None:
    settings = Settings(_env_file=None, environment="dev", tenant_id=UUID(DEV_PLACEHOLDER))  # type: ignore[call-arg]
    assert settings.connector.runtime.retry.max_attempts == 5
    assert settings.connector.runtime.rate.backfill_fraction == 0.5
    assert settings.connector.raw.retention_days == 365


def test_settings_extra_forbid_rejects_unknown_key() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            environment="dev",
            tenant_id=UUID(DEV_PLACEHOLDER),
            something_unexpected="x",  # type: ignore[call-arg]
        )


def test_dev_placeholder_tenant_id_rejected_outside_dev() -> None:
    with pytest.raises(ConfigError):
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            environment="test",
            tenant_id=UUID(DEV_PLACEHOLDER),
        )


def test_dev_placeholder_tenant_id_accepted_in_dev() -> None:
    settings = Settings(_env_file=None, environment="dev", tenant_id=UUID(DEV_PLACEHOLDER))  # type: ignore[call-arg]
    assert settings.tenant_id == UUID(DEV_PLACEHOLDER)


def test_non_v7_tenant_id_rejected() -> None:
    not_v7 = UUID("00000000-0000-4000-8000-000000000000")  # version 4, not 7
    with pytest.raises(ConfigError):
        Settings(_env_file=None, environment="dev", tenant_id=not_v7)  # type: ignore[call-arg]


def test_staging_requires_vault_addr_and_kms_key_alias() -> None:
    with pytest.raises(ConfigError):
        Settings(_env_file=None, environment="staging", tenant_id=UUID(A_REAL_V7))  # type: ignore[call-arg]


def test_staging_passes_with_vault_and_kms_configured() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="staging",
        tenant_id=UUID(A_REAL_V7),
        vault_addr="https://vault.internal:8200",
        kms_key_alias="alias/usep-pilot",
    )
    assert settings.environment == "staging"


def test_encrypt_must_be_true_outside_dev() -> None:
    with pytest.raises(ConfigError):
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            environment="test",
            tenant_id=UUID(A_REAL_V7),
            connector={"raw": {"encrypt": False}},
        )


def test_retry_max_delay_must_be_at_least_base_delay() -> None:
    with pytest.raises(ConfigError):
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            environment="dev",
            tenant_id=UUID(DEV_PLACEHOLDER),
            connector={"runtime": {"retry": {"base_delay_s": 10, "max_delay_s": 5}}},
        )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("env:JIRA_TOKEN", True),
        ("vault:secret/jira#token", True),
        ("vault:secret/jira", False),
        ("vault:#token", False),
        ("env:", False),
        ("glpat-abcdefghijklmnopqrst", False),  # SYNTHETIC
        ("", False),
    ],
)
def test_is_valid_secret_ref(value: str, expected: bool) -> None:
    assert is_valid_secret_ref(value) is expected


def test_retry_policy_needs_at_least_one_attempt() -> None:
    with pytest.raises(ValidationError):
        RetryRuntimeSettings(max_attempts=0)
