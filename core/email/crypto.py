"""Fernet-based credential encryption for the PaliMind email module.

Key derivation strategy (in priority order):
1. /etc/machine-id  (Linux)       — SHA-256 → 32-byte Fernet key
2. macOS IOPlatformUUID           — SHA-256 → 32-byte Fernet key
3. File-based key at ~/.palimind/email.key  (fallback, created on first use)

Passwords are never logged or exposed to AI prompts.
"""
from __future__ import annotations

import base64
import hashlib
import os
import platform
import subprocess
from functools import lru_cache
from pathlib import Path

from core.email.exceptions import EmailCryptoError

# Lazy import so the cryptography package is optional until email commands are used.
try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError as _err:  # pragma: no cover
    raise ImportError(
        "The 'cryptography' package is required for the email module. "
        "Install it with: pip install cryptography"
    ) from _err

_EMAIL_KEY_FILE = Path.home() / ".palimind" / "email.key"


def _machine_uuid() -> str | None:
    """Return the machine UUID string, or None if unavailable."""
    system = platform.system()
    try:
        if system == "Linux":
            p = Path("/etc/machine-id")
            if p.exists():
                return p.read_text(encoding="ascii").strip()
        elif system == "Darwin":
            result = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                if "IOPlatformUUID" in line:
                    return line.split('"')[-2]
        elif system == "Windows":
            result = subprocess.run(
                ["wmic", "csproduct", "get", "uuid"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
            if len(lines) >= 2:
                return lines[1]
    except Exception:
        pass
    return None


def _derive_key_from_uuid(uuid_str: str) -> bytes:
    """SHA-256 the UUID string and base64url-encode the first 32 bytes."""
    digest = hashlib.sha256(uuid_str.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest[:32])


def _load_or_create_file_key() -> bytes:
    """Load (or create) a random key stored in ~/.palimind/email.key."""
    _EMAIL_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if _EMAIL_KEY_FILE.exists():
        return _EMAIL_KEY_FILE.read_bytes().strip()
    key = Fernet.generate_key()
    _EMAIL_KEY_FILE.write_bytes(key)
    _EMAIL_KEY_FILE.chmod(0o600)
    return key


@lru_cache(maxsize=1)
def _get_fernet() -> "Fernet":
    """Return a cached Fernet instance keyed to this machine."""
    uuid = _machine_uuid()
    if uuid:
        key = _derive_key_from_uuid(uuid)
    else:
        key = _load_or_create_file_key()
    return Fernet(key)


def encrypt_password(plaintext: str) -> str:
    """Encrypt a plaintext password and return a base64 Fernet token string."""
    try:
        token: bytes = _get_fernet().encrypt(plaintext.encode("utf-8"))
        return token.decode("ascii")
    except Exception as exc:
        raise EmailCryptoError(f"Failed to encrypt password: {exc}") from exc


def decrypt_password(ciphertext: str) -> str:
    """Decrypt a Fernet token string and return the plaintext password."""
    try:
        plaintext: bytes = _get_fernet().decrypt(ciphertext.encode("ascii"))
        return plaintext.decode("utf-8")
    except InvalidToken as exc:
        raise EmailCryptoError(
            "Failed to decrypt stored password — the encryption key may have changed. "
            "You may need to re-add the account."
        ) from exc
    except Exception as exc:
        raise EmailCryptoError(f"Decryption error: {exc}") from exc
