"""Builder — today's price-mover universe payload.

Writes ``data/daily_payload/today_price_movers.json``.

When no live price feed is wired this produces a *static-but-rotating* universe
drawn from ``scripts/minimum_daily_universe.py``: every record has null price
features and is labelled honestly (``freshness="UNVERIFIED"``,
``provider="STATIC_UNIVERSE_FALLBACK"``, ``is_live=false``, ``data_quality=0.25``).

The rotation is deterministic on ``run_date`` (a sliding window over the static
universe) so the daily slice changes day to day without fabricating live data.

Hard requirement (per record):
    ticker, bucket, market, freshness, source_health, provider, is_live,
    why_today, data_quality

Backward compatibility: the loader reads the list under ``movers``; we also
mirror it under ``records`` for the fresh-payload synthesis contract.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

try:
    from scripts.minimum_daily_universe import minimum_universe_records
    from scripts.runtime_common import REPO_ROOT, ensure_directory, utc_timestamp
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from minimum_daily_universe import minimum_universe_records
    from runtime_common import REPO_ROOT, ensure_directory, utc_timestamp


DAILY_PAYLOAD_DIR = REPO_ROOT / "data" / "daily_payload"
PRICE_MOVERS_PATH = DAILY_PAYLOAD_DIR / "today_price_movers.json"

# Size of the daily rotating slice when running on the static fallback.
ROTATION_WINDOW = 24

_FALLBACK_WHY_TODAY = (
    "Included in minimum viable daily market universe; live price mover "
    "confirmation unavailable."
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_directory(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def _rotation_offset(run_date: str, modulo: int) -> int:
    try:
        parsed = date.fromisoformat(run_date)
        return parsed.toordinal() % max(1, modulo)
    except ValueError:
        return 0


def _rotating_slice(rows: list[dict[str, Any]], run_date: str, window: int) -> list[dict[str, Any]]:
    n = len(rows)
    if n == 0:
        return []
    window = min(window, n)
    start = _rotation_offset(run_date, n)
    # Wrap-around window so the slice rotates daily and always has `window` names.
    return [rows[(start + i) % n] for i in range(window)]


def _fallback_mover_record(universe_row: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticker": universe_row["ticker"],
        "asset_name": universe_row.get("name", universe_row["ticker"]),
        "bucket": universe_row.get("bucket", "STATIC_UNIVERSE"),
        "market": universe_row.get("market", "US"),
        "country": universe_row.get("country", "United States"),
        "asset_type": universe_row.get("asset_type", "equity"),
        "price": None,
        "move_pct": None,
        "volume_ratio": None,
        "gap_pct": None,
        "relative_strength_score": None,
        "freshness": "UNVERIFIED",
        "source_health": "UNVERIFIED",
        "provider": "STATIC_UNIVERSE_FALLBACK",
        "is_live": False,
        "why_today": _FALLBACK_WHY_TODAY,
        "data_quality": 0.25,
        # Legacy field kept so older readers that look for `source` still work.
        "source": "static_universe_fallback",
    }


def build_today_price_movers(
    run_date: str,
    generated_at_utc: str | None = None,
    universe_path: Path | None = None,
    window: int = ROTATION_WINDOW,
) -> dict[str, Any]:
    """Return the price-movers payload (pure; honest static-fallback)."""
    universe = minimum_universe_records(universe_path)
    slice_rows = _rotating_slice(universe, run_date, window)
    movers = [_fallback_mover_record(row) for row in slice_rows]
    return {
        "run_date": run_date,
        "generated_at_utc": generated_at_utc or utc_timestamp(),
        "source_health": "UNVERIFIED",
        "provider": "STATIC_UNIVERSE_FALLBACK",
        "is_live": False,
        "rotation_window": len(movers),
        "universe_size": len(universe),
        "movers": movers,
        # Synthesis-contract envelope alias (same list object content).
        "records": movers,
    }


def write_today_price_movers(
    run_date: str,
    path: Path | None = None,
    generated_at_utc: str | None = None,
    universe_path: Path | None = None,
) -> dict[str, Any]:
    payload = build_today_price_movers(run_date, generated_at_utc, universe_path)
    _write_json(path or PRICE_MOVERS_PATH, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build today's price-mover universe payload.")
    parser.add_argument("--run-date", default=None, help="YYYY-MM-DD (default: today UTC)")
    args = parser.parse_args(argv)
    run_date = args.run_date or utc_timestamp()[:10]
    payload = write_today_price_movers(run_date)
    sys.stdout.write(
        f"today_price_movers.json written: source_health={payload['source_health']} "
        f"is_live={payload['is_live']} movers={len(payload['movers'])} "
        f"(rotating slice of {payload['universe_size']})\n"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
