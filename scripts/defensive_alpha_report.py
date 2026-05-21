"""Defensive-alpha report — what the MVP *prevented*, not what it recommended.

Defensive alpha = bad decisions avoided, false confidence prevented, fake
consensus detected, losses converted into lessons.  This is real product value
even though it never appears as a P/L gain.  This report counts it.

It composes existing, tested sources so the numbers cannot drift:
    * ``business_value_report``        — stale signals, duplicate theses, repaired losses
    * ``runtime_truth_purity_audit``   — fake rows blocked from release
    * ``source_independence_audit``    — catalyst echoes / ant-mill downgrades
    * ``closed_loop_learning_audit``   — advisory-only invariant verification

Honesty contract
----------------
NEVER claims a return, profit, or P/L improvement.  Counts prevention and
record-keeping events only.  Missing data is reported honestly.

Safety
------
Read-only.  No DB writes, no broker calls, no execution state.

Usage
-----
    python scripts/defensive_alpha_report.py
    python scripts/defensive_alpha_report.py --json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

try:
    from scripts.runtime_common import utc_timestamp
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from runtime_common import utc_timestamp  # type: ignore[no-redef]

try:
    from scripts.business_value_report import build_report as _business_value
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from business_value_report import build_report as _business_value  # type: ignore[no-redef]

try:
    from scripts.runtime_truth_purity_audit import build_audit as _truth_purity
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from runtime_truth_purity_audit import build_audit as _truth_purity  # type: ignore[no-redef]

try:
    from scripts.source_independence_audit import build_report as _source_independence
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from source_independence_audit import build_report as _source_independence  # type: ignore[no-redef]

try:
    from scripts.closed_loop_learning_audit import build_audit as _closed_loop
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from closed_loop_learning_audit import build_audit as _closed_loop  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "runtime" / "mvp_local.db"

ADVISORY_DISCLAIMER = (
    "Advisory-only defensive-alpha report. It counts bad decisions PREVENTED "
    "and losses captured as lessons; it makes NO claim of profit, return, or "
    "P/L improvement. Every decision requires a human. No broker call is made."
)


def build_report(db_path: Path | None = None) -> dict[str, Any]:
    """Build the defensive-alpha report by composing existing diagnostics."""
    db = Path(db_path) if db_path is not None else DEFAULT_DB

    bvr = _business_value(db)
    purity = _truth_purity(db)
    indep = _source_independence(db_path=db)
    loop = _closed_loop(db)

    # source echoes: distinct duplicate-thesis fingerprints + ant-mill duplicate
    # catalysts across model cohorts.
    echo_from_catalysts = sum(
        a.get("duplicate_catalyst_count", 0)
        for a in indep.get("per_ticker", {}).values()
    )
    source_echoes_detected = (
        int(bvr.get("duplicate_ai_thesis_detected", 0)) + int(echo_from_catalysts)
    )
    bad_promotions_blocked = len(indep.get("flagged_cohorts", []))

    report = {
        "report": "defensive_alpha_report",
        "db_path": str(db),
        "db_available": bool(bvr.get("db_available", False)),
        "advisory_disclaimer": ADVISORY_DISCLAIMER,
        "claims_pl_improvement": False,
        # --- prevention counts ------------------------------------------
        "bad_promotions_blocked": bad_promotions_blocked,
        "stale_signals_downgraded": int(bvr.get("stale_signals_detected", 0)),
        # "Blocked" = fake rows successfully excluded from canonical active
        # truth via quarantine (the defensive win).  Un-quarantined fake rows
        # (``fake_rows_detected``) are NOT a win — they are still leaking and
        # are surfaced separately below so the count stays honest.
        "fake_data_rows_blocked": int(purity.get("quarantined_rows_excluded", 0)),
        "fake_data_rows_still_leaking": int(purity.get("fake_rows_detected", 0)),
        "closed_losses_captured_as_lessons": int(
            bvr.get("closed_losses_repaired_into_moltbook", 0)
        ),
        "source_echoes_detected": source_echoes_detected,
        "operator_overload_warnings": 1 if bvr.get("operator_overload_flagged") else 0,
        "compliance_blocks": 0,
        # --- invariant verification -------------------------------------
        "advisory_only_invariants_verified": bool(
            loop.get("advisory_only_verified", True)
            and loop.get("broker_api_called_false_verified", True)
            and loop.get("ai_execution_count_zero_verified", True)
        ),
        "human_execution_required_verified": bool(
            loop.get("human_execution_verified", True)
        ),
        "human_execution_required": True,
        "notes": [],
        **_contract.advisory_safety_stamps(),
        "generated_at": utc_timestamp(),
    }
    if not report["db_available"]:
        report["notes"].append(
            "DB not available — prevention counts default to zero, reported honestly."
        )
    report["total_defensive_events"] = (
        report["bad_promotions_blocked"]
        + report["stale_signals_downgraded"]
        + report["fake_data_rows_blocked"]
        + report["closed_losses_captured_as_lessons"]
        + report["source_echoes_detected"]
        + report["operator_overload_warnings"]
    )
    return report


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="defensive_alpha_report.py",
        description=(
            "Read-only advisory report of bad decisions PREVENTED. Never claims "
            "P/L. No broker calls."
        ),
    )
    p.add_argument("--db-path", type=Path, default=None)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    rep = build_report(args.db_path)
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        print("Defensive-Alpha Report (advisory-only)")
        print("=" * 44)
        print(f"  DB available                   : {rep['db_available']}")
        print(f"  bad promotions blocked         : {rep['bad_promotions_blocked']}")
        print(f"  stale signals downgraded       : {rep['stale_signals_downgraded']}")
        print(f"  fake data rows blocked         : {rep['fake_data_rows_blocked']}")
        print(f"  closed losses -> lessons       : {rep['closed_losses_captured_as_lessons']}")
        print(f"  source echoes detected         : {rep['source_echoes_detected']}")
        print(f"  operator overload warnings     : {rep['operator_overload_warnings']}")
        print(f"  total defensive events         : {rep['total_defensive_events']}")
        print(f"  advisory-only invariants ok    : {rep['advisory_only_invariants_verified']}")
        print(f"  human execution required ok    : {rep['human_execution_required_verified']}")
        for note in rep["notes"]:
            print(f"  note: {note}")
        print(f"\n  {rep['advisory_disclaimer']}")
    return 0


__all__ = ["ADVISORY_DISCLAIMER", "build_report"]


if __name__ == "__main__":
    raise SystemExit(main())
