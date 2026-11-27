"""Configuration: the validated `Settings` schema and the permissive `Config` reader.

Two distinct objects, deliberately:

* `Settings` is a closed, `extra="forbid"` pydantic-settings schema for exactly the
  keys section 7 of the Phase 1 plan defines (`USEP_ENVIRONMENT`, `USEP_TENANT_ID`,
  `connector.runtime.*`, `connector.raw.*`, ...). It is read once at process start by
  the composition root and passed down as an immutable value.
* `Config` is what `usep.ontology.bundle` and `usep.ontology.gate` already depend on
  (`Config.get(key, default=None)`) for dotted keys such as `ontology.dir` and
  `ontology.packs`, which are not part of `Settings`'s schema and must not trip its
  `extra="forbid"` rule. `Config` is a thin, permissive read over the same `USEP_`
  environment-variable namespace (dots become `__`, per D8), with no schema of its
  own — existing code that predates this phase keeps working unmodified.

No secret value is ever read into a plain `str` field on `Settings`: anything
reference-shaped (`env:NAME`, `vault:path#field`) stays a reference until a
`SecretResolverPort` resolves it at the point of use (PR 3).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from usep.core.defaults import (
    DEFAULT_BASE_DELAY_S,
    DEFAULT_DEFER_MAX_S,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_DELAY_S,
    DEFAULT_MAX_PAGES,
    DEFAULT_RECONCILE_INTERVAL_S,
    DEFAULT_TOMBSTONE_MIN_AGE_S,
)
from usep.core.errors import ConfigError


class Environment(StrEnum):
    """Deployment environment. Staging and prod are production-like and get stricter validation."""

    DEV = "dev"
    TEST = "test"
    STAGING = "staging"
    PROD = "prod"


PRODUCTION_LIKE_ENVIRONMENTS = frozenset({Environment.STAGING, Environment.PROD})
ENV_REF_PREFIX = "env:"
VAULT_REF_PREFIX = "vault:"
VAULT_FIELD_SEPARATOR = "#"
UUID_VERSION_7 = 7

_DEV_PLACEHOLDER_TENANT_ID = UUID("00000000-0000-7000-8000-000000000000")
"""The exact placeholder from .env.example. Accepted only when environment == dev (D10)."""


class Config:
    """A generic, permissive dotted-key reader over `USEP_` environment variables.

    `key` such as `"ontology.dir"` maps to the environment variable
    `USEP_ONTOLOGY__DIR` (same transform `Settings` uses via
    `env_nested_delimiter="__"`, applied by hand here since these keys are not part
    of `Settings`'s closed schema). Values are returned as plain strings (or
    `default` when unset); callers coerce them (`bool(...)`, `list(...)`, ...)
    themselves, exactly as `usep.ontology.bundle` already does.
    """

    _ENV_PREFIX = "USEP_"

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        """Build the reader.

        Args:
            env: Variables to read instead of `os.environ`.
        """
        self._env: Mapping[str, str] = dict(env) if env is not None else dict(os.environ)

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for a dotted key.

        Args:
            key: Dotted key such as `ontology.dir`.
            default: Returned when the variable is not set.

        Returns:
            The raw string value, or `default`.
        """
        env_name = self._ENV_PREFIX + key.upper().replace(".", "__")
        return self._env.get(env_name, default)


def is_valid_secret_ref(value: str) -> bool:
    """True if `value` has the shape `env:NAME` or `vault:path#field` (section 5.1).

    Used by `Settings` to validate any field this phase defines ending in `_ref`
    (none yet — per-source `*_ref` fields such as `token_ref` are deferred to the
    connector phase per section 7) and, in PR 3, by the secret resolvers themselves
    to parse a reference before resolving it. Defined here, not in a resolver
    module, so both can depend on one definition without `usep.core` depending on
    anything in `usep.ingestion`.
    """
    if value.startswith(ENV_REF_PREFIX):
        return len(value) > len(ENV_REF_PREFIX)
    if value.startswith(VAULT_REF_PREFIX):
        rest = value[len(VAULT_REF_PREFIX) :]
        path, _, field = rest.partition(VAULT_FIELD_SEPARATOR)
        return bool(path) and bool(field)
    return False


class RetryRuntimeSettings(BaseModel):
    """Attempt cap and back-off bounds for connector HTTP calls."""

    model_config = SettingsConfigDict(frozen=True)

    max_attempts: int = Field(default=DEFAULT_MAX_ATTEMPTS, ge=1, le=20)
    base_delay_s: float = Field(default=DEFAULT_BASE_DELAY_S, gt=0)
    max_delay_s: float = Field(default=DEFAULT_MAX_DELAY_S, gt=0)
    defer_max_s: float = Field(default=DEFAULT_DEFER_MAX_S, gt=0)

    @model_validator(mode="after")
    def _max_at_least_base(self) -> RetryRuntimeSettings:
        if self.max_delay_s < self.base_delay_s:
            raise ConfigError("connector.runtime.retry.max_delay_s must be >= base_delay_s")
        return self


class RateRuntimeSettings(BaseModel):
    """Rate-limit settings for connector HTTP calls."""

    model_config = SettingsConfigDict(frozen=True)

    backfill_fraction: float = Field(default=0.5, gt=0, le=1)


class RuntimeSettings(BaseModel):
    """Connector runtime timing, paging and reconciliation settings."""

    model_config = SettingsConfigDict(frozen=True)

    retry: RetryRuntimeSettings = RetryRuntimeSettings()
    rate: RateRuntimeSettings = RateRuntimeSettings()
    degraded_after_s: int = Field(default=300, gt=0)
    recover_after_s: int = Field(default=600, gt=0)
    reconcile_interval_s: int = Field(default=DEFAULT_RECONCILE_INTERVAL_S, gt=0)
    tombstone_min_age_s: int = Field(default=DEFAULT_TOMBSTONE_MIN_AGE_S, gt=0)
    max_pages: int = Field(default=DEFAULT_MAX_PAGES, gt=0)
    poll_interval_s: int = Field(default=900, ge=60)


class ConnectorRawSettings(BaseModel):
    """Settings for raw-payload storage."""

    model_config = SettingsConfigDict(frozen=True)

    retention_days: int = Field(default=365, gt=0)
    encrypt: bool = True


class ConnectorSettings(BaseModel):
    """Connector settings: runtime behaviour and raw-payload storage."""

    model_config = SettingsConfigDict(frozen=True)

    runtime: RuntimeSettings = RuntimeSettings()
    raw: ConnectorRawSettings = ConnectorRawSettings()


class Settings(BaseSettings):
    """The validated configuration schema for everything this phase defines (section 7).

    Per-source keys (`token_ref` and similar) are explicitly out of scope for this
    phase (section 7: "Per-source keys ... are not defined in this phase. They
    come with the connector work.") and are not fields here.
    """

    model_config = SettingsConfigDict(
        env_prefix="USEP_",
        env_nested_delimiter="__",
        extra="forbid",
        frozen=True,
    )

    environment: Environment = Environment.DEV
    tenant_id: UUID
    vault_addr: str | None = None
    vault_jwt_auth_mount: str = "jwt"
    vault_kv_mount: str = "secret"
    kms_key_alias: str | None = None
    connector: ConnectorSettings = ConnectorSettings()

    @model_validator(mode="after")
    def _validate_tenant_id(self) -> Settings:
        if self.tenant_id == _DEV_PLACEHOLDER_TENANT_ID and self.environment != Environment.DEV:
            raise ConfigError("tenant_id: the .env.example placeholder is only accepted when environment=dev")
        if self.tenant_id.version != UUID_VERSION_7:
            raise ConfigError("tenant_id: must be a UUID v7")
        return self

    @model_validator(mode="after")
    def _validate_production_rules(self) -> Settings:
        if self.environment in PRODUCTION_LIKE_ENVIRONMENTS:
            if not self.vault_addr:
                raise ConfigError("vault_addr: required when environment is staging or prod")
            if not self.kms_key_alias:
                raise ConfigError("kms_key_alias: required when environment is staging or prod")
        if self.environment != Environment.DEV and not self.connector.raw.encrypt:
            raise ConfigError("connector.raw.encrypt: must be true outside environment=dev")
        return self
