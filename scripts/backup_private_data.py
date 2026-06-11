"""Encrypted (optional) backup of the MVP's private local data.

Backs up the SQLite journal DB, a REDACTED config summary, and optionally
reports/exports into ``backups/`` with a manifest + SHA-256 checksum.
``.env`` raw secrets are NEVER included.

Encryption: ``--encrypt`` derives a key from an operator passphrase with
``hashlib.scrypt`` (stdlib KDF: n=2^15, r=8, p=1) and seals the archive
with AES-256-GCM via the ``cryptography`` package. That package is an
OPTIONAL extra (``pip install cryptography``) — hand-rolling AES in
stdlib would be malpractice, so without it the script refuses
``--encrypt`` and produces a compressed+checksummed archive instead,
saying so plainly. The checksum still proves integrity; it does not
provide confidentiality — full-disk encryption (BitLocker) remains the
at-rest baseline either way.

Usage:
    python scripts/backup_private_data.py                 # tar.gz + manifest
    python scripts/backup_private_data.py --encrypt       # passphrase prompt
    python scripts/backup_private_data.py --include-reports

Advisory-only: backs up journal data; nothing here can execute trades.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import getpass
import hashlib
import json
import os
import sys
import tarfile
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BACKUP_DIR = _REPO_ROOT / "backups"
_MAGIC = b"SPV1-AESGCM-v1"  # header of encrypted archives
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**15, 8, 1

# Config keys worth carrying in the redacted summary (never values of
# secret kinds — only whether they were set).
_SUMMARY_KEYS = (
    "API_HOST", "API_PORT", "MVP_ENVIRONMENT", "MVP_DB_PATH",
    "SECRET_PROVIDER", "MVP_LOCKDOWN_MODE",
)


def encryption_available() -> bool:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        return True
    except ImportError:
        return False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def derive_key(passphrase: str, salt: bytes) -> bytes:
    # maxmem: 128*r*n = 32 MiB exceeds OpenSSL's default cap; allow 64 MiB.
    return hashlib.scrypt(
        passphrase.encode("utf-8"), salt=salt,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32, maxmem=2**26,
    )


def encrypt_file(plain_path: Path, out_path: Path, passphrase: str) -> None:
    """Seal with AES-256-GCM: MAGIC || salt(16) || nonce(12) || ciphertext."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = derive_key(passphrase, salt)
    sealed = AESGCM(key).encrypt(nonce, plain_path.read_bytes(), _MAGIC)
    out_path.write_bytes(_MAGIC + salt + nonce + sealed)


def decrypt_file(enc_path: Path, out_path: Path, passphrase: str) -> None:
    """Inverse of encrypt_file; raises on wrong passphrase or tampering."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    blob = enc_path.read_bytes()
    if not blob.startswith(_MAGIC):
        raise ValueError("not a SPV1-AESGCM-v1 encrypted archive")
    offset = len(_MAGIC)
    salt = blob[offset:offset + 16]
    nonce = blob[offset + 16:offset + 28]
    key = derive_key(passphrase, salt)
    out_path.write_bytes(AESGCM(key).decrypt(nonce, blob[offset + 28:], _MAGIC))


def redacted_config_summary() -> dict:
    """Which knobs/keys are set — never their values."""
    try:
        from scripts.secret_provider import known_secret_names
    except ModuleNotFoundError:  # pragma: no cover
        from secret_provider import known_secret_names  # type: ignore[no-redef]
    summary = {
        key: (os.environ.get(key, "").strip() or "<unset>")
        for key in _SUMMARY_KEYS
    }
    summary["secret_keys_set"] = sorted(
        name for name in known_secret_names() if os.environ.get(name, "").strip()
    )
    summary["note"] = "values of secret-kind keys are never included"
    return summary


def collect_sources(include_reports: bool, db_path: Path) -> list[Path]:
    sources: list[Path] = []
    if db_path.exists():
        sources.append(db_path)
    if include_reports:
        for rel in ("reports", "scorecards"):
            d = _REPO_ROOT / rel
            if d.exists():
                sources.append(d)
    return sources


def create_backup(
    *,
    encrypt: bool = False,
    passphrase: str | None = None,
    include_reports: bool = False,
    db_path: Path | None = None,
    backup_dir: Path | None = None,
) -> dict:
    """Build the archive + manifest; returns the manifest dict."""
    backup_dir = backup_dir or _BACKUP_DIR
    backup_dir.mkdir(parents=True, exist_ok=True)
    if db_path is None:
        try:
            from scripts.runtime_config import get_db_path
        except ModuleNotFoundError:  # pragma: no cover
            from runtime_config import get_db_path  # type: ignore[no-redef]
        db_path = get_db_path()

    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sources = collect_sources(include_reports, db_path)
    if not sources:
        raise FileNotFoundError(
            f"nothing to back up: DB not found at {db_path} and no reports requested"
        )

    if encrypt and not encryption_available():
        raise RuntimeError(
            "--encrypt requested but the optional 'cryptography' package is "
            "not installed. Install it (pip install cryptography) or run "
            "without --encrypt for a compressed+checksummed (NOT "
            "confidential) archive."
        )

    with tempfile.TemporaryDirectory(prefix="spv1-backup-") as tmp:
        tar_path = Path(tmp) / f"private_backup_{stamp}.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tar:
            for src in sources:
                tar.add(src, arcname=src.name, recursive=True)
            summary = json.dumps(redacted_config_summary(), indent=2)
            summary_file = Path(tmp) / "config_summary.redacted.json"
            summary_file.write_text(summary, encoding="utf-8")
            tar.add(summary_file, arcname="config_summary.redacted.json")

        if encrypt:
            archive_path = backup_dir / f"private_backup_{stamp}.tar.gz.enc"
            encrypt_file(tar_path, archive_path, passphrase or "")
        else:
            archive_path = backup_dir / tar_path.name
            archive_path.write_bytes(tar_path.read_bytes())

    manifest = {
        "created_utc": stamp,
        "archive": archive_path.name,
        "archive_sha256": sha256_file(archive_path),
        "encrypted": bool(encrypt),
        "encryption": "scrypt(n=2^15,r=8,p=1) + AES-256-GCM" if encrypt else "none",
        "confidentiality_note": (
            "archive is sealed; passphrase required to restore"
            if encrypt
            else "NOT encrypted — checksum proves integrity only; rely on "
            "BitLocker/device encryption for at-rest confidentiality"
        ),
        "sources": [str(s.relative_to(_REPO_ROOT)) if s.is_relative_to(_REPO_ROOT) else str(s) for s in sources],
        "env_secrets_included": False,
        "advisory_status": "ADVISORY_ONLY",
        "broker_api_called": False,
    }
    manifest_path = backup_dir / f"private_backup_{stamp}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    manifest["archive_path"] = str(archive_path)

    try:
        from scripts.audit_log import append_event
    except ModuleNotFoundError:  # pragma: no cover
        from audit_log import append_event  # type: ignore[no-redef]
    append_event(
        "backup", actor="owner", action="backup_private_data",
        outcome="ok", metadata={"archive": archive_path.name,
                                "encrypted": bool(encrypt)},
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--encrypt", action="store_true",
                        help="AES-256-GCM with a scrypt-derived passphrase key")
    parser.add_argument("--include-reports", action="store_true")
    args = parser.parse_args(argv)

    passphrase = None
    if args.encrypt:
        if not encryption_available():
            print("[error] optional 'cryptography' package not installed; "
                  "see docs/BACKUP_RESTORE.md", file=sys.stderr)
            return 2
        passphrase = getpass.getpass("Backup passphrase (not stored anywhere): ")
        if len(passphrase) < 10:
            print("[error] passphrase must be at least 10 characters", file=sys.stderr)
            return 2
        if getpass.getpass("Repeat passphrase: ") != passphrase:
            print("[error] passphrases do not match", file=sys.stderr)
            return 2

    manifest = create_backup(
        encrypt=args.encrypt, passphrase=passphrase,
        include_reports=args.include_reports,
    )
    print(f"[ok] backup: {manifest['archive_path']}")
    print(f"[ok] manifest: {manifest['manifest_path']}")
    print(f"[ok] sha256: {manifest['archive_sha256']}")
    if not args.encrypt:
        print("[note] archive is NOT encrypted (integrity only). For "
              "confidential off-machine copies use --encrypt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
