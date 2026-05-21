"""Broken-windows repair-debt report — visible decay is product decay.

Operationalises the doctrine: an unlogged loss, a fake row left in canonical
truth, or an unreconciled trade is a *broken window* — left visible, it signals
that decay is tolerated and invites more.  This report counts the broken
windows, scores the repair debt, and states the release-gate impact.

It reuses the already-tested discipline engine
(``scripts.complex_systems_diagnostics.compute_broken_windows_discipline``) and
the new closed-loop / truth-purity audits so all three agree on the numbers.

Tracked windows
    unlogged_losses / closed_losses_without_moltbook
    fake_rows_detected
    stale_sources
    manual_trades_missing_reconciliation
    model_reports_missing_catalyst_fingerprints
    unresolved_compliance_warnings
    failed_smoke_checks
    unresolved_repair_debt

Safety
------
Read-only.  No DB writes, no broker calls.  ``release_gate_impact`` is advice
to a human; it blocks no execution path (none exists).

Usage
-----
    python scripts/broken_windows_report.py
    python scripts/broken_windows_report.py --json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
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
    from scripts.complex_systems_diagnostics import (
        compute_broken_windows_discipline,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from complex_systems_diagnostics import (  # type: ignore[no-redef]
        compute_broken_windows_discipline,
    )

try:
    from scripts.closed_loop_learning_audit import build_audit as _closed_loop
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from closed_loop_learning_audit import build_audit as _closed_loop  # type: ignore[no-redef]

try:
    from scripts.runtime_truth_purity_audit import build_audit as _truth_purity
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from runtime_truth_purity_audit import build_audit as _truth_purity  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "runtime" / "mvp_local.db"

ADVISORY_DISCLAIMER = (
    "Advisory-only repair-debt report. release_gate_impact is guidance for a "
    "human operator; it blocks no broker action because none exists."
)


def assess_broken_windows(state: dict[str, Any]) -> dict[str, Any]:
    """Pure: classify broken windows from a counts dict and score the debt."""
    def _i(key: str) -> int:
        try:
            return max(int(state.get(key, 0) or 0), 0)
        except (TypeError, ValueError):
            return 0

    unlogged_losses = _i("unlogged_losses") or _i("closed_losses_without_moltbook")
    fake_rows = _i("fake_rows_detected")
    stale_sources = _i("stale_sources")
    missing_recon = _i("manual_trades_missing_reconciliation")
    missing_fingerprints = _i("model_reports_missing_catalyst_fingerprints")
    compliance_warnings = _i("unresolved_compliance_warnings")
    failed_smoke = _i("failed_smoke_checks")

    # Critical windows poison truth or hide risk: fake data in canonical memory,
    # unlogged losses, and failed smoke checks.
    critical = {
        "fake_rows_detected": fake_rows,
        "unlogged_losses": unlogged_losses,
        "failed_smoke_checks": failed_smoke,
    }
    medium = {
        "manual_trades_missing_reconciliation": missing_recon,
        "stale_sources": stale_sources,
        "model_reports_missing_catalyst_fingerprints": missing_fingerprints,
        "unresolved_compliance_warnings": compliance_warnings,
    }
    critical_count = sum(critical.values())
    medium_count = sum(medium.values())

    # Reuse the tested discipline engine for the canonical repair score.
    discipline = compute_broken_windows_discipline({
        "closed_losses_without_moltbook": unlogged_losses,
        "stale_reconciliation_mismatches": missing_recon,
        "unreviewed_moltbook_items": missing_fingerprints + compliance_warnings,
        "stop_loss_breaches": 0,
        "loss_bridge_complete": unlogged_losses == 0,
    })
    # Repair-debt score blends discipline decay with the truth-poisoning weight
    # of fake rows and failed smoke checks (each a hard critical window).
    extra = min(0.5 * (fake_rows > 0) + 0.5 * (failed_smoke > 0), 1.0)
    repair_debt_score = round(min(discipline["discipline_decay_score"] + extra, 1.0), 4)

    if critical_count > 0:
        release_gate_impact = "BLOCK"
    elif medium_count > 0:
        release_gate_impact = "WARN"
    else:
        release_gate_impact = "CLEAR"

    if fake_rows > 0:
        next_repair = ("Run truth-purity cleanup: fake rows in canonical memory "
                       "must be removed before release.")
    elif unlogged_losses > 0:
        next_repair = discipline["next_repair_action"]
    elif failed_smoke > 0:
        next_repair = "Fix failing smoke checks before release."
    elif missing_recon > 0:
        next_repair = f"Reconcile {missing_recon} open manual trade(s)."
    elif medium_count > 0:
        next_repair = "Clear medium repair debt (stale sources / fingerprints / compliance)."
    else:
        next_repair = "No repair debt — discipline intact."

    out = {
        "repair_debt_score": repair_debt_score,
        "critical_broken_windows": {k: v for k, v in critical.items() if v},
        "medium_broken_windows": {k: v for k, v in medium.items() if v},
        "critical_count": critical_count,
        "medium_count": medium_count,
        "trend_if_available": "unavailable",
        "recommended_next_repair": next_repair,
        "release_gate_impact": release_gate_impact,
        "unresolved_repair_debt": critical_count + medium_count,
        "discipline_decay_score": discipline["discipline_decay_score"],
        "human_review_required": True,
    }
    out.update(_contract.advisory_safety_stamps())
    return out


def _readonly_connect(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        try:
            conn = sqlite3.connect(str(db_path))
        except sqlite3.Error:
            return None
    conn.row_factory = sqlite3.Row
    return conn


def _stale_source_count(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM signal_cell_index"
            " WHERE LOWER(freshness_state) IN ('stale','expired')"
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except sqlite3.Error:
        return 0


def build_report(
    db_path: Path | None = None,
    *,
    state_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Gather real counts from DB + audits, then assess broken windows."""
    db = Path(db_path) if db_path is not None else DEFAULT_DB
    state: dict[str, Any] = {
        "closed_losses_without_moltbook": 0,
        "fake_rows_detected": 0,
        "stale_sources": 0,
        "manual_trades_missing_reconciliation": 0,
        "model_reports_missing_catalyst_fingerprints": 0,
        "unresolved_compliance_warnings": 0,
        "failed_smoke_checks": 0,
    }
    notes: list[str] = []

    loop = _closed_loop(db)
    state["closed_losses_without_moltbook"] = loop.get("closed_losses_without_moltbook", 0)
    state["manual_trades_missing_reconciliation"] = loop.get(
        "manual_trades_without_reconciliation", 0
    )

    purity = _truth_purity(db)
    state["fake_rows_detected"] = purity.get("fake_rows_detected", 0)

    conn = _readonly_connect(db)
    if conn is None:
        notes.append("DB not available — stale-source count defaulted to 0.")
    else:
        try:
            state["stale_sources"] = _stale_source_count(conn)
        finally:
            conn.close()

    if state_overrides:
        state.update(state_overrides)

    assessment = assess_broken_windows(state)
    return {
        "report": "broken_windows_report",
        "db_path": str(db),
        "db_available": loop.get("db_available", False),
        "advisory_disclaimer": ADVISORY_DISCLAIMER,
        "inputs": state,
        "notes": notes,
        **assessment,
        "generated_at": utc_timestamp(),
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="broken_windows_report.py",
        description=(
            "Read-only repair-debt report. release_gate_impact is human "
            "guidance; blocks no execution. No broker calls."
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
        print("Broken-Windows Repair-Debt Report (advisory-only)")
        print("=" * 50)
        print(f"  DB available          : {rep['db_available']}")
        print(f"  repair debt score     : {rep['repair_debt_score']}")
        print(f"  critical windows      : {rep['critical_broken_windows']}")
        print(f"  medium windows        : {rep['medium_broken_windows']}")
        print(f"  release gate impact   : {rep['release_gate_impact']}")
        print(f"  next repair           : {rep['recommended_next_repair']}")
        for note in rep["notes"]:
            print(f"  note: {note}")
        print(f"\n  {rep['advisory_disclaimer']}")
    return 0


__all__ = ["ADVISORY_DISCLAIMER", "assess_broken_windows", "build_report"]


if __name__ == "__main__":
    raise SystemExit(main())
