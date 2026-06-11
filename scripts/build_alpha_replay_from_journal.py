"""CLI — build alpha replay records from the operator journal (read-only).

Extracts reconciled outcomes via the journal-to-replay bridge, runs the
replay harness, and prints the JSON report to stdout.  No DB writes, no
network, no broker surface.

Usage:
    python scripts/build_alpha_replay_from_journal.py
    python scripts/build_alpha_replay_from_journal.py --db-path runtime/mvp_local.db --k 5
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.alpha.journal_replay_bridge import journal_replay_report  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="build_alpha_replay_from_journal.py",
        description=(
            "Read-only: journal outcomes -> replay records -> calibration "
            "report. Advisory-only; never authorises execution."
        ),
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Optional SQLite path (defaults to the configured journal DB).",
    )
    parser.add_argument(
        "--k", type=int, default=5, help="k for precision@k (default 5)."
    )
    parser.add_argument(
        "--fit-calibration",
        action="store_true",
        help=(
            "Fit an isotonic/Platt calibration map from the journal's own "
            "resolved outcomes (refuses below the data floor)."
        ),
    )
    parser.add_argument(
        "--apply-calibration",
        action="store_true",
        help=(
            "Apply the calibration artifact given via --calibration-artifact "
            "to the replay probabilities."
        ),
    )
    parser.add_argument(
        "--calibration-artifact",
        default=None,
        help=(
            "Artifact JSON path: load target with --apply-calibration, save "
            "target with --fit-calibration."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON (the default output format; flag kept for scripting).",
    )
    args = parser.parse_args(argv)
    if args.apply_calibration and not args.calibration_artifact:
        parser.error("--apply-calibration requires --calibration-artifact")
    report = journal_replay_report(
        args.db_path,
        k=max(1, args.k),
        fit_calibration=args.fit_calibration,
        calibration_artifact_path=(
            args.calibration_artifact if args.apply_calibration else None
        ),
        save_artifact_path=(
            args.calibration_artifact if args.fit_calibration else None
        ),
    )
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
