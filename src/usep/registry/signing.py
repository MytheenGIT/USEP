"""Signing and verification of release manifests.

Two signers behind one port: `KmsSigner` (production: the private key never leaves AWS KMS; ECDSA P-256 with SHA-256) and
`Ed25519Signer` (development and tests: a key held in a file). Verification is offline against a trust store committed to Git
(`config/registry/trusted_keys.yaml`): key id, algorithm, public key, status (active or revoked) and an optional expiry.
A revoked or expired key, an unknown key, an unsupported algorithm or a bad signature all fail the same way.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519

from usep.registry.errors import RegistryError

ED25519, ECDSA = "ed25519", "ecdsa-p256-sha256"


class Signer(Protocol):
    key_id: str
    alg: str

    def sign(self, data: bytes) -> bytes: ...


class Ed25519Signer:
    alg = ED25519

    def __init__(self, private_key: ed25519.Ed25519PrivateKey, key_id: str) -> None:
        self._key, self.key_id = private_key, key_id

    @classmethod
    def generate(cls, key_id: str) -> "Ed25519Signer":
        return cls(ed25519.Ed25519PrivateKey.generate(), key_id)

    @classmethod
    def from_pem_file(cls, path: str | Path, key_id: str) -> "Ed25519Signer":
        key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
        if not isinstance(key, ed25519.Ed25519PrivateKey):
            raise RegistryError("not an Ed25519 private key")
        return cls(key, key_id)

    def sign(self, data: bytes) -> bytes:
        return self._key.sign(data)

    def private_pem(self) -> bytes:
        return self._key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())

    def public_pem(self) -> str:
        return self._key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


class KmsSigner:
    """AWS KMS asymmetric key, key spec ECC_NIST_P256, usage SIGN_VERIFY. The client is injected (boto3 'kms')."""
    alg = ECDSA

    def __init__(self, client: Any, key_arn: str) -> None:
        self._kms, self.key_id = client, key_arn

    def sign(self, data: bytes) -> bytes:
        r = self._kms.sign(KeyId=self.key_id, Message=data, MessageType="RAW", SigningAlgorithm="ECDSA_SHA_256")
        return r["Signature"]                                           # DER encoded, which is what verify() expects

    def public_pem(self) -> str:
        der = self._kms.get_public_key(KeyId=self.key_id)["PublicKey"]
        return serialization.load_der_public_key(der).public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


@dataclass(frozen=True)
class TrustedKey:
    key_id: str
    alg: str
    public_key_pem: str
    status: str = "active"                 # active | revoked
    not_after: str | None = None           # ISO 8601 UTC


class TrustStore:
    def __init__(self, keys: list[TrustedKey]) -> None:
        self._keys = {k.key_id: k for k in keys}

    @classmethod
    def load(cls, path: str | Path) -> "TrustStore":
        p = Path(path)
        doc = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.is_file() else {}
        keys = []
        for row in doc.get("keys") or []:
            if set(row) - {"key_id", "alg", "public_key_pem", "status", "not_after"} or not {"key_id", "alg", "public_key_pem"} <= set(row):
                raise RegistryError(f"trust store: bad key entry {row.get('key_id')!r}")
            if row["alg"] not in (ED25519, ECDSA) or row.get("status", "active") not in ("active", "revoked"):
                raise RegistryError(f"trust store: unsupported alg or status for {row['key_id']}")
            keys.append(TrustedKey(str(row["key_id"]), row["alg"], str(row["public_key_pem"]), row.get("status", "active"),
                                   str(row["not_after"]) if row.get("not_after") else None))
        return cls(keys)

    def verify(self, data: bytes, signature: dict[str, str], now: datetime | None = None) -> str:
        """Return the key id that signed `data`, or raise RegistryError. One message for every failure: no oracle."""
        fail = RegistryError("signature is not valid for any trusted, active key")
        key = self._keys.get(signature.get("key_id", ""))
        if key is None or key.status != "active" or key.alg != signature.get("alg"):
            raise fail
        if key.not_after and (now or datetime.now(timezone.utc)) > datetime.fromisoformat(key.not_after.replace("Z", "+00:00")):
            raise fail
        try:
            sig = base64.b64decode(signature["sig"], validate=True)
            pub = serialization.load_pem_public_key(key.public_key_pem.encode())
            if key.alg == ED25519:
                if not isinstance(pub, ed25519.Ed25519PublicKey):
                    raise fail
                pub.verify(sig, data)
            else:
                if not isinstance(pub, ec.EllipticCurvePublicKey) or pub.curve.name != "secp256r1":
                    raise fail
                pub.verify(sig, data, ec.ECDSA(hashes.SHA256()))
        except (InvalidSignature, ValueError, KeyError) as exc:
            raise fail from exc
        return key.key_id


def sign_body(signer: Signer, body_bytes: bytes) -> dict[str, str]:
    return {"alg": signer.alg, "key_id": signer.key_id, "sig": base64.b64encode(signer.sign(body_bytes)).decode()}
