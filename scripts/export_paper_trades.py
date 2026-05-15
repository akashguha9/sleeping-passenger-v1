"""
CLI: round-trip the current paper-trade rows back to a CSV for Excel review.

Usage:
    python scripts/export_paper_trades.py
    python scripts/export_paper_trades.py --out exports/paper_trades_review.csv

Advisory-only.  Read-only with respect to the DB (no UPDATE / DELETE).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from scripts.paper_trade_ledger import export_paper_trades
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from paper_trade_ledger import export_paper_trades  # type: ignore[no-redef]


DEFAULT_OUT = Path("exports") / "paper_trades_review.csv"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="export_paper_trades.py",
        description=(
            "Round-trip current paper-trade rows (trade_mode='PAPER') back "
            "to CSV for further Excel review.  Read-only on the DB."
        ),
    )
    p.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output path (default: {DEFAULT_OUT})",
    )
    p.add_argument("--json", action="store_true", help="Emit JSON summary instead of text.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    payload = export_paper_trades(args.out)
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2, default=str))
        return 0
    print(f"Exported paper trades -> {payload['path']}")
    print(f"Rows exported: {payload['rows_exported']}")
    print(payload["advisory_disclaimer"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
