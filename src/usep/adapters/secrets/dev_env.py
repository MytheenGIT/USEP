"""Resolves `env:NAME` references from environment variables, for development only.

Vault is the only production credential store (D5): constructing this resolver raises `ConfigError` at
startup unless `environment` is exactly dev or test, so a stray wiring mistake or an unexpected
environment name can't reach production with it.
"""

from __future__ import annotations

import os

from usep.core.config import ENV_REF_PREFIX, Environment, is_valid_secret_ref
from usep.core.errors import ConfigError
from usep.ingestion.ports.secrets import SecretValue

_ALLOWED_ENVIRONMENTS = frozenset({Environment.DEV, Environment.TEST})


class DevEnvSecretResolver:
    """Resolves `env:NAME` references from environment variables, for dev and test only."""

    def __init__(self, environment: Environment, *, env: dict[str, str] | None = None) -> None:
        """Build the resolver.

        Args:
            environment: Deployment environment; only dev and test are accepted.
            env: Variables to read instead of `os.environ`.

        Raises:
            ConfigError: If `environment` is not dev or test.
        """
        if environment not in _ALLOWED_ENVIRONMENTS:
            raise ConfigError("DevEnvSecretResolver is only allowed when environment is dev or test (D5)")
        self._env = env if env is not None else dict(os.environ)

    async def resolve(self, ref: str) -> SecretValue:
        """Return the value of the environment variable that an `env:` reference names.

        Args:
            ref: A reference of the form `env:NAME`.

        Returns:
            The variable's value, wrapped so it cannot be logged by accident.

        Raises:
            ConfigError: If `ref` is not an `env:` reference, or the variable is unset or empty.
        """
        if not is_valid_secret_ref(ref) or not ref.startswith(ENV_REF_PREFIX):
            raise ConfigError("secret reference is not an env: reference")
        name = ref[len(ENV_REF_PREFIX) :]
        value = self._env.get(name)
        if not value:
            raise ConfigError(f"environment variable not set or empty: {name}")
        return SecretValue(value)
