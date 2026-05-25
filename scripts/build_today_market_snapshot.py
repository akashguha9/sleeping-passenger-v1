"""Builder — today's broad market snapshot payload.

Writes ``data/daily_payload/today_market_snapshot.json``.

Design rule (honest-fallback): if no live market-data provider is wired, this
builder STILL produces valid JSON, but every generated record is labelled
honestly — ``source_health = "UNVERIFIED"``, ``provider =
"STATIC_UNIVERSE_FALLBACK"``, ``is_live = false``. We never pretend a static
fallback is a live feed.

Backward compatibility: the existing loader (scripts/daily_payload.py) reads
``indices/rates/commodities/fx/regime_notes`` and ``source_health/
snapshot_timestamp_utc``. Those keys are preserved; the new envelope fields
(``generated_at_utc/provider/is_live/macro_proxies``) are added alongside.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import REPO_ROOT, ensure_directory, utc_timestamp
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from runtime_common import REPO_ROOT, ensure_directory, utc_timestamp


DAILY_PAYLOAD_DIR = REPO_ROOT / "data" / "daily_payload"
MARKET_SNAPSHOT_PATH = DAILY_PAYLOAD_DIR / "today_market_snapshot.json"

# Broad market context — index proxies and macro themes. These are *context*,
# not movers; they orient the models on regime without claiming live levels.
_INDICES: tuple[dict[str, str], ...] = (
    {"ticker": "SPY", "name": "S&P 500 ETF", "market": "US", "asset_class": "equity_index_proxy"},
    {"ticker": "QQQ", "name": "Nasdaq 100 ETF", "market": "US", "asset_class": "equity_index_proxy"},
    {"ticker": "IWM", "name": "Russell 2000 ETF", "market": "US", "asset_class": "equity_index_proxy"},
    {"ticker": "^NSEI", "name": "Nifty 50", "market": "India", "asset_class": "equity_index"},
    {"ticker": "^GDAXI", "name": "DAX", "market": "Germany", "asset_class": "equity_index"},
)
_MACRO_PROXIES: tuple[dict[str, str], ...] = (
    {"ticker": "GLD", "theme": "gold_safe_haven"},
    {"ticker": "TLT", "theme": "long_duration"},
    {"ticker": "TIP", "theme": "inflation_protected_bonds"},
    {"ticker": "USO", "theme": "oil_proxy"},
    {"ticker": "UUP", "theme": "usd_proxy"},
    {"ticker": "BTC-USD", "theme": "crypto_risk_proxy"},
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_directory(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def build_today_market_snapshot(run_date: str, generated_at_utc: str | None = None) -> dict[str, Any]:
    """Return the market-snapshot payload (pure; honest UNVERIFIED fallback)."""
    return {
        "run_date": run_date,
        "generated_at_utc": generated_at_utc or utc_timestamp(),
        "snapshot_timestamp_utc": None,
        "source_health": "UNVERIFIED",
        "provider": "STATIC_UNIVERSE_FALLBACK",
        "is_live": False,
        "indices": [dict(row) for row in _INDICES],
        "macro_proxies": [dict(row) for row in _MACRO_PROXIES],
        # Legacy detail buckets retained for loader backward compatibility.
        "rates": [],
        "commodities": [],
        "fx": [],
        "regime_notes": [
            {
                "note": (
                    "Market snapshot generated from static fallback universe; "
                    "live data not yet verified."
                ),
                "freshness": "UNVERIFIED",
            }
        ],
    }


def write_today_market_snapshot(
    run_date: str,
    path: Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    payload = build_today_market_snapshot(run_date, generated_at_utc)
    _write_json(path or MARKET_SNAPSHOT_PATH, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build today's market snapshot payload.")
    parser.add_argument("--run-date", default=None, help="YYYY-MM-DD (default: today UTC)")
    args = parser.parse_args(argv)
    run_date = args.run_date or utc_timestamp()[:10]
    payload = write_today_market_snapshot(run_date)
    sys.stdout.write(
        f"today_market_snapshot.json written: source_health={payload['source_health']} "
        f"is_live={payload['is_live']} indices={len(payload['indices'])} "
        f"macro_proxies={len(payload['macro_proxies'])}\n"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
