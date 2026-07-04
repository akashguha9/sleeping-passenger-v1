"""Fresh-discovery live refresh — wire the daily payloads to real Yahoo bars.

Feed-the-Loop sprint (2026-07-04), forensic-audit SP-006 family: fresh
discovery had fail-closed every day since 2026-05-22 because all four
``today_*`` payloads sat on ``STATIC_UNIVERSE_FALLBACK``.  The proven live
path already exists: the 6-hourly refresh persists real Yahoo OHLCV bars
into canonical ``signal_events`` (``source_name='market_data'``) for the
index ETFs AND the canonical holdings.  This module turns those ingested
bars into live discovery payloads — no new provider, no new secrets.

Canary (per provider-freshness math)::

    Provider_Age_Minutes = Now_UTC − max(bar.timestamp) over required symbols
    Canary_Status = PASS  iff Provider_Age_Minutes <= MAX_PROVIDER_AGE_MINUTES
                         AND the freshest close is a positive finite number
                         AND no bar timestamp lies in the future

Fail-closed rules (payload level):

* canary FAIL          -> payload stays ``is_live=false`` / ``UNVERIFIED``
                          (the static fallback truth is preserved, never
                          dressed up), refresh reports DEGRADED/BLOCKED;
* canary PASS          -> only records whose OWN bars are fresh get
                          ``is_live=true`` / ``VERIFIED_LIVE``; symbols with
                          stale/absent bars stay honestly UNVERIFIED;
* every payload gains ``artifact_created_at`` so the truth surface can
  age-gate it (>26h DEGRADED, >50h BLOCKED).

Advisory-only: reads the canonical DB, writes the two discovery payloads.
No network, no broker, no execution.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

try:  # package layout
    from scripts import persistence
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.build_today_market_snapshot import build_today_market_snapshot
    from scripts.build_today_price_movers import build_today_price_movers
    from scripts.runtime_common import REPO_ROOT, write_json_atomic
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    import persistence  # type: ignore[no-redef]
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]
    from build_today_market_snapshot import build_today_market_snapshot  # type: ignore[no-redef]
    from build_today_price_movers import build_today_price_movers  # type: ignore[no-redef]
    from runtime_common import REPO_ROOT, write_json_atomic  # type: ignore[no-redef]

DAILY_PAYLOAD_DIR = REPO_ROOT / "data" / "daily_payload"
SNAPSHOT_PATH = DAILY_PAYLOAD_DIR / "today_market_snapshot.json"
MOVERS_PATH = DAILY_PAYLOAD_DIR / "today_price_movers.json"

MAX_PROVIDER_AGE_MINUTES = 26 * 60.0  # one daily cadence + slack
# Weekends + observed exchange holidays legitimately stop new bars without
# the provider being dead.  Within this window the canary can still PASS —
# but ONLY when the provider itself proved alive (a successful market_data
# run within MAX_PROVIDER_AGE_MINUTES).  Distinguishes "markets closed"
# (honest PASS, mode=MARKET_CLOSED_WINDOW) from "provider dead" (FAIL).
MARKET_CLOSED_WINDOW_MINUTES = 4 * 24 * 60.0
CANARY_SYMBOL = "SPY"                 # the proven Yahoo canary
MIN_LIVE_RECORDS = 3                  # payload-level live claim floor
PROVIDER_LIVE = "yahoo_market_data_signal_events"


def _last_successful_provider_run_age_minutes(
    db_path: Any, now: datetime
) -> float | None:
    """Minutes since the last ok-family market_data run in source_run_log."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute(
            "SELECT MAX(timestamp_utc) FROM source_run_log "
            "WHERE source_name='market_data' AND upper(status) LIKE 'OK%'"
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    dt = _parse_iso(row[0] if row else None)
    if dt is None:
        return None
    return (now - dt).total_seconds() / 60.0


def _parse_iso(ts: Any) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def load_bar_series(
    db_path: Any, symbols: set[str]
) -> dict[str, list[tuple[str, float]]]:
    """Latest-two real closes per symbol from ingested market_data bars."""
    series: dict[str, list[tuple[str, float]]] = {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return series
    try:
        rows = conn.execute(
            "SELECT raw_payload FROM signal_events WHERE source_name='market_data'"
        ).fetchall()
    except sqlite3.Error:
        return series
    finally:
        conn.close()
    for (raw,) in rows:
        try:
            p = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        sym = str(p.get("symbol") or "").upper()
        if sym not in symbols:
            continue
        ts = str(p.get("timestamp") or "")
        close = p.get("close") if p.get("close") is not None else p.get("latest_price")
        try:
            close_f = float(close)
        except (TypeError, ValueError):
            continue
        if not ts or close_f <= 0:
            continue
        series.setdefault(sym, []).append((ts, close_f))
    for sym in series:
        series[sym].sort(key=lambda t: t[0])
        series[sym] = series[sym][-2:]
    return series


def run_provider_canary(
    db_path: Any, *, now_utc: datetime | None = None,
    symbol: str = CANARY_SYMBOL,
    max_age_minutes: float = MAX_PROVIDER_AGE_MINUTES,
) -> dict[str, Any]:
    """PASS iff the canary symbol has a fresh, sane, non-future bar."""
    now = now_utc or datetime.now(timezone.utc)
    bars = load_bar_series(db_path, {symbol}).get(symbol, [])
    result: dict[str, Any] = {
        "canary_symbol": symbol,
        "checked_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "max_provider_age_minutes": max_age_minutes,
        "provider_age_minutes": None,
        "latest_close": None,
        "status": "FAIL",
        "reason": None,
    }
    if not bars:
        result["reason"] = "NO_BARS_FOR_CANARY_SYMBOL"
        return result
    ts, close = bars[-1]
    dt = _parse_iso(ts)
    if dt is None:
        result["reason"] = "UNPARSEABLE_BAR_TIMESTAMP"
        return result
    age_min = (now - dt).total_seconds() / 60.0
    result["provider_age_minutes"] = round(age_min, 1)
    result["latest_close"] = close
    if age_min < 0:
        result["reason"] = "BAR_TIMESTAMP_IN_FUTURE"
        return result
    if not (close > 0):
        result["reason"] = "NON_POSITIVE_CLOSE"
        return result
    if age_min <= max_age_minutes:
        result["status"] = "PASS"
        result["mode"] = "FRESH"
        return result
    # Bars older than the cadence: PASS only inside the market-closure
    # window AND with a provably-alive provider (recent successful run).
    if age_min <= MARKET_CLOSED_WINDOW_MINUTES:
        run_age = _last_successful_provider_run_age_minutes(db_path, now)
        result["last_successful_provider_run_age_minutes"] = (
            round(run_age, 1) if run_age is not None else None
        )
        if run_age is not None and run_age <= max_age_minutes:
            result["status"] = "PASS"
            result["mode"] = "MARKET_CLOSED_WINDOW"
            result["reason"] = (
                "newest bar predates the cadence but sits inside the "
                "weekend/holiday window and the provider ran successfully "
                f"{run_age:.0f} minutes ago"
            )
            return result
        result["reason"] = "PROVIDER_DEAD_NO_RECENT_SUCCESSFUL_RUN"
        return result
    result["reason"] = "PROVIDER_DATA_STALE"
    return result


def refresh_fresh_discovery(
    *,
    db_path: Any = None,
    now_utc: datetime | None = None,
    write: bool = False,
    snapshot_path: Any = None,
    movers_path: Any = None,
    max_age_minutes: float = MAX_PROVIDER_AGE_MINUTES,
) -> dict[str, Any]:
    """Enrich the static discovery payloads with real ingested bars."""
    now = now_utc or datetime.now(timezone.utc)
    db = db_path if db_path is not None else persistence.DB_PATH
    run_date = now.strftime("%Y-%m-%d")
    created_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    canary = run_provider_canary(db, now_utc=now, max_age_minutes=max_age_minutes)

    snapshot = build_today_market_snapshot(run_date, generated_at_utc=created_at)
    movers = build_today_price_movers(run_date, generated_at_utc=created_at)
    snapshot["artifact_created_at"] = created_at
    movers["artifact_created_at"] = created_at
    snapshot["provider_canary"] = canary
    movers["provider_canary"] = canary

    live_records = 0
    symbols = {
        str(r.get("ticker") or "").upper() for r in movers.get("records", [])
    }
    if canary["status"] == "PASS":
        # In the market-closed window the latest session's bars are the
        # freshest truth that can exist; label them honestly.
        closed_window = canary.get("mode") == "MARKET_CLOSED_WINDOW"
        allowed_age = (
            MARKET_CLOSED_WINDOW_MINUTES if closed_window else max_age_minutes
        )
        freshness_label = "LATEST_SESSION" if closed_window else "FRESH"
        series = load_bar_series(db, symbols)
        for record in movers.get("records", []):
            sym = str(record.get("ticker") or "").upper()
            bars = series.get(sym, [])
            if not bars:
                continue  # no live bars: record stays honestly UNVERIFIED
            ts, close = bars[-1]
            dt = _parse_iso(ts)
            if dt is None:
                continue
            age_min = (now - dt).total_seconds() / 60.0
            if age_min < 0 or age_min > allowed_age:
                continue
            record["price"] = close
            if len(bars) == 2 and bars[0][1] > 0:
                record["move_pct"] = round((close / bars[0][1] - 1.0) * 100.0, 4)
            record["freshness"] = freshness_label
            record["source_health"] = "VERIFIED_LIVE"
            record["provider"] = PROVIDER_LIVE
            record["is_live"] = True
            record["price_as_of"] = ts
            record["data_quality"] = 0.85 if not closed_window else 0.75
            record["why_today"] = (
                f"Live ingested Yahoo bar ({ts}, {freshness_label}); move "
                f"{record.get('move_pct')}% vs prior bar."
            )
            live_records += 1
        movers["movers"] = list(movers.get("records", []))

    payload_live = canary["status"] == "PASS" and live_records >= MIN_LIVE_RECORDS
    for payload in (snapshot, movers):
        payload["is_live"] = bool(payload_live)
        payload["source_health"] = "VERIFIED_LIVE" if payload_live else "UNVERIFIED"
        payload["provider"] = (
            PROVIDER_LIVE if payload_live else "STATIC_UNIVERSE_FALLBACK"
        )

    state = (
        "OK" if payload_live
        else "DEGRADED" if canary["status"] == "PASS"
        else "BLOCKED"
    )
    result = {
        "report": "fresh_discovery_live_refresh",
        "generated_at_utc": created_at,
        "run_date": run_date,
        "canary": canary,
        "live_record_count": live_records,
        "universe_size": len(symbols),
        "payload_is_live": bool(payload_live),
        "discovery_state": state,
        "write_mode": bool(write),
        **advisory_safety_stamps(),
    }
    if write:
        s_path = Path(snapshot_path) if snapshot_path else SNAPSHOT_PATH
        m_path = Path(movers_path) if movers_path else MOVERS_PATH
        s_path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(s_path, snapshot)
        write_json_atomic(m_path, movers)
        result["snapshot_path"] = str(s_path)
        result["movers_path"] = str(m_path)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--db")
    p.add_argument("--write", action="store_true",
                   help="persist the refreshed payloads (dry-run otherwise)")
    args = p.parse_args(argv)
    result = refresh_fresh_discovery(db_path=args.db, write=args.write)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["discovery_state"] != "BLOCKED" else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
