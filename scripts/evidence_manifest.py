"""Build the investor / proof-loop evidence manifest.

proof_loop_hardening_sprint, Phase 4.

Purpose
-------
Roll up the artifacts that justify (or fail to justify) any readiness
score this MVP claims.  This is the *single* place that ties a score to
real files on disk, with freshness and `N_real` gates.

Hard truths it enforces
~~~~~~~~~~~~~~~~~~~~~~~
* Path existence alone is never full evidence.
* ``SUFFICIENT_FOR_INVESTOR_DEMO`` is **impossible** when ``N_real < 20``.
* ``SUFFICIENT_FOR_PRIVATE_BETA`` further requires hosted uptime
  evidence and the same ``N_real >= 20``.

Safety
~~~~~~
* Read-only.  No DB writes, no network, no broker calls.
* Advisory-only stamps on every output row.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
    "human_review_required": True,
    "canonical_store": "sqlite",
    "jsonl_is_canonical": False,
}


# Per-artifact freshness budgets (days).  See Phase 7 — same formula.
DEFAULT_MAX_AGE_DAYS: dict[str, int] = {
    "calibration_report": 7,
    "calibration_corpus_status": 7,
    "paper_trade_ledger": 7,
    "screenshots": 30,
    "demo_video_or_notes": 30,
    "pytest_report": 7,
    "frontend_test_report": 7,
    "evidence_manifest": 7,
    "hosted_uptime_report": 7,
    "source_canary_report": 3,
    "playwright_report": 14,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().replace(microsecond=0).isoformat()


def file_age_days(path: Path, *, now: datetime | None = None) -> float | None:
    """Return file age in days, or ``None`` if missing."""
    if not path.exists():
        return None
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    now = now or _utc_now()
    age_sec = max(0.0, (now - mtime).total_seconds())
    return age_sec / 86400.0


def freshness_score(age_days: float | None, max_age_days: int) -> float:
    """Sprint freshness formula:

    ::

        freshness =
          0,                                   if missing
          1,                                   if age <= max_age
          max(0, 1 - (age - max_age) / max_age) otherwise
    """
    if age_days is None:
        return 0.0
    if max_age_days <= 0:
        return 0.0
    if age_days <= max_age_days:
        return 1.0
    over = age_days - max_age_days
    return max(0.0, 1.0 - over / float(max_age_days))


def _calibration_status_and_n_real(report_path: Path) -> tuple[str, int]:
    """Read calibration_status + N_real from the gate's report."""
    if not report_path.exists():
        return ("INSUFFICIENT_EVIDENCE", 0)
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ("INSUFFICIENT_EVIDENCE", 0)
    status = str(
        data.get("calibration_status") or "INSUFFICIENT_EVIDENCE"
    ).strip().upper()
    try:
        n_real = int(data.get("n_real") or data.get("N_real") or 0)
    except (TypeError, ValueError):
        n_real = 0
    return (status, n_real)


def _classify_evidence_status(
    *,
    has_calibration: bool,
    has_ledger: bool,
    n_real: int,
    has_demo: bool,
    has_screenshots: bool,
    has_playwright: bool,
    has_pytest: bool,
    has_hosted_uptime: bool,
) -> str:
    """Apply the sprint's evidence status truth table.

    Hard rule: ``SUFFICIENT_FOR_INVESTOR_DEMO`` requires ``n_real >= 20``.
    """
    any_evidence = any(
        [has_calibration, has_ledger, has_demo, has_screenshots,
         has_playwright, has_pytest]
    )
    if not any_evidence:
        return "EMPTY"
    # Investor-demo: requires full local-demo evidence PLUS playwright
    # PLUS at least 20 real outcomes.
    investor_demo = (
        has_pytest
        and has_screenshots
        and has_demo
        and has_playwright
        and has_calibration
        and n_real >= 20
    )
    private_beta = investor_demo and has_hosted_uptime and n_real >= 20
    if private_beta:
        return "SUFFICIENT_FOR_PRIVATE_BETA"
    if investor_demo:
        return "SUFFICIENT_FOR_INVESTOR_DEMO"
    local_demo = has_pytest and has_screenshots and has_calibration
    if local_demo:
        return "SUFFICIENT_FOR_LOCAL_DEMO"
    return "PARTIAL"


def build_manifest(
    *,
    repo_root: Path = _REPO_ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compute the manifest as a pure-Python dict (no writes)."""
    now = now or _utc_now()

    artifacts: dict[str, dict[str, Any]] = {}

    def _stamp(slug: str, rel_path: str, optional: bool = False) -> None:
        path = repo_root / rel_path
        max_age = DEFAULT_MAX_AGE_DAYS.get(slug, 7)
        age = file_age_days(path, now=now)
        artifacts[slug] = {
            "path": rel_path,
            "exists": path.exists(),
            "age_days": (round(age, 4) if age is not None else None),
            "max_age_days": int(max_age),
            "freshness": round(freshness_score(age, max_age), 4),
            "optional": bool(optional),
        }

    _stamp("calibration_report", "runtime/release/calibration_report.json")
    _stamp(
        "calibration_corpus_status",
        "runtime/release/calibration_corpus_status.json",
        optional=True,
    )
    _stamp("paper_trade_ledger", "runtime/release/calibration_corpus.json")
    _stamp("screenshots", "docs/demo/SCREENSHOT_CHECKLIST.md")
    _stamp("demo_video_or_notes", "docs/demo/DEMO_SCRIPT_5_MIN.md")
    _stamp(
        "pytest_report", "runtime/release/release_gate_proof.json", optional=True
    )
    _stamp(
        "frontend_test_report",
        "frontend/coverage/coverage-summary.json",
        optional=True,
    )
    _stamp(
        "playwright_report",
        "frontend/playwright-report/index.html",
        optional=True,
    )
    _stamp(
        "hosted_uptime_report",
        "runtime/release/hosted_uptime_report.json",
        optional=True,
    )
    _stamp(
        "source_canary_report",
        "runtime/release/live_provider_evidence.json",
        optional=True,
    )

    calibration_status, n_real = _calibration_status_and_n_real(
        repo_root / "runtime" / "release" / "calibration_report.json"
    )

    has_calibration = artifacts["calibration_report"]["exists"]
    has_ledger = artifacts["paper_trade_ledger"]["exists"]
    has_demo = artifacts["demo_video_or_notes"]["exists"]
    has_screenshots = artifacts["screenshots"]["exists"]
    has_playwright = artifacts["playwright_report"]["exists"]
    has_pytest = artifacts["pytest_report"]["exists"]
    has_hosted_uptime = artifacts["hosted_uptime_report"]["exists"]

    evidence_status = _classify_evidence_status(
        has_calibration=has_calibration,
        has_ledger=has_ledger,
        n_real=n_real,
        has_demo=has_demo,
        has_screenshots=has_screenshots,
        has_playwright=has_playwright,
        has_pytest=has_pytest,
        has_hosted_uptime=has_hosted_uptime,
    )

    return {
        "script": "evidence_manifest.py",
        "generated_at_utc": now.replace(microsecond=0).isoformat(),
        "artifacts": artifacts,
        "calibration_status": calibration_status,
        "n_real": int(n_real),
        "evidence_status": evidence_status,
        "investor_demo_minimum_n_real": 20,
        "private_beta_minimum_n_real": 20,
        "self_audit_disclaimer": (
            "Self-audit, not externally validated.  Readiness scores must "
            "always be reported next to N_real and evidence_status."
        ),
        **SAFETY_STAMPS,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the proof-loop evidence manifest.  Default is dry-run; "
            "pass --write to persist."
        )
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Default.  Compute and print but do not write.",
    )
    group.add_argument(
        "--write",
        action="store_true",
        help="Persist to --output.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_REPO_ROOT / "runtime" / "release" / "evidence_manifest.json",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    manifest = build_manifest()
    summary = (
        f"evidence_status={manifest['evidence_status']} "
        f"N_real={manifest['n_real']} "
        f"calibration_status={manifest['calibration_status']}\n"
    )
    sys.stdout.write(summary)
    if args.write:
        out = Path(args.output)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            sys.stdout.write(f"wrote {out}\n")
        except OSError as exc:  # pragma: no cover
            sys.stderr.write(f"could not write manifest: {type(exc).__name__}\n")
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
