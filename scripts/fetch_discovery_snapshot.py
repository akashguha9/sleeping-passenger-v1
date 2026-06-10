#!/usr/bin/env python3
"""DISC-B4 (fetch half): pin a dated OHLCV snapshot for the discovery backtest.

Runs on the OPERATOR'S machine (the CI/audit sandbox is firewalled from
market-data hosts).  Resolves the requested universe through the
DISC-B1 mapping (fail loud on any unresolved symbol BEFORE any fetch),
downloads daily OHLCV via yfinance, and writes ONE dated snapshot JSON
that `run_discovery_backtest.py` consumes offline.  Re-running the
backtest against the same snapshot file is byte-identical (B4).

Usage (PowerShell, operator machine):
    python scripts/fetch_discovery_snapshot.py `
        --symbols-file data/discovery_universe.txt `
        --start 2024-01-01 --end 2026-06-01 `
        --out runtime/discovery_snapshot_2026-06-10.json

The tool degrades cleanly without yfinance/network (clear error, exit 2,
nothing partial written).  Advisory-only: fetches public market data,
never calls a broker.  RESULTS FIREWALL: tooling only — no edge claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.discovery_symbol_map import SymbolResolutionError, validate_universe
    from scripts.runtime_common import restrict_file_permissions
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from discovery_symbol_map import SymbolResolutionError, validate_universe  # type: ignore[no-redef]
    from runtime_common import restrict_file_permissions  # type: ignore[no-redef]

TOOL_VERSION = "discovery-snapshot-1.0"


def _read_symbols(path: Path) -> list[str]:
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def fetch_bars_yfinance(
    yahoo_symbol: str, start: str, end: str
) -> list[dict[str, Any]]:
    """One-symbol daily OHLCV fetch.  Lazy yfinance import; raises cleanly."""
    try:
        import yfinance  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - operator machine only
        raise RuntimeError(
            "yfinance is not installed — run on the operator machine "
            "(pip install yfinance) or supply an existing snapshot"
        ) from exc
    frame = yfinance.Ticker(yahoo_symbol).history(
        start=start, end=end, interval="1d", auto_adjust=False
    )
    bars: list[dict[str, Any]] = []
    for idx, row in frame.iterrows():
        bars.append(
            {
                "date": str(idx)[:10],
                "open": str(row.get("Open")),
                "high": str(row.get("High")),
                "low": str(row.get("Low")),
                "close": str(row.get("Close")),
                "adjusted_close": str(row.get("Adj Close", row.get("Close"))),
                "volume": str(row.get("Volume")),
                "source": "YFINANCE_SNAPSHOT",
            }
        )
    return bars


def build_snapshot(
    symbols: list[str],
    start: str,
    end: str,
    fetcher=fetch_bars_yfinance,
) -> dict[str, Any]:
    """Resolve, fetch, and assemble the snapshot dict (deterministic order)."""
    universe = validate_universe(symbols)  # raises listing EVERY failure
    bars_by_symbol: dict[str, list[dict[str, Any]]] = {}
    fetch_errors: dict[str, str] = {}
    for r in sorted(universe["resolved"], key=lambda x: x["yahoo_symbol"]):
        y = r["yahoo_symbol"]
        try:
            bars_by_symbol[y] = fetcher(y, start, end)
        except Exception as exc:  # noqa: BLE001 - reported, run fails loud below
            fetch_errors[y] = f"{type(exc).__name__}: {exc}"
    if fetch_errors:
        raise RuntimeError(
            "fetch FAILED for "
            + ", ".join(sorted(fetch_errors))
            + " — snapshot not written (partial data would bias coverage): "
            + json.dumps(fetch_errors, sort_keys=True)
        )
    body = {
        "tool_version": TOOL_VERSION,
        "start": start,
        "end": end,
        "requested_symbols": list(symbols),
        "resolved": universe["resolved"],
        "bars_by_symbol": bars_by_symbol,
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
        "results_firewall": (
            "Snapshot for retrospective tooling only — not evidence of "
            "forward edge."
        ),
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    body["snapshot_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--symbols-file", type=Path, required=True)
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    symbols = _read_symbols(args.symbols_file)
    try:
        snapshot = build_snapshot(symbols, args.start, args.end)
    except (SymbolResolutionError, RuntimeError) as exc:
        print(f"[fetch_discovery_snapshot] FAILED: {exc}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(snapshot, indent=2, sort_keys=True))
    restrict_file_permissions(args.out)
    print(
        f"[fetch_discovery_snapshot] wrote {args.out} "
        f"({len(snapshot['bars_by_symbol'])} symbols, "
        f"sha256={snapshot['snapshot_sha256'][:16]}…)"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI entry point
    raise SystemExit(main())
