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

from usep.core.config import is_valid_secret_ref
from usep.core.errors import ConfigError
from usep.ingestion.ports.secrets import SecretValue, SvidProviderPort


class VaultSecretResolver:
    def __init__(
        self,
        client: hvac.Client,
        svid_provider: SvidProviderPort,
        *,
        jwt_auth_mount: str,
        kv_mount: str,
        vault_role: str,
        audience: str = "vault",
    ) -> None:
        self._client = client
        self._svid_provider = svid_provider
        self._jwt_auth_mount = jwt_auth_mount
        self._kv_mount = kv_mount
        self._vault_role = vault_role
        self._audience = audience

    async def resolve(self, ref: str) -> SecretValue:
        if not is_valid_secret_ref(ref) or not ref.startswith("vault:"):
            raise ConfigError("secret reference is not a vault: reference")
        path, _, field = ref[len("vault:") :].partition("#")

        svid = await self._svid_provider.fetch_jwt_svid(self._audience)
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
        data = response["data"]["data"]
        if field not in data:
            raise ConfigError(f"vault secret at {path!r} has no field named {field!r}")
        return SecretValue(str(data[field]))
