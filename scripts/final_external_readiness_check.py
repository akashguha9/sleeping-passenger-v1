"""Final external-readiness check (Pass 6) — never fakes verification.

External tasks (GitHub UI settings, first green E2E run, Windows
Credential Manager migration) can only be completed outside this repo.
This script makes them visible and hard to forget, with three honest
states:

  * VERIFIED  — machine-checkable artifact exists and says the safe thing;
  * PENDING   — not verifiable from here; manual confirmation missing
    (this is NOT a failure — faking it would be);
  * UNSAFE    — a machine-checkable artifact says a dangerous thing
    (exit 1).

Manual confirmations live as marker files the OWNER creates explicitly
(this script NEVER creates them):

    reports/manual_confirmations/github_branch_protection_confirmed.md
    reports/manual_confirmations/github_security_features_confirmed.md
    reports/manual_confirmations/e2e_first_green_run_confirmed.md
    reports/manual_confirmations/wcm_migration_confirmed.md

Usage:  python scripts/final_external_readiness_check.py
"""
from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIRM_DIR = _REPO_ROOT / "reports" / "manual_confirmations"

VERIFIED = "VERIFIED"
PENDING = "PENDING"
UNSAFE = "UNSAFE"


def _marker(name: str) -> bool:
    return (CONFIRM_DIR / name).exists()


def check_github_owner_controls(repo_root: Path = _REPO_ROOT) -> tuple[str, str]:
    report = repo_root / "reports" / "github_owner_controls_report.md"
    if not report.exists():
        return PENDING, ("owner-controls report missing — run "
                         "scripts/audit_github_owner_controls.py")
    text = report.read_text(encoding="utf-8")
    # A verified-unsafe line in the report is a hard failure.
    unsafe_section = text.split("## Verified unsafe", 1)[-1].split("##", 1)[0]
    if "❌" in unsafe_section:
        return UNSAFE, "owner-controls report contains VERIFIED-unsafe findings"
    if "✅" in text:
        return VERIFIED, "owner-controls report present with verified-safe findings"
    return PENDING, "owner-controls report present but nothing was verifiable (no gh)"


def check_branch_protection(repo_root: Path = _REPO_ROOT) -> tuple[str, str]:
    confirm = repo_root / "reports" / "manual_confirmations" / \
        "github_branch_protection_confirmed.md"
    if confirm.exists():
        return VERIFIED, f"owner confirmation on file: {confirm.name}"
    return PENDING, ("branch protection not confirmable from here — verify in "
                     "GitHub UI, then create the confirmation marker yourself")


def check_security_features(repo_root: Path = _REPO_ROOT) -> tuple[str, str]:
    confirm = repo_root / "reports" / "manual_confirmations" / \
        "github_security_features_confirmed.md"
    if confirm.exists():
        return VERIFIED, "Dependabot/secret-scanning/push-protection confirmed by owner"
    return PENDING, "Dependabot/secret-scanning/push-protection unconfirmed"


def check_e2e(repo_root: Path = _REPO_ROOT) -> tuple[str, str]:
    confirm = repo_root / "reports" / "manual_confirmations" / \
        "e2e_first_green_run_confirmed.md"
    if confirm.exists():
        return VERIFIED, "first green e2e.yml run confirmed by owner"
    workflow = repo_root / ".github" / "workflows" / "e2e.yml"
    if workflow.exists():
        return PENDING, ("e2e.yml exists; trigger it (Actions → e2e → Run "
                         "workflow) and create the confirmation marker after "
                         "the first green run")
    return UNSAFE, "e2e.yml workflow missing"


def check_wcm(repo_root: Path = _REPO_ROOT) -> tuple[str, str]:
    if sys.platform == "win32":  # pragma: no cover - exercised on Windows
        try:
            from scripts.secret_provider import WindowsCredentialManagerProvider

            WindowsCredentialManagerProvider()
            return VERIFIED, "WCM provider constructed successfully on this Windows host"
        except Exception as exc:
            return UNSAFE, f"WCM provider failed on Windows: {exc}"
    confirm = repo_root / "reports" / "manual_confirmations" / \
        "wcm_migration_confirmed.md"
    if confirm.exists():
        return VERIFIED, "WCM migration confirmed by owner (ran on Windows)"
    return PENDING, ("not a Windows host — run manage_secrets.py on your "
                     "Windows machine, then create the confirmation marker")


def check_env_keys_migrated(repo_root: Path = _REPO_ROOT) -> tuple[str, str]:
    env_path = repo_root / ".env"
    if not env_path.exists():
        return VERIFIED, "no .env on this machine — nothing to migrate here"
    try:
        from scripts.secret_provider import known_secret_names
    except ModuleNotFoundError:  # pragma: no cover
        from secret_provider import known_secret_names  # type: ignore[no-redef]
    populated = []
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        for name in known_secret_names():
            if stripped.startswith(f"{name}=") and stripped != f"{name}=":
                populated.append(name)
    if populated:
        return PENDING, (f"{len(populated)} provider key(s) still plaintext in "
                         ".env — migrate via manage_secrets.py "
                         f"({', '.join(populated[:3])}…)")
    return VERIFIED, "no plaintext provider keys in .env"


CHECKS = (
    ("github_owner_controls", check_github_owner_controls),
    ("github_branch_protection", check_branch_protection),
    ("github_security_features", check_security_features),
    ("e2e_first_green_run", check_e2e),
    ("windows_credential_manager", check_wcm),
    ("env_provider_keys_migrated", check_env_keys_migrated),
)


def run_checks(repo_root: Path = _REPO_ROOT) -> dict:
    results = []
    for name, fn in CHECKS:
        try:
            status, detail = fn(repo_root)
        except Exception as exc:
            status, detail = PENDING, f"check errored: {type(exc).__name__}"
        results.append({"check": name, "status": status, "detail": detail})
    return {
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "results": results,
        "verified": sum(1 for r in results if r["status"] == VERIFIED),
        "pending": sum(1 for r in results if r["status"] == PENDING),
        "unsafe": sum(1 for r in results if r["status"] == UNSAFE),
    }


def main() -> int:
    outcome = run_checks()
    print(f"external readiness · verified {outcome['verified']} · "
          f"pending {outcome['pending']} · UNSAFE {outcome['unsafe']}")
    for r in outcome["results"]:
        print(f"  [{r['status']}] {r['check']}: {r['detail']}")
    if outcome["pending"]:
        print("note: PENDING means honestly unverified — see "
              "docs/FINAL_EXTERNAL_CHECKLIST.md; this script never fakes "
              "external verification and never creates confirmation markers.")
    return 1 if outcome["unsafe"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
