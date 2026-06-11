"""Restore a private-data backup (scripts/backup_private_data.py).

Safety contract (test-pinned):
  * checksum is verified against the manifest BEFORE anything is touched;
  * DRY-RUN is the default — nothing is written without ``--apply``;
  * an existing DB is never overwritten without ``--force`` (the current
    DB is first copied aside as ``<name>.pre_restore.<stamp>``);
  * ``.env``/secrets are never restored (backups never contain them);
  * refused outright while ``MVP_LOCKDOWN_MODE=1`` — lift lockdown
    deliberately first (docs/INCIDENT_LOCKDOWN.md);
  * a restore report is written next to the backup and the action is
    recorded in the tamper-evident audit log.

Usage:
    python scripts/restore_private_data.py --manifest backups/<...>.manifest.json
    python scripts/restore_private_data.py --manifest ... --apply [--force]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import tarfile
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

try:
    from scripts.backup_private_data import decrypt_file, sha256_file, encryption_available
except ModuleNotFoundError:  # pragma: no cover
    from backup_private_data import (  # type: ignore[no-redef]
        decrypt_file, sha256_file, encryption_available,
    )


try:
    from scripts import operator_permission_guard as _guard
except ModuleNotFoundError:  # pragma: no cover - script-style env
    import operator_permission_guard as _guard  # type: ignore[no-redef]

# Kanté write boundary: CLI --apply routes through the central
# operator_permission_guard (RESTORE_WRITE needs an authorized role and a
# recent dry-run receipt; allow/deny are both audited). Dry-run writes the
# receipt that a later --apply must present.
OPERATION_NAME = "restore_private_data"
OPERATION_CLASS = _guard.OperationClass.RESTORE_WRITE


class RestoreRefused(RuntimeError):
    """Raised when a safety precondition fails."""


def load_manifest(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for field in ("archive", "archive_sha256", "encrypted"):
        if field not in manifest:
            raise RestoreRefused(f"manifest missing field {field!r}")
    return manifest


def verify_archive(manifest_path: Path) -> Path:
    """Checksum the archive against its manifest; returns the archive path."""
    manifest = load_manifest(manifest_path)
    archive = manifest_path.parent / manifest["archive"]
    if not archive.exists():
        raise RestoreRefused(f"archive missing: {archive}")
    actual = sha256_file(archive)
    if actual != manifest["archive_sha256"]:
        raise RestoreRefused(
            "checksum mismatch — the backup is corrupted or tampered "
            f"(expected {manifest['archive_sha256'][:12]}…, got {actual[:12]}…). "
            "REFUSING to restore from it."
        )
    return archive


def restore(
    manifest_path: Path,
    *,
    apply: bool = False,
    force: bool = False,
    passphrase: str | None = None,
    db_path: Path | None = None,
) -> dict:
    if os.environ.get("MVP_LOCKDOWN_MODE", "").strip().lower() in ("1", "true", "yes"):
        raise RestoreRefused(
            "MVP_LOCKDOWN_MODE=1 — restore is a mutation and lockdown "
            "blocks mutations. Lift lockdown deliberately first "
            "(docs/INCIDENT_LOCKDOWN.md)."
        )
    manifest = load_manifest(manifest_path)
    archive = verify_archive(manifest_path)

    if db_path is None:
        try:
            from scripts.runtime_config import get_db_path
        except ModuleNotFoundError:  # pragma: no cover
            from runtime_config import get_db_path  # type: ignore[no-redef]
        db_path = get_db_path()

    report: dict = {
        "manifest": str(manifest_path),
        "archive": str(archive),
        "checksum": "verified",
        "mode": "apply" if apply else "dry_run",
        "restored": [],
        "skipped": [],
        "warnings": [],
    }

    with tempfile.TemporaryDirectory(prefix="spv1-restore-") as tmp:
        tar_path = Path(tmp) / "backup.tar.gz"
        if manifest["encrypted"]:
            if not encryption_available():
                raise RestoreRefused(
                    "encrypted backup but optional 'cryptography' package "
                    "is not installed (pip install cryptography)"
                )
            if not passphrase:
                raise RestoreRefused("encrypted backup requires --passphrase-prompt")
            try:
                decrypt_file(archive, tar_path, passphrase)
            except Exception:
                raise RestoreRefused(
                    "decryption failed — wrong passphrase or tampered archive"
                ) from None
        else:
            tar_path.write_bytes(archive.read_bytes())

        with tarfile.open(tar_path, "r:gz") as tar:
            members = tar.getnames()
            report["archive_members"] = members
            db_members = [m for m in members if m.endswith((".db", ".sqlite"))]
            for member in members:
                if ".env" in member:
                    report["skipped"].append(f"{member} (secrets are never restored)")
            if not db_members:
                report["warnings"].append("no database file inside archive")
            for member in db_members:
                if db_path.exists() and not force:
                    if apply:
                        raise RestoreRefused(
                            f"target DB exists ({db_path}); pass --force to "
                            "overwrite (a pre-restore copy is kept)"
                        )
                    report["warnings"].append(
                        f"target DB exists ({db_path.name}); --apply will "
                        "require --force"
                    )
                if not apply:
                    report["restored"].append(f"{member} (dry-run; not written)")
                    continue
                if db_path.exists():
                    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                    keep = db_path.with_name(f"{db_path.name}.pre_restore.{stamp}")
                    keep.write_bytes(db_path.read_bytes())
                    report["warnings"].append(f"previous DB kept at {keep.name}")
                extracted = tar.extractfile(member)
                assert extracted is not None
                db_path.parent.mkdir(parents=True, exist_ok=True)
                db_path.write_bytes(extracted.read())
                report["restored"].append(f"{member} -> {db_path}")

    if not apply:
        # Receipt proves a dry-run happened; build_apply_decision requires it.
        try:
            _guard.write_dry_run_receipt(
                OPERATION_NAME,
                target_count=len(report["restored"]),
                db_path=str(db_path),
            )
        except Exception:  # pragma: no cover - receipt is best-effort
            pass

    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = manifest_path.parent / f"restore_report_{stamp}.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = str(report_path)

    try:
        from scripts.audit_log import append_event
    except ModuleNotFoundError:  # pragma: no cover
        from audit_log import append_event  # type: ignore[no-redef]
    append_event(
        "restore", actor="owner", action="restore_private_data",
        outcome=report["mode"],
        metadata={"archive": archive.name, "restored": len(report["restored"])},
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--apply", action="store_true",
                        help="actually write files (default is DRY RUN)")
    parser.add_argument("--force", action="store_true",
                        help="allow overwriting an existing DB (pre-restore copy kept)")
    parser.add_argument("--passphrase-prompt", action="store_true",
                        help="prompt for the passphrase of an encrypted backup")
    parser.add_argument("--operator-role", default=None,
                        help="role for the permission guard (else MVP_OPERATOR_ROLE env)")
    args = parser.parse_args(argv)

    if args.apply:
        # Central permission guard: fails closed, audits allow AND deny.
        try:
            _guard.build_apply_decision(
                OPERATION_NAME, OPERATION_CLASS, None,
                operator_role=args.operator_role,
            )
        except PermissionError as exc:
            print(f"[DENY] {exc}", file=sys.stderr)
            print("[hint] run the dry-run first (writes the receipt), then "
                  "re-run --apply as an authorized role "
                  "(MVP_OPERATOR_ROLE=ADMIN or --operator-role ADMIN).",
                  file=sys.stderr)
            return 2

    passphrase = None
    if args.passphrase_prompt:
        import getpass

        passphrase = getpass.getpass("Backup passphrase: ")
    try:
        report = restore(
            Path(args.manifest), apply=args.apply, force=args.force,
            passphrase=passphrase,
        )
    except RestoreRefused as exc:
        print(f"[refused] {exc}", file=sys.stderr)
        return 1
    print(f"[{report['mode']}] checksum verified; report: {report['report_path']}")
    for line in report["restored"]:
        print(f"  restored: {line}")
    for line in report["warnings"]:
        print(f"  warning : {line}")
    if not args.apply:
        print("[note] DRY RUN — nothing was written. Re-run with --apply "
              "(and --force if the DB exists).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
