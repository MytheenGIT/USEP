"""`VaultSecretResolver`: `SecretResolverPort` backed by a real `hvac.Client` (D4, D5).

The workload obtains a JWT-SVID from the SPIFFE Workload API (`SvidProviderPort`)
and logs in to Vault's JWT auth method with it; the resulting token reads one KV v2
secret per call. `hvac` is synchronous, so every call runs in a worker thread via
`asyncio.to_thread`, consistent with the asyncio worker model (D6).

Docstring per D4: pending security-architect ratification (ADR-22, Proposed).
"""

from __future__ import annotations

import asyncio
from typing import Any

import hvac
import hvac.exceptions

from usep.core.config import VAULT_FIELD_SEPARATOR, VAULT_REF_PREFIX, is_valid_secret_ref
from usep.core.errors import ConfigError
from usep.ingestion.ports.secrets import SecretValue, SvidProviderPort

DEFAULT_AUDIENCE = "vault"


class VaultSecretResolver:
    """Resolves `vault:path#field` references from a Vault KV v2 secret.

    It logs in with a workload JWT before each read.
    """

    def __init__(
        self,
        client: hvac.Client,
        svid_provider: SvidProviderPort,
        *,
        jwt_auth_mount: str,
        kv_mount: str,
        vault_role: str,
        audience: str = DEFAULT_AUDIENCE,
    ) -> None:
        """Build the resolver.

        Args:
            client: Vault client, shared by all calls.
            svid_provider: Source of the workload JWT used to log in.
            jwt_auth_mount: Mount point of Vault's JWT auth method.
            kv_mount: Mount point of the KV v2 secrets engine.
            vault_role: Vault role to log in as.
            audience: Audience requested for the workload JWT.
        """
        self._client = client
        self._svid_provider = svid_provider
        self._jwt_auth_mount = jwt_auth_mount
        self._kv_mount = kv_mount
        self._vault_role = vault_role
        self._audience = audience
        # hvac keeps one token per client: a login must not be replaced by another call's login
        # before its read has run.
        # shortcut: every resolve() logs in again and leaves a Vault token to expire by TTL;
        # upgrade to a token cache refreshed near lease expiry (after security review, ADR-22).
        self._lock = asyncio.Lock()

    async def resolve(self, ref: str) -> SecretValue:
        """Read one field of a Vault secret.

        Args:
            ref: A reference of the form `vault:path#field`.

        Returns:
            The field's value, wrapped so it cannot be logged by accident.

        Raises:
            ConfigError: If `ref` is not a `vault:` reference, Vault cannot be read, or the field is
                missing or not a non-empty string.
        """
        if not is_valid_secret_ref(ref) or not ref.startswith(VAULT_REF_PREFIX):
            raise ConfigError("secret reference is not a vault: reference")
        path, _, field = ref[len(VAULT_REF_PREFIX) :].partition(VAULT_FIELD_SEPARATOR)

        async with self._lock:
            svid = await self._svid_provider.fetch_jwt_svid(self._audience)
            try:
                await asyncio.to_thread(
                    self._client.auth.jwt.jwt_login,
                    role=self._vault_role,
                    jwt=svid,
                    path=self._jwt_auth_mount,
                )
                response: dict[str, Any] = await asyncio.to_thread(
                    self._client.secrets.kv.v2.read_secret_version,
                    path=path,
                    mount_point=self._kv_mount,
                )
                secret_fields = response["data"]["data"]
            except (hvac.exceptions.VaultError, OSError, KeyError, TypeError) as err:
                # OSError covers connection failures raised by the HTTP layer under hvac. The
                # message names the path and exception type only: vendor messages can echo URLs.
                raise ConfigError(f"could not read vault secret at {path!r}: {type(err).__name__}") from err
        if not isinstance(secret_fields, dict) or field not in secret_fields:
            raise ConfigError(f"vault secret at {path!r} has no field named {field!r}")
        value = secret_fields[field]
        if not isinstance(value, str) or not value:
            raise ConfigError(f"vault secret at {path!r} field {field!r} is not a non-empty string")
        return SecretValue(value)
