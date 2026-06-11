"""Full-history secret scan vs. the verified historical ledger.

The repo's git history contains 24 known gitleaks findings — all verified
synthetic test fixtures, documented fingerprint-by-fingerprint in
``docs/security/historical_findings_ledger.json`` (story and purge policy:
``docs/security/historical-secret-scan-ledger.md``).

This script re-runs the full-history scan and classifies every finding:

  * finding in the **current tree** (``--no-git`` scan of HEAD content)
    → ALWAYS fatal (exit 2). The ledger can never suppress live leaks.
  * historical finding whose fingerprint is **in the ledger**
    → known synthetic bait; reported, does not fail.
  * historical finding **not in the ledger**
    → fatal (exit 1). Either a new verified-synthetic entry is needed
      (add it ONLY after line-by-line verification) or it is a real
      secret — in which case rotate the credential immediately; rotation,
      not history rewriting, is the security fix.

Not wired into per-push CI by default (history never changes on a normal
push, and a fetch-depth quirk must not block merges); run locally or via
the manual ``history-audit`` workflow (workflow_dispatch). A
machine-readable report is written to
``runtime/reports/historical_secret_scan.json`` (gitignored).

Exit codes: 0 clean · 1 unknown historical finding · 2 current-tree
finding · 3 gitleaks unavailable · 4 shallow clone (history incomplete).

Stdlib only:  python scripts/audit_historical_secret_ledger.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = _REPO_ROOT / "docs" / "security" / "historical_findings_ledger.json"
REPORT_PATH = _REPO_ROOT / "runtime" / "reports" / "historical_secret_scan.json"

EXIT_CLEAN = 0
EXIT_UNKNOWN_HISTORICAL = 1
EXIT_CURRENT_TREE = 2
EXIT_NO_GITLEAKS = 3
EXIT_SHALLOW = 4


def find_gitleaks() -> str | None:
    """Locate the gitleaks binary (env override, PATH, ~/.local/bin)."""
    override = os.environ.get("GITLEAKS_BIN", "").strip()
    if override and Path(override).exists():
        return override
    on_path = shutil.which("gitleaks")
    if on_path:
        return on_path
    local = Path.home() / ".local" / "bin" / "gitleaks"
    return str(local) if local.exists() else None


def load_ledger(path: Path = LEDGER_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def classify_findings(
    history_findings: list[dict[str, Any]],
    tree_findings: list[dict[str, Any]],
    ledger: dict[str, Any],
) -> dict[str, Any]:
    """Pure classification (unit-testable without gitleaks installed)."""
    known = {entry["fingerprint"] for entry in ledger.get("known_findings", [])}
    known_hits, unknown = [], []
    for f in history_findings:
        fp = f.get("Fingerprint", "")
        (known_hits if fp in known else unknown).append(fp)
    return {
        "current_tree_findings": [
            # File:line only — never echo matched content into the report.
            f"{f.get('File')}:{f.get('StartLine')}:{f.get('RuleID')}"
            for f in tree_findings
        ],
        "historical_known_synthetic": sorted(known_hits),
        "historical_unknown": sorted(unknown),
        "ledger_entries": len(known),
        "ledger_entries_not_seen": sorted(
            known - {f.get("Fingerprint", "") for f in history_findings}
        ),
    }


def _run_scan(gitleaks: str, *args: str) -> list[dict[str, Any]]:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        report = tmp.name
    try:
        subprocess.run(
            [gitleaks, "detect", "--config=.gitleaks.toml", "--redact",
             "--exit-code=2", "--report-format=json",
             f"--report-path={report}", *args],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,  # exit 2 just means findings; we classify them
        )
        raw = Path(report).read_text(encoding="utf-8").strip()
        return json.loads(raw) if raw else []
    finally:
        Path(report).unlink(missing_ok=True)


def main() -> int:
    gitleaks = find_gitleaks()
    if gitleaks is None:
        print(
            "SKIP — gitleaks binary not found. Install the pinned CLI the "
            "same way CI does (see the 'Install gitleaks' step in "
            ".github/workflows/dep_audit.yml) or set GITLEAKS_BIN."
        )
        return EXIT_NO_GITLEAKS

    shallow = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=False,
    ).stdout.strip()
    if shallow == "true":
        print(
            "FAIL — shallow clone: history scan would be incomplete and "
            "could hide findings. Run `git fetch --unshallow` first."
        )
        return EXIT_SHALLOW

    ledger = load_ledger()
    history = _run_scan(gitleaks)            # all commits
    tree = _run_scan(gitleaks, "--no-git", "--source=.")
    result = classify_findings(history, tree, ledger)

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=False,
    ).stdout.strip()
    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "head_commit": head,
        "gitleaks_binary": gitleaks,
        **result,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"historical secret-scan audit (report: {REPORT_PATH})")
    print(f"  known synthetic historical findings: "
          f"{len(result['historical_known_synthetic'])}")
    if result["current_tree_findings"]:
        print("FAIL — findings in the CURRENT tree (never suppressible):")
        for f in result["current_tree_findings"]:
            print(f"  - {f}")
        return EXIT_CURRENT_TREE
    if result["historical_unknown"]:
        print("FAIL — historical findings NOT in the verified ledger:")
        for fp in result["historical_unknown"]:
            print(f"  - {fp}")
        print(
            "Verify each line at its commit. If synthetic, add a ledger "
            "entry with a note; if it could be real, ROTATE the credential "
            "now (see docs/security/historical-secret-scan-ledger.md)."
        )
        return EXIT_UNKNOWN_HISTORICAL
    print("PASS — history matches the verified ledger; current tree clean.")
    return EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
