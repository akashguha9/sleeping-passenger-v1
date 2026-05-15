"""
CLI: validate (and optionally write) a paper-trade CSV ledger.

Usage:
    python scripts/import_paper_trades.py --file exports/paper_trades.csv
    python scripts/import_paper_trades.py --file exports/paper_trades.csv --dry-run
    python scripts/import_paper_trades.py --file exports/paper_trades.csv --write

Defaults to dry-run.  ``--write`` is the only flag that mutates the DB,
and even then every row is inserted with ``trade_mode='PAPER'`` and the
broker / execution stamps stay locked.

Advisory-only.  No broker is contacted.  No order is placed.  No real
capital is committed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from scripts.paper_trade_ledger import import_paper_trades
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from paper_trade_ledger import import_paper_trades  # type: ignore[no-redef]


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="import_paper_trades.py",
        description=(
            "Validate (and optionally write) a paper-trade ledger CSV.  "
            "Default mode is dry-run; pass --write to persist.  Paper "
            "rows never imply broker execution."
        ),
    )
    p.add_argument("--file", type=Path, required=True, help="Path to the CSV ledger.")
    grp = p.add_mutually_exclusive_group()
    grp.add_argument("--dry-run", action="store_true", help="Validate only (default).")
    grp.add_argument("--write", action="store_true", help="Persist valid rows.")
    p.add_argument("--json", action="store_true", help="Emit JSON summary instead of text.")
    return p


def _render_text(payload: dict) -> str:
    lines: list[str] = []
    lines.append("Paper-trade ledger import")
    lines.append("=" * 26)
    lines.append(f"File           : {payload['path']}")
    lines.append(f"Mode           : {'WRITE' if payload.get('write') else 'DRY-RUN'}")
    lines.append(f"Rows seen      : {payload['rows_seen']}")
    lines.append(f"Rows valid     : {payload['rows_valid']}")
    lines.append(f"Rows imported  : {payload['rows_imported']}")
    lines.append(f"Rows rejected  : {payload['rows_rejected']}")
    lines.append(f"Rows duplicate : {payload['rows_duplicate']}")
    if payload.get("warnings"):
        lines.append("Warnings: " + ", ".join(payload["warnings"]))
    for row in payload.get("items", []):
        if not row.get("valid"):
            lines.append(
                f"  - REJECT {row['paper_trade_id'] or '<no id>':<20} "
                f"{row['symbol']:<12} reasons={','.join(row['rejection_reasons']) or '-'}"
            )
        elif row.get("imported"):
            lines.append(
                f"  - IMPORT {row['paper_trade_id'] or '<no id>':<20} {row['symbol']}"
            )
        else:
            lines.append(
                f"  - OK     {row['paper_trade_id'] or '<no id>':<20} {row['symbol']}"
            )
    lines.append("")
    lines.append(payload["advisory_disclaimer"])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    payload = import_paper_trades(args.file, write=bool(args.write))
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2, default=str))
    else:
        print(_render_text(payload))
    # Exit non-zero if rows were rejected so CI/audit scripts can detect it.
    return 0 if payload.get("rows_rejected", 0) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
