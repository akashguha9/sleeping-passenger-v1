"""
CLI: write a blank Excel-friendly paper-trade ledger template.

Usage:
    python scripts/export_paper_trade_template.py
    python scripts/export_paper_trade_template.py --out exports/paper_trades.csv
    python scripts/export_paper_trade_template.py --include-example

Advisory-only.  This script writes a CSV template the operator opens in
Excel and fills in by hand.  Paper-trade ledger only — no broker is
contacted, no order is placed, no real capital is committed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from scripts.paper_trade_ledger import write_template
except ModuleNotFoundError:
    # Allow direct invocation without the `scripts.` package prefix.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from paper_trade_ledger import write_template  # type: ignore[no-redef]


DEFAULT_OUT = Path("exports") / "paper_trade_template.csv"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="export_paper_trade_template.py",
        description=(
            "Write an Excel/CSV template for the operator-maintained paper "
            "trade ledger.  Paper trades are rehearsal/calibration data "
            "only; no broker is contacted."
        ),
    )
    p.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output path (default: {DEFAULT_OUT})",
    )
    p.add_argument(
        "--include-example",
        action="store_true",
        help="Write one obviously-fake example row (paper-only, EXAMPLE_TICKER).",
    )
    p.add_argument("--json", action="store_true", help="Emit JSON summary instead of text.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    payload = write_template(args.out, include_example=bool(args.include_example))
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2, default=str))
        return 0
    print(f"Wrote paper-trade ledger template -> {payload['path']}")
    print(f"Columns: {len(payload['columns'])}")
    if payload["example_rows_written"]:
        print(f"Example rows written: {payload['example_rows_written']} (replace before importing)")
    print(payload["advisory_disclaimer"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
