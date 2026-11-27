"""`DevEnvSecretResolver`: `SecretResolverPort` over environment variables, for development and tests only (D5).

Vault is the only production credential store, so this resolver refuses to be built for staging or prod. It resolves
`env:NAME` references only. A message names the reference or variable, never a value.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from usep.core.config import is_valid_secret_ref
from usep.core.errors import ConfigError
from usep.ingestion.ports.secrets import SecretValue

_ALLOWED_ENVIRONMENTS = frozenset({"dev", "test"})


class DevEnvSecretResolver:
    def __init__(self, environment: str, env: Mapping[str, str] | None = None) -> None:
        if environment not in _ALLOWED_ENVIRONMENTS:
            raise ConfigError("the environment-variable secret resolver is for dev and test only; use Vault in staging and prod")
        self._env: Mapping[str, str] = dict(env) if env is not None else dict(os.environ)

    async def resolve(self, ref: str) -> SecretValue:
        if not is_valid_secret_ref(ref) or not ref.startswith("env:"):
            raise ConfigError("secret reference is not an env: reference")
        name = ref[len("env:"):]
        value = self._env.get(name)
        if value is None:
            raise ConfigError(f"environment variable {name!r} is not set")
        return SecretValue(value)
