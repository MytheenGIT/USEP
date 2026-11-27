"""Ports for resolving secret references and obtaining a SPIFFE JWT-SVID.

The secret is short-lived, and the SPIFFE JWT-SVID authenticates to Vault (D4, D5).
"""

from __future__ import annotations

from typing import Protocol

REDACTED = "<redacted>"


class SecretValue:
    """Wraps a resolved secret.

    `repr()` and `str()` never reveal it, it cannot be pickled, and callers must call `.reveal()` —
    only at the point of use — to get the actual string (ground rule, section 1: no secret value in
    logs).
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        """Wrap a secret.

        Args:
            value: The secret.
        """
        self._value = value

    def reveal(self) -> str:
        """Return the secret. Call this only at the point of use."""
        return self._value

    def __repr__(self) -> str:
        """Return a placeholder, never the secret."""
        return REDACTED

    def __str__(self) -> str:
        """Return a placeholder, never the secret."""
        return REDACTED

    def __reduce__(self) -> tuple[object, ...]:
        """Refuse to be pickled, so the secret cannot be serialized.

        Raises:
            TypeError: Always.
        """
        raise TypeError("SecretValue cannot be pickled")


class SecretResolverPort(Protocol):
    """Resolves a reference (`env:NAME` or `vault:path#field`) to a short-lived `SecretValue`.

    Credentials are resolved per call and held only for their lease (D5) — nothing caches a
    `SecretValue` across calls.
    """

    async def resolve(self, ref: str) -> SecretValue:
        """Resolve a secret reference to its value.

        Args:
            ref: A reference of the form `env:NAME` or `vault:path#field`.

        Returns:
            The secret, wrapped so it cannot be logged by accident.

        Raises:
            ConfigError: If the reference is the wrong kind or cannot be resolved.
        """


class SvidProviderPort(Protocol):
    """Obtains a JWT-SVID from the SPIFFE Workload API.

    The Vault JWT auth method exchanges it for a Vault token (D4).

    Pending security-architect ratification — see ADR-22 (Proposed).
    """

    async def fetch_jwt_svid(self, audience: str) -> str:
        """Return a JWT-SVID from the SPIFFE Workload API.

        Args:
            audience: Audience the token is issued for.

        Returns:
            The signed JWT.
        """
