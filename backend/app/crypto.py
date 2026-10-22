"""Envelope encryption with a KMS abstraction, plus pseudonymisation.

Each patient payload is encrypted with a random 256-bit data key (DEK, AES-GCM). The DEK is
wrapped with the owning hospital's key-encryption key (KEK). Sharing re-wraps the DEK for the
recipient hospital, so revocation = deleting that wrapped DEK.

`FileKMS` stores KEKs as files on local disk. **It is an INSECURE development stub**: in
production use a real KMS/HSM (AWS KMS, Azure Key Vault, GCP KMS, HashiCorp Vault Transit) by
implementing the same two methods.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import get_settings


class KMS(Protocol):
    def wrap(self, tenant: str, dek: bytes) -> bytes: ...
    def unwrap(self, tenant: str, wrapped: bytes) -> bytes: ...


class FileKMS:
    """INSECURE: development-only key storage on the local filesystem."""

    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _kek(self, tenant: str) -> bytes:
        p = self.dir / f"{tenant}.kek"
        if not p.exists():
            p.write_bytes(AESGCM.generate_key(bit_length=256))
        return p.read_bytes()

    def wrap(self, tenant: str, dek: bytes) -> bytes:
        nonce = os.urandom(12)
        return nonce + AESGCM(self._kek(tenant)).encrypt(nonce, dek, tenant.encode())

    def unwrap(self, tenant: str, wrapped: bytes) -> bytes:
        return AESGCM(self._kek(tenant)).decrypt(wrapped[:12], wrapped[12:], tenant.encode())


_kms: KMS | None = None


def get_kms() -> KMS:
    global _kms
    if _kms is None:
        _kms = FileKMS(get_settings().kms_dir)
    return _kms


def encrypt_payload(tenant: str, plaintext: bytes, aad: bytes) -> tuple[bytes, bytes, bytes]:
    dek = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    ct = AESGCM(dek).encrypt(nonce, plaintext, aad)
    return ct, nonce, get_kms().wrap(tenant, dek)


def decrypt_payload(tenant: str, wrapped_dek: bytes, nonce: bytes, ct: bytes, aad: bytes) -> bytes:
    dek = get_kms().unwrap(tenant, wrapped_dek)
    return AESGCM(dek).decrypt(nonce, ct, aad)


def rewrap(from_tenant: str, to_tenant: str, wrapped: bytes) -> bytes:
    kms = get_kms()
    return kms.wrap(to_tenant, kms.unwrap(from_tenant, wrapped))


def pseudonymize(hospital_code: str, local_id: str) -> str:
    """Keyed hash: stable per (hospital, local id), not reversible without the key."""
    key = get_settings().pseudonym_key.encode()
    return "PX-" + hmac.new(key, f"{hospital_code}:{local_id}".encode(), hashlib.sha256).hexdigest()[:16].upper()
