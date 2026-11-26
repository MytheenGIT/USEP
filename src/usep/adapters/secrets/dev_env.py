"""`DevEnvSecretResolver`: resolves `env:NAME` references from process environment
variables, for local development only (D5). Vault is the only production credential
store — constructing this resolver when `environment` is staging or prod raises
`ConfigError` at startup, so a stray wiring mistake can't reach production with it.
"""

from __future__ import annotations

import os

from usep.core.config import Environment, is_valid_secret_ref
from usep.core.errors import ConfigError
from usep.ingestion.ports.secrets import SecretValue


class DevEnvSecretResolver:
    def __init__(self, environment: Environment, *, env: dict[str, str] | None = None) -> None:
        if environment in ("staging", "prod"):
            raise ConfigError(
                "DevEnvSecretResolver must not be constructed when environment is staging or prod (D5)"
            )
        self._env = env if env is not None else dict(os.environ)

    async def resolve(self, ref: str) -> SecretValue:
        if not is_valid_secret_ref(ref) or not ref.startswith("env:"):
            raise ConfigError("secret reference is not an env: reference")
        name = ref[len("env:") :]
        value = self._env.get(name)
        if value is None:
            raise ConfigError(f"environment variable not set: {name}")
        return SecretValue(value)
