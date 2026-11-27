"""Configuration: `Settings` (the validated schema this phase defines) and `Config`
(a narrower, permissive dotted-key facade for callers outside that schema).

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
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from usep.core.errors import ConfigError

Environment = Literal["dev", "test", "staging", "prod"]

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
        self._env: Mapping[str, str] = dict(env) if env is not None else dict(os.environ)

    def get(self, key: str, default: Any = None) -> Any:
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
    if value.startswith("env:"):
        return len(value) > len("env:")
    if value.startswith("vault:"):
        rest = value[len("vault:") :]
        path, _, field = rest.partition("#")
        return bool(path) and bool(field)
    return False


class RetryRuntimeSettings(BaseModel):
    model_config = SettingsConfigDict(frozen=True)

    max_attempts: int = Field(default=5, ge=1, le=20)
    base_delay_s: float = Field(default=2.0, gt=0)
    max_delay_s: float = Field(default=600.0, gt=0)
    defer_max_s: float = Field(default=86400.0, gt=0)

    @model_validator(mode="after")
    def _max_at_least_base(self) -> RetryRuntimeSettings:
        if self.max_delay_s < self.base_delay_s:
            raise ConfigError("connector.runtime.retry.max_delay_s must be >= base_delay_s")
        return self


class RateRuntimeSettings(BaseModel):
    model_config = SettingsConfigDict(frozen=True)

    backfill_fraction: float = Field(default=0.5, gt=0, le=1)


class RuntimeSettings(BaseModel):
    model_config = SettingsConfigDict(frozen=True)

    retry: RetryRuntimeSettings = RetryRuntimeSettings()
    rate: RateRuntimeSettings = RateRuntimeSettings()
    degraded_after_s: int = Field(default=300, gt=0)
    recover_after_s: int = Field(default=600, gt=0)
    reconcile_interval_s: int = Field(default=86400, gt=0)
    tombstone_min_age_s: int = Field(default=72000, gt=0)
    max_pages: int = Field(default=10_000, gt=0)
    poll_interval_s: int = Field(default=900, ge=60)


class ConnectorRawSettings(BaseModel):
    model_config = SettingsConfigDict(frozen=True)

    retention_days: int = Field(default=365, gt=0)
    encrypt: bool = True


class ConnectorSettings(BaseModel):
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

    environment: Environment = "dev"
    tenant_id: UUID
    vault_addr: str | None = None
    vault_jwt_auth_mount: str = "jwt"
    vault_kv_mount: str = "secret"
    kms_key_alias: str | None = None
    connector: ConnectorSettings = ConnectorSettings()

    @model_validator(mode="after")
    def _validate_tenant_id(self) -> Settings:
        if self.tenant_id == _DEV_PLACEHOLDER_TENANT_ID and self.environment != "dev":
            raise ConfigError("tenant_id: the .env.example placeholder is only accepted when environment=dev")
        if self.tenant_id.version != 7:
            raise ConfigError("tenant_id: must be a UUID v7")
        return self

    @model_validator(mode="after")
    def _validate_production_rules(self) -> Settings:
        if self.environment in ("staging", "prod"):
            if not self.vault_addr:
                raise ConfigError("vault_addr: required when environment is staging or prod")
            if not self.kms_key_alias:
                raise ConfigError("kms_key_alias: required when environment is staging or prod")
        if self.environment != "dev" and not self.connector.raw.encrypt:
            raise ConfigError("connector.raw.encrypt: must be true outside environment=dev")
        return self
