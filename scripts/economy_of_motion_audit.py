"""Economy of Motion Audit — "hack away the unessential".

"It is not daily increase but daily decrease — hack away the unessential."
The MVP's quality is *useful signal minus ornamentation*, not feature count.
This audit measures system sharpness: how much of what the system emits is
useful versus redundant, decorative, stale, mock-polluted, or duplicated.

EconomyScore (0–10)::

    EconomyScore = 10 * UsefulSignals /
        max(UsefulSignals + RedundantSignals + DecorativeSignals
            + StaleSignals + MockPollution + DuplicateDiagnostics, 1)

SystemSharpness::

    SystemSharpness = UsefulDiagnostics - DecorativeComplexity
                      - StaleDataDebt - DuplicateSignalDebt - MockPollutionPenalty

It reuses the existing release-gate audits so the numbers cannot drift:

    runtime_truth_purity_audit  -> mock pollution (un-quarantined fake rows)
    broken_windows_report       -> stale sources, unresolved repair debt
    closed_loop_learning_audit  -> signals without outcomes (decay debt)

Safety
------
Read-only.  No DB writes, no broker calls.  ``release_gate_impact`` is human
guidance.  Advisory-only.

Usage
-----
    python scripts/economy_of_motion_audit.py
    python scripts/economy_of_motion_audit.py --json
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
    from scripts.runtime_truth_purity_audit import build_audit as _truth_purity
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from runtime_truth_purity_audit import build_audit as _truth_purity  # type: ignore[no-redef]

try:
    from scripts.broken_windows_report import build_report as _broken_windows
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from broken_windows_report import build_report as _broken_windows  # type: ignore[no-redef]

try:
    from scripts.closed_loop_learning_audit import build_audit as _closed_loop
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from closed_loop_learning_audit import build_audit as _closed_loop  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "runtime" / "mvp_local.db"

ADVISORY_DISCLAIMER = (
    "Advisory-only economy-of-motion audit. It scores useful signal versus "
    "ornamentation and names removal candidates; it deletes nothing and makes "
    "no broker call."
)


def compute_economy_score(counts: dict[str, int]) -> dict[str, Any]:
    """Pure: compute EconomyScore (0–10) and SystemSharpness from raw counts.

    ``counts`` keys (missing → 0):
        useful_signal_count, redundant_signal_count, decorative_signal_count,
        stale_signal_count, mock_pollution_count, duplicate_diagnostic_count
    """
    def _i(key: str) -> int:
        try:
            return max(int(counts.get(key, 0) or 0), 0)
        except (TypeError, ValueError):
            return 0

    useful = _i("useful_signal_count")
    redundant = _i("redundant_signal_count")
    decorative = _i("decorative_signal_count")
    stale = _i("stale_signal_count")
    mock = _i("mock_pollution_count")
    duplicate = _i("duplicate_diagnostic_count")

    denom = max(useful + redundant + decorative + stale + mock + duplicate, 1)
    economy_score = round(10.0 * useful / denom, 4)
    system_sharpness = round(
        float(useful) - decorative - stale - duplicate - mock, 4
    )

    removal: list[str] = []
    if mock:
        removal.append(f"{mock} mock/un-quarantined pollution row(s)")
    if stale:
        removal.append(f"{stale} stale signal(s)/source(s)")
    if duplicate:
        removal.append(f"{duplicate} duplicate diagnostic(s)")
    if decorative:
        removal.append(f"{decorative} decorative signal(s)")
    if redundant:
        removal.append(f"{redundant} redundant signal(s)")

    # Mock pollution is the only economy debt that should *block* — it poisons
    # canonical truth.  Everything else is WARN/CLEAR (hygiene, not poison).
    if mock > 0:
        gate = "BLOCK"
    elif removal:
        gate = "WARN"
    else:
        gate = "CLEAR"

    out: dict[str, Any] = {
        "economy_score": economy_score,
        "system_sharpness": system_sharpness,
        "useful_signal_count": useful,
        "redundant_signal_count": redundant,
        "decorative_signal_count": decorative,
        "stale_signal_count": stale,
        "mock_pollution_count": mock,
        "duplicate_diagnostic_count": duplicate,
        "recommended_removal_candidates": removal,
        "release_gate_impact": gate,
        "human_review_required": True,
    }
    out.update(_contract.advisory_safety_stamps())
    return out


def build_audit(db_path: Path | None = None) -> dict[str, Any]:
    """Gather economy-of-motion counts from the existing release-gate audits."""
    db = Path(db_path) if db_path is not None else DEFAULT_DB

    purity = _truth_purity(db)
    windows = _broken_windows(db)
    loop = _closed_loop(db)

    # Mock pollution = un-quarantined fake rows.  Quarantined rows are NOT debt —
    # they have already been hacked away from canonical *active* truth.
    mock = int(purity.get("fake_rows_detected", 0) or 0)
    quarantined = int(purity.get("quarantined_rows_excluded", 0) or 0)
    stale = int(windows.get("inputs", {}).get("stale_sources", 0) or 0)
    # Unreconciled trades clutter the active decision surface (redundant motion).
    redundant = int(loop.get("manual_trades_without_reconciliation", 0) or 0)
    # Useful signal proxy = the clean canonical rows that survive the purity
    # scan: total scanned, minus active pollution, minus the already-excluded
    # quarantine.  This is the *operator truth surface*, bounded and meaningful,
    # not the raw multi-thousand-row signal ledger.
    total_scanned = int(purity.get("total_rows_scanned", 0) or 0)
    useful = max(total_scanned - mock - quarantined, 0)

    counts = {
        "useful_signal_count": useful,
        "redundant_signal_count": redundant,
        "decorative_signal_count": 0,
        "stale_signal_count": stale,
        "mock_pollution_count": mock,
        "duplicate_diagnostic_count": 0,
    }
    assessment = compute_economy_score(counts)
    return {
        "report": "economy_of_motion_audit",
        "db_path": str(db),
        "db_available": bool(purity.get("db_available", False)),
        "advisory_disclaimer": ADVISORY_DISCLAIMER,
        "quarantined_rows_excluded": quarantined,
        "sources": {
            "truth_purity_fake_rows": mock,
            "clean_canonical_rows": useful,
            "stale_sources": stale,
            "unreconciled_trades": redundant,
        },
        **assessment,
        "generated_at": utc_timestamp(),
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="economy_of_motion_audit.py",
        description=(
            "Read-only economy-of-motion audit. Useful signal vs ornamentation. "
            "No deletes, no broker calls."
        ),
    )
    p.add_argument("--db-path", type=Path, default=None)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    rep = build_audit(args.db_path)
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        print("Economy of Motion Audit (advisory-only)")
        print("=" * 40)
        print(f"  economy score        : {rep['economy_score']} / 10")
        print(f"  system sharpness     : {rep['system_sharpness']}")
        print(f"  mock pollution       : {rep['mock_pollution_count']}")
        print(f"  quarantined (cleaned): {rep['quarantined_rows_excluded']}")
        print(f"  removal candidates   : {rep['recommended_removal_candidates']}")
        print(f"  release gate impact  : {rep['release_gate_impact']}")
        print(f"\n  {rep['advisory_disclaimer']}")
    return 0


__all__ = ["compute_economy_score", "build_audit", "ADVISORY_DISCLAIMER"]


if __name__ == "__main__":
    raise SystemExit(main())
