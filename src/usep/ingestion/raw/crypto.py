"""AES-256-GCM helpers for the raw payload writer (step 5 of the write algorithm).
No vendor import of a KMS client here — only the `cryptography` package, which is
the cipher primitive itself, not a vendor service client.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

DATA_KEY_SIZE = 32  # 256 bits
NONCE_SIZE = 12  # 96 bits, standard for GCM


def generate_data_key() -> bytes:
    return os.urandom(DATA_KEY_SIZE)


@dataclass(frozen=True, slots=True)
class EncryptedPayload:
    nonce: bytes
    ciphertext: bytes  # includes the GCM authentication tag


def encrypt(plaintext: bytes, data_key: bytes, *, aad: bytes) -> EncryptedPayload:
    nonce = os.urandom(NONCE_SIZE)
    ciphertext = AESGCM(data_key).encrypt(nonce, plaintext, aad)
    return EncryptedPayload(nonce=nonce, ciphertext=ciphertext)


def decrypt(payload: EncryptedPayload, data_key: bytes, *, aad: bytes) -> bytes:
    return AESGCM(data_key).decrypt(payload.nonce, payload.ciphertext, aad)


def pack(payload: EncryptedPayload) -> bytes:
    """Serializes `nonce || ciphertext` into one blob for object storage."""
    return payload.nonce + payload.ciphertext


def unpack(blob: bytes) -> EncryptedPayload:
    return EncryptedPayload(nonce=blob[:NONCE_SIZE], ciphertext=blob[NONCE_SIZE:])
