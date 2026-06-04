"""Import historical OHLCV from a CSV into the read-only ohlcv_bars store.

Validates every row via ohlcv_import_contract, rejects synthetic data in
runtime mode, and idempotently upserts the accepted bars (unique on
ticker/date/source). No network, no broker, no execution.

Usage:
    python scripts/import_ohlcv_csv.py path/to/bars.csv
    python scripts/import_ohlcv_csv.py bars.csv --dry-run --json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts import ohlcv_import_contract as contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import ohlcv_import_contract as contract  # type: ignore[no-redef]


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def import_ohlcv(
    rows: list[dict[str, Any]],
    *,
    runtime_mode: bool = True,
    dry_run: bool = False,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Validate then (unless dry_run) persist OHLCV rows. Defensive + idempotent."""
    result = contract.validate_rows(rows, runtime_mode=runtime_mode)
    written = 0
    if not dry_run and result["accepted"]:
        try:
            try:
                from scripts import persistence
            except ModuleNotFoundError:  # pragma: no cover - script-style fallback
                import persistence  # type: ignore[no-redef]
            path = db_path if db_path is not None else persistence.DB_PATH
            written = persistence.insert_ohlcv_bars(result["accepted"], db_path=path)
        except Exception as exc:  # pragma: no cover - defensive
            result["write_error"] = str(exc)
    return {
        "report": "ohlcv_import",
        "rows_read": len(rows),
        "accepted_count": result["accepted_count"],
        "rejected_count": result["rejected_count"],
        "rejected": result["rejected"][:50],
        "rows_written": written,
        "dry_run": dry_run,
        "runtime_mode": runtime_mode,
        "advisory_only": "ADVISORY_ONLY",
        "human_execution_required": True,
        "broker_api_called": False,
    }


def import_ohlcv_file(path: Path, **kwargs) -> dict[str, Any]:
    return import_ohlcv(read_csv_rows(path), **kwargs)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Import historical OHLCV CSV (read-only).")
    p.add_argument("csv_path", type=Path)
    p.add_argument("--db-path", type=Path, default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--allow-synthetic", action="store_true",
                   help="TEST ONLY: permit SYNTHETIC_FIXTURE rows (non-runtime).")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    rep = import_ohlcv_file(
        args.csv_path, runtime_mode=not args.allow_synthetic,
        dry_run=args.dry_run, db_path=args.db_path,
    )
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        print(f"read {rep['rows_read']}, accepted {rep['accepted_count']}, "
              f"rejected {rep['rejected_count']}, written {rep['rows_written']} "
              f"(dry_run={rep['dry_run']})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["read_csv_rows", "import_ohlcv", "import_ohlcv_file"]
