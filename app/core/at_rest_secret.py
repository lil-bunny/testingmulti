"""Encrypt / decrypt small secrets at rest using Fernet (optional key)."""

from __future__ import annotations

from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


def _fernet_from_key(key_b64: str) -> Fernet:
    return Fernet(key_b64.encode("ascii"))


def encrypt_password(plain: str, key_b64: Optional[str]) -> str:
    if not key_b64:
        # Dev-only: not secret; do not use in production without a real key
        return "plain:" + plain
    return _fernet_from_key(key_b64).encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_password(stored: str, key_b64: Optional[str]) -> str:
    # Explicit plaintext-at-rest marker (dev / legacy); strip before Fernet path.
    if stored.startswith("plain:"):
        return stored[len("plain:") :]
    if not key_b64:
        raise ValueError("TURVO_OAUTH_ENCRYPTION_KEY is required to decrypt stored password")
    try:
        return _fernet_from_key(key_b64).decrypt(stored.encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        raise ValueError("Could not decrypt stored password (wrong key or corrupted data)") from e
