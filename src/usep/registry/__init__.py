"""Ontology registry (C-06) and pack signing (C-07). Decision record: docs/adr/ADR-20-ontology-registry-and-signing.md.

Git stays the source of the definitions. Publishing turns a reviewed, checked version into an immutable, signed release in
the registry; a tenant's pins say which releases it runs. Services load pinned releases from the registry, verify them
against a trust store, and fail closed on anything unsigned, altered, revoked or unpinned.
"""
from usep.registry.client import RegistryClient
from usep.registry.errors import RegistryError
from usep.registry.registry import Registry
from usep.registry.signing import Ed25519Signer, KmsSigner, TrustStore

__all__ = ["Ed25519Signer", "KmsSigner", "Registry", "RegistryClient", "RegistryError", "TrustStore"]
