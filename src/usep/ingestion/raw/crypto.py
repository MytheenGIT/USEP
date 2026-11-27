"""AES-256-GCM helpers for the raw payload writer (step 5 of the write algorithm).

No vendor import of a KMS client here — only the `cryptography` package, which is the cipher
primitive itself, not a vendor service client.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

DATA_KEY_SIZE = 32  # 256 bits
NONCE_SIZE = 12  # 96 bits, standard for GCM


def generate_data_key() -> bytes:
    """Return a new random 256-bit data key."""
    return os.urandom(DATA_KEY_SIZE)


@dataclass(frozen=True, slots=True)
class EncryptedPayload:
    """A nonce and ciphertext; the ciphertext includes the GCM authentication tag."""

    nonce: bytes
    ciphertext: bytes  # includes the GCM authentication tag


def encrypt(plaintext: bytes, data_key: bytes, *, aad: bytes) -> EncryptedPayload:
    """Encrypt with AES-256-GCM under a fresh random nonce.

    Args:
        plaintext: The bytes to protect.
        data_key: A 256-bit key from `generate_data_key`.
        aad: Additional data that is authenticated but not encrypted; decryption needs the same value.

    Returns:
        The nonce and ciphertext.
    """
    nonce = os.urandom(NONCE_SIZE)
    ciphertext = AESGCM(data_key).encrypt(nonce, plaintext, aad)
    return EncryptedPayload(nonce=nonce, ciphertext=ciphertext)


def decrypt(payload: EncryptedPayload, data_key: bytes, *, aad: bytes) -> bytes:
    """Decrypt a payload made by `encrypt`.

    Args:
        payload: The nonce and ciphertext.
        data_key: The key used to encrypt.
        aad: The additional data used to encrypt.

    Returns:
        The original bytes.

    Raises:
        cryptography.exceptions.InvalidTag: If the key, data or `aad` do not match.
    """
    return AESGCM(data_key).decrypt(payload.nonce, payload.ciphertext, aad)


def pack(payload: EncryptedPayload) -> bytes:
    """Serializes `nonce || ciphertext` into one blob for object storage."""
    return payload.nonce + payload.ciphertext


def unpack(blob: bytes) -> EncryptedPayload:
    """Split a blob made by `pack` back into nonce and ciphertext."""
    return EncryptedPayload(nonce=blob[:NONCE_SIZE], ciphertext=blob[NONCE_SIZE:])
