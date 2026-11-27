from __future__ import annotations

import pickle
from unittest.mock import AsyncMock, MagicMock

import pytest

from usep.adapters.secrets.dev_env import DevEnvSecretResolver
from usep.adapters.vault.resolver import VaultSecretResolver
from usep.adapters.vault.svid import SpiffeSvidProvider
from usep.core.errors import ConfigError
from usep.ingestion.ports.secrets import SecretValue


def test_secret_value_never_reveals_via_repr_or_str() -> None:
    secret = SecretValue("super-secret-token")
    assert repr(secret) == "<redacted>"
    assert str(secret) == "<redacted>"
    assert secret.reveal() == "super-secret-token"


def test_secret_value_cannot_be_pickled() -> None:
    secret = SecretValue("super-secret-token")
    with pytest.raises(TypeError):
        pickle.dumps(secret)


@pytest.mark.asyncio
async def test_dev_resolver_resolves_env_ref() -> None:
    resolver = DevEnvSecretResolver("dev", env={"JIRA_TOKEN": "dev-token-value"})
    value = await resolver.resolve("env:JIRA_TOKEN")
    assert value.reveal() == "dev-token-value"


@pytest.mark.asyncio
async def test_dev_resolver_rejects_non_env_ref() -> None:
    resolver = DevEnvSecretResolver("dev", env={})
    with pytest.raises(ConfigError):
        await resolver.resolve("vault:secret/jira#token")


@pytest.mark.asyncio
async def test_dev_resolver_rejects_missing_env_var() -> None:
    resolver = DevEnvSecretResolver("dev", env={})
    with pytest.raises(ConfigError):
        await resolver.resolve("env:DOES_NOT_EXIST")


def test_dev_resolver_refused_in_prod() -> None:
    """D5: Vault is the only production credential store."""
    with pytest.raises(ConfigError):
        DevEnvSecretResolver("prod", env={})


def test_dev_resolver_refused_in_staging() -> None:
    with pytest.raises(ConfigError):
        DevEnvSecretResolver("staging", env={})


def test_dev_resolver_allowed_in_dev_and_test() -> None:
    DevEnvSecretResolver("dev", env={})
    DevEnvSecretResolver("test", env={})


@pytest.mark.asyncio
async def test_spiffe_svid_provider_delegates_to_client() -> None:
    client = AsyncMock()
    client.fetch_jwt_svid.return_value = "fake.jwt.svid"
    provider = SpiffeSvidProvider(client)
    svid = await provider.fetch_jwt_svid(audience="vault")
    assert svid == "fake.jwt.svid"
    client.fetch_jwt_svid.assert_awaited_once_with("vault")


@pytest.mark.asyncio
async def test_vault_resolver_logs_in_with_svid_and_reads_kv(monkeypatch: pytest.MonkeyPatch) -> None:
    """hvac calls are mocked; no real Vault server involved (section 11: 'hvac and
    SPIFFE calls covered by mocked tests')."""
    svid_provider = AsyncMock()
    svid_provider.fetch_jwt_svid.return_value = "fake.jwt.svid"

    hvac_client = MagicMock()
    hvac_client.auth.jwt.jwt_login.return_value = {"auth": {"client_token": "s.fake"}}
    hvac_client.secrets.kv.v2.read_secret_version.return_value = {
        "data": {"data": {"token": "resolved-secret-value"}}
    }

    resolver = VaultSecretResolver(
        hvac_client,
        svid_provider,
        jwt_auth_mount="jwt",
        kv_mount="secret",
        vault_role="usep-connector",
    )
    value = await resolver.resolve("vault:connectors/jira#token")

    assert value.reveal() == "resolved-secret-value"
    svid_provider.fetch_jwt_svid.assert_awaited_once_with("vault")
    hvac_client.auth.jwt.jwt_login.assert_called_once_with(
        role="usep-connector", jwt="fake.jwt.svid", path="jwt"
    )
    hvac_client.secrets.kv.v2.read_secret_version.assert_called_once_with(
        path="connectors/jira", mount_point="secret"
    )


@pytest.mark.asyncio
async def test_vault_resolver_rejects_non_vault_ref() -> None:
    resolver = VaultSecretResolver(
        MagicMock(), AsyncMock(), jwt_auth_mount="jwt", kv_mount="secret", vault_role="r"
    )
    with pytest.raises(ConfigError):
        await resolver.resolve("env:SOMETHING")


@pytest.mark.asyncio
async def test_vault_resolver_raises_on_missing_field() -> None:
    svid_provider = AsyncMock()
    svid_provider.fetch_jwt_svid.return_value = "fake.jwt.svid"
    hvac_client = MagicMock()
    hvac_client.auth.jwt.jwt_login.return_value = {}
    hvac_client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": {"other_field": "x"}}}

    resolver = VaultSecretResolver(
        hvac_client, svid_provider, jwt_auth_mount="jwt", kv_mount="secret", vault_role="r"
    )
    with pytest.raises(ConfigError):
        await resolver.resolve("vault:connectors/jira#token")
