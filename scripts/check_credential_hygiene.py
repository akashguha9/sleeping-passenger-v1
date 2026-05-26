"""Credential hygiene check — no service-account JSON at repo root.

Calibration Corpus + Hosted Canary sprint, Phase 5.

Doctrine
--------
* The Google service-account JSON (and other credential files) MUST
  NOT sit at the repository root.  Move them to ``secrets/`` and point
  ``GOOGLE_APPLICATION_CREDENTIALS`` at that path.
* This script NEVER reads, prints, copies, or echoes the contents of
  any credential file.  It only inspects path existence and .gitignore
  coverage.
* Output is a structured JSON report carrying advisory-only safety
  stamps.

Exit codes
~~~~~~~~~~
* 0 — PASS
* 1 — FAIL (root credential present, OR ``secrets/`` not gitignored)
* 2 — usage error / I/O error
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Stable list of credential-shaped filenames that must never sit at the
# repository root.  Glob-pattern style; the check uses literal name
# match plus prefix/suffix matching.
_FORBIDDEN_AT_ROOT: tuple[str, ...] = (
    "google-service-account.json",
    "service-account.json",
)
_FORBIDDEN_PATTERNS: tuple[str, ...] = (
    "service-account",   # any *service-account*.json
    "credentials",       # any *credentials*.json
)

SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _root_credential_offenders(root: Path) -> list[str]:
    """List credential-shaped filenames present directly under ``root``.

    Returns filenames (not paths).  Performs ``os.scandir`` + filename
    matching only — never opens the file.
    """
    offenders: list[str] = []
    try:
        entries = list(os.scandir(root))
    except OSError:
        return offenders
    for entry in entries:
        if not entry.is_file(follow_symlinks=False):
            continue
        name = entry.name
        if not name.lower().endswith(".json"):
            continue
        lower = name.lower()
        if name in _FORBIDDEN_AT_ROOT:
            offenders.append(name)
            continue
        for pattern in _FORBIDDEN_PATTERNS:
            if pattern in lower:
                offenders.append(name)
                break
    return offenders


def _gitignore_covers_secrets(root: Path) -> bool:
    """Check that ``secrets/`` is gitignored.  Reads .gitignore by
    LINES — never opens or prints any credential file.
    """
    gi = root / ".gitignore"
    if not gi.exists():
        return False
    try:
        text = gi.read_text(encoding="utf-8")
    except OSError:
        return False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.rstrip("/") == "secrets":
            return True
    return False


def _secrets_credential_path(root: Path) -> Path:
    return root / "secrets" / "google-service-account.json"


def build_report(root: Path | None = None) -> dict[str, Any]:
    """Build the structured hygiene report.  Pure file-shape inspection
    — no credential contents are ever read.
    """
    base = Path(root) if root is not None else _REPO_ROOT
    offenders = _root_credential_offenders(base)
    secrets_path = _secrets_credential_path(base)
    secrets_present = secrets_path.exists() if secrets_path.parent.exists() else False
    secrets_gitignored = _gitignore_covers_secrets(base)

    root_present = bool(offenders)
    hygiene_pass = (not root_present) and secrets_gitignored
    status = "PASS" if hygiene_pass else "FAIL"

    recommendation_parts: list[str] = []
    if root_present:
        recommendation_parts.append(
            f"Move {', '.join(offenders)} from repo root to secrets/ "
            "(path-level move only — do not read the file)."
        )
    if not secrets_gitignored:
        recommendation_parts.append(
            "Add ``secrets/`` to .gitignore so credentials never get committed."
        )
    if secrets_present:
        recommendation_parts.append(
            "Set GOOGLE_APPLICATION_CREDENTIALS=secrets/google-service-account.json "
            "for any Google client library."
        )
    if not recommendation_parts:
        recommendation_parts.append(
            "Credential hygiene is clean.  Keep GOOGLE_APPLICATION_CREDENTIALS "
            "pointed at secrets/google-service-account.json."
        )

    report = {
        "script": "check_credential_hygiene.py",
        "generated_at_utc": _utc_now_iso(),
        "root_service_account_present": bool(root_present),
        "root_offenders": offenders,
        "secrets_service_account_present": bool(secrets_present),
        "secrets_gitignored": bool(secrets_gitignored),
        "status": status,
        "credential_hygiene_pass": int(hygiene_pass),
        "credential_risk_score": round(10.0 * (1 - int(hygiene_pass)), 4),
        "recommendation": " ".join(recommendation_parts),
        # Note: never include credential contents, paths to actual env
        # values, or any token-shaped string.
    }
    report.update(SAFETY_STAMPS)
    return report


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Refuse root-level service-account JSON files.  Never reads "
            "the file contents; only inspects path existence and "
            ".gitignore coverage.  Advisory-only."
        )
    )
    parser.add_argument("--json", type=str, default=None,
                        help="Optional path to write the structured JSON report.")
    parser.add_argument("--root", type=Path, default=_REPO_ROOT,
                        help="Repository root (defaults to the repo this script lives in).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_report(root=args.root)

    if args.json:
        out = Path(args.json)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:  # pragma: no cover — disk full / read-only
            sys.stderr.write(f"could not write report: {type(exc).__name__}\n")
            return 2

    sys.stdout.write(
        f"credential hygiene: status={report['status']} "
        f"root_offenders={report['root_offenders']} "
        f"secrets_gitignored={report['secrets_gitignored']}\n"
    )
    sys.stdout.write(report["recommendation"] + "\n")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
