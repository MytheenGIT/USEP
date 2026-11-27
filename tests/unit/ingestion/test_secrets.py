from __future__ import annotations

import asyncio
import pickle
import time
from unittest.mock import AsyncMock, MagicMock

import hvac.exceptions
import pytest

from usep.adapters.secrets.dev_env import DevEnvSecretResolver
from usep.adapters.vault.resolver import VaultSecretResolver
from usep.core.errors import ConfigError
from usep.ingestion.ports.secrets import SecretValue


def _vault(response: object = None) -> tuple[VaultSecretResolver, MagicMock, AsyncMock]:
    """A Vault resolver over a mocked hvac client whose KV read returns `response`.
    No real Vault server is involved."""
    svid_provider = AsyncMock()
    svid_provider.fetch_jwt_svid.return_value = "fake.jwt.svid"
    hvac_client = MagicMock()
    hvac_client.secrets.kv.v2.read_secret_version.return_value = response
    resolver = VaultSecretResolver(
        hvac_client, svid_provider, jwt_auth_mount="jwt", kv_mount="secret", vault_role="usep-connector"
    )
    return resolver, hvac_client, svid_provider


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


@pytest.mark.asyncio
async def test_dev_resolver_rejects_an_empty_env_var() -> None:
    resolver = DevEnvSecretResolver("dev", env={"JIRA_TOKEN": ""})

    with pytest.raises(ConfigError, match="JIRA_TOKEN"):
        await resolver.resolve("env:JIRA_TOKEN")


@pytest.mark.parametrize("environment", ["production", "PROD", "prod ", "", "qa", "staging", "prod"])
def test_dev_resolver_is_refused_for_anything_but_dev_and_test(environment: str) -> None:
    """D5: Vault is the only production credential store."""
    with pytest.raises(ConfigError):
        DevEnvSecretResolver(environment, env={})  # type: ignore[arg-type]


def test_dev_resolver_allowed_in_dev_and_test() -> None:
    DevEnvSecretResolver("dev", env={})
    DevEnvSecretResolver("test", env={})


@pytest.mark.asyncio
async def test_vault_resolver_logs_in_with_svid_and_reads_kv() -> None:
    resolver, hvac_client, svid_provider = _vault({"data": {"data": {"token": "resolved-secret-value"}}})

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
    resolver, _, _ = _vault()
    with pytest.raises(ConfigError):
        await resolver.resolve("env:SOMETHING")


@pytest.mark.asyncio
async def test_vault_resolver_raises_on_missing_field() -> None:
    resolver, _, _ = _vault({"data": {"data": {"other_field": "x"}}})
    with pytest.raises(ConfigError):
        await resolver.resolve("vault:connectors/jira#token")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [hvac.exceptions.Forbidden("denied by https://vault.internal/x"), ConnectionError("down")]
)
async def test_vault_failures_become_config_errors_with_the_cause_kept(failure: Exception) -> None:
    resolver, hvac_client, _ = _vault()
    hvac_client.auth.jwt.jwt_login.side_effect = failure

    with pytest.raises(ConfigError) as exc_info:
        await resolver.resolve("vault:connectors/jira#token")

    assert exc_info.value.__cause__ is failure
    assert "vault.internal" not in str(exc_info.value)
    assert "connectors/jira" in str(exc_info.value)


@pytest.mark.asyncio
async def test_vault_response_without_data_becomes_a_config_error() -> None:
    resolver, _, _ = _vault({"unexpected": "shape"})

    with pytest.raises(ConfigError, match="KeyError"):
        await resolver.resolve("vault:connectors/jira#token")


@pytest.mark.asyncio
@pytest.mark.parametrize("stored", [None, "", 123, ["a"]])
async def test_vault_field_that_is_not_a_non_empty_string_is_rejected(stored: object) -> None:
    resolver, _, _ = _vault({"data": {"data": {"token": stored}}})

    with pytest.raises(ConfigError, match=r"connectors/jira.*token"):
        await resolver.resolve("vault:connectors/jira#token")


@pytest.mark.asyncio
async def test_vault_secret_with_no_data_is_a_config_error_naming_the_path() -> None:
    resolver, _, _ = _vault({"data": {"data": None}})

    with pytest.raises(ConfigError, match="connectors/jira"):
        await resolver.resolve("vault:connectors/jira#token")


@pytest.mark.asyncio
async def test_concurrent_resolves_do_not_interleave_login_and_read() -> None:
    resolver, hvac_client, _ = _vault()
    events: list[str] = []

    def slow_login(**_: object) -> None:
        time.sleep(0.05)
        events.append("login")

    def read(**_: object) -> dict[str, object]:
        events.append("read")
        return {"data": {"data": {"token": "value"}}}

    hvac_client.auth.jwt.jwt_login.side_effect = slow_login
    hvac_client.secrets.kv.v2.read_secret_version.side_effect = read

    await asyncio.gather(resolver.resolve("vault:a/b#token"), resolver.resolve("vault:c/d#token"))

    assert events == ["login", "read", "login", "read"]
