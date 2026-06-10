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
    args = parser.parse_args(argv)
    report = journal_replay_report(args.db_path, k=max(1, args.k))
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
