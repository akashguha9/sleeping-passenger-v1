"""S4-A4: authenticated encryption for local DB backups.

Residual being closed: backups were owner-permission-restricted but
plaintext at rest.

Primitive: AES-256-GCM via the ``cryptography`` package — ALREADY pinned
in requirements.lock (48.0.0, previously a transitive dependency; now a
documented direct one).  No new dependency was introduced.

File format (versioned):
    MAGIC(b"MVPENCBK1") || nonce(12 bytes) || AESGCM ciphertext+tag
AAD = MAGIC, so a tampered header fails authentication.

Key handling:
* ``MVP_BACKUP_KEY`` env var (urlsafe-base64, 32 bytes decoded), else an
  owner-only key file ``runtime/diagnostics_cache/backup_key.key``;
* the key file is auto-generated for ENCRYPTION when absent;
* DECRYPTION fails closed when no key source exists — a restore can
  never silently proceed without the key;
* the key is never logged, never embedded in metadata or filenames.

Advisory invariants: file transformation only — no broker, no execution.
"""
from __future__ import annotations

import base64
import logging
import os
import secrets
from pathlib import Path

try:
    from scripts.runtime_common import RUNTIME_DIR, restrict_file_permissions
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from runtime_common import RUNTIME_DIR, restrict_file_permissions  # type: ignore[no-redef]

_logger = logging.getLogger("scripts.backup_crypto")

MAGIC = b"MVPENCBK1"
_NONCE_BYTES = 12
_KEY_BYTES = 32

ENCRYPTED_SUFFIX = ".enc"


class BackupCryptoError(RuntimeError):
    """Encryption/decryption refused or failed (fail closed)."""


def _key_file() -> Path:
    return RUNTIME_DIR / "diagnostics_cache" / "backup_key.key"


def _load_key(*, create_if_missing: bool) -> bytes:
    env = os.environ.get("MVP_BACKUP_KEY", "").strip()
    if env:
        try:
            key = base64.urlsafe_b64decode(env)
        except Exception as exc:
            raise BackupCryptoError("MVP_BACKUP_KEY is not valid base64") from exc
        if len(key) != _KEY_BYTES:
            raise BackupCryptoError(
                f"MVP_BACKUP_KEY must decode to {_KEY_BYTES} bytes"
            )
        return key
    path = _key_file()
    if path.exists():
        key = path.read_bytes()
        if len(key) != _KEY_BYTES:
            raise BackupCryptoError("backup key file is corrupt (wrong length)")
        return key
    if not create_if_missing:
        raise BackupCryptoError(
            "no backup key available (set MVP_BACKUP_KEY or provide "
            f"{path}) — refusing to proceed without the key"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(_KEY_BYTES)
    path.write_bytes(key)
    restrict_file_permissions(path)
    _logger.info("generated backup encryption key file (owner-only)")
    return key


def encrypt_file(plain_path: Path, encrypted_path: Path) -> Path:
    """Encrypt ``plain_path`` → ``encrypted_path`` (AES-256-GCM)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: PLC0415

    key = _load_key(create_if_missing=True)
    nonce = secrets.token_bytes(_NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plain_path.read_bytes(), MAGIC)
    encrypted_path.parent.mkdir(parents=True, exist_ok=True)
    encrypted_path.write_bytes(MAGIC + nonce + ciphertext)
    restrict_file_permissions(encrypted_path)
    return encrypted_path


def decrypt_file(encrypted_path: Path, plain_path: Path) -> Path:
    """Decrypt with authentication.  Wrong key / tamper → BackupCryptoError."""
    from cryptography.exceptions import InvalidTag  # noqa: PLC0415
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: PLC0415

    blob = encrypted_path.read_bytes()
    if not blob.startswith(MAGIC):
        raise BackupCryptoError("not an MVP encrypted backup (bad magic)")
    key = _load_key(create_if_missing=False)
    nonce = blob[len(MAGIC): len(MAGIC) + _NONCE_BYTES]
    ciphertext = blob[len(MAGIC) + _NONCE_BYTES:]
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, MAGIC)
    except InvalidTag as exc:
        raise BackupCryptoError(
            "decryption FAILED (wrong key or tampered backup) — refusing"
        ) from exc
    plain_path.parent.mkdir(parents=True, exist_ok=True)
    plain_path.write_bytes(plaintext)
    restrict_file_permissions(plain_path)
    return plain_path


def is_encrypted_backup(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(len(MAGIC)) == MAGIC
    except OSError:
        return False
