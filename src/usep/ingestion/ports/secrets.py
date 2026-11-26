"""Ports for resolving a secret reference to a short-lived value, and for obtaining
a SPIFFE JWT-SVID to authenticate to Vault (D4, D5).
"""

from __future__ import annotations

from typing import Protocol


class SecretValue:
    """Wraps a resolved secret. `repr()` and `str()` never reveal it, it cannot be
    pickled, and callers must call `.reveal()` — only at the point of use — to get
    the actual string (ground rule, section 1: no secret value in logs).
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "<redacted>"

    def __str__(self) -> str:
        return "<redacted>"

    def __reduce__(self) -> tuple[object, ...]:
        raise TypeError("SecretValue cannot be pickled")


class SecretResolverPort(Protocol):
    """Resolves a reference (`env:NAME` or `vault:path#field`) to a short-lived
    `SecretValue`. Credentials are resolved per call and held only for their lease
    (D5) — nothing caches a `SecretValue` across calls.
    """

    async def resolve(self, ref: str) -> SecretValue: ...


class SvidProviderPort(Protocol):
    """Obtains a JWT-SVID from the SPIFFE Workload API, for the Vault JWT auth
    method to exchange for a Vault token (D4). Pending security-architect
    ratification — see ADR-22 (Proposed).
    """

    async def fetch_jwt_svid(self, audience: str) -> str: ...
