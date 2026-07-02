"""Snapshot maturity scanner — the outcome half of the Outcome Factory.

Lifecycle enforced here: SNAPSHOT_OPEN -> SNAPSHOT_MATURED -> SCORED_OUTCOME.
Every OPEN live snapshot is checked at each horizon (T+1/5/21): if the
horizon has elapsed and a price exists, a deduplicated live outcome row is
written; otherwise the row is honestly NOT_MATURED / PRICE_UNAVAILABLE.
Fixture snapshots are counted but NEVER scored as live outcomes.

Pure scan logic (injectable prices, integer days); network (yfinance) only
in the CLI when live snapshots actually need prices. ADVISORY_ONLY — no
broker, no execution.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
REAL_MONEY = "PROHIBITED"

HORIZONS = (1, 5, 21)
NOT_MATURED = "NOT_MATURED"
MATURED_SCORED = "MATURED_SCORED"
PRICE_UNAVAILABLE = "PRICE_UNAVAILABLE"
BENCHMARK_UNAVAILABLE = "BENCHMARK_UNAVAILABLE"

SNAPSHOTS_DEFAULT = Path("data/calibration_corpus/forward_snapshots.jsonl")
OUTCOMES_DEFAULT = Path("data/calibration_corpus/live_outcomes.jsonl")


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _price_at(prices: dict[str, dict[int, float]], ticker: str,
              day: int, tolerance: int = 3) -> float | None:
    series = prices.get(ticker, {})
    for d in range(day, day + tolerance + 1):
        if d in series:
            return float(series[d])
    return None


def scan(snapshots: list[dict[str, Any]], *, as_of_day: int,
         prices: dict[str, dict[int, float]],
         sector_prices: dict[str, dict[int, float]] | None = None,
         existing_outcome_ids: set[str] | None = None) -> dict[str, Any]:
    """Pure maturity scan. Returns outcome rows + per-horizon statuses."""
    existing = existing_outcome_ids or set()
    outcomes: list[dict[str, Any]] = []
    statuses: dict[str, int] = {NOT_MATURED: 0, MATURED_SCORED: 0,
                                PRICE_UNAVAILABLE: 0}
    fixture_ignored = 0
    live_open = 0
    for snap in snapshots:
        if snap.get("source_mode") != "LIVE":
            fixture_ignored += 1          # fixtures never become live outcomes
            continue
        if snap.get("outcome") not in (None, "PENDING") \
                and snap.get("status") not in (None, "OPEN"):
            continue
        live_open += 1
        entry_day = int(snap["entry_day"])
        entry_price = float(snap["entry_price"])
        ticker = str(snap["ticker"])
        want_up = str(snap.get("direction", "UP")).upper() == "UP"
        horizons = snap.get("horizon_days")
        hs = tuple(horizons) if isinstance(horizons, list) else HORIZONS
        for h in hs:
            outcome_id = f"{snap['snapshot_id']}|h{int(h)}"
            if outcome_id in existing:
                continue
            if as_of_day < entry_day + int(h):
                statuses[NOT_MATURED] += 1
                continue
            px = _price_at(prices, ticker, entry_day + int(h))
            if px is None or entry_price <= 0:
                statuses[PRICE_UNAVAILABLE] += 1
                continue
            ret = px / entry_price - 1.0
            residual = ret
            benchmark = BENCHMARK_UNAVAILABLE
            if sector_prices:
                b0 = _price_at(sector_prices, ticker, entry_day)
                b1 = _price_at(sector_prices, ticker, entry_day + int(h))
                if b0 and b1:
                    residual = ret - (b1 / b0 - 1.0)
                    benchmark = "SECTOR_RESIDUAL"
            expected = 1.0 if want_up else -1.0
            hit = 1 if math.copysign(1.0, residual or 1e-12) == expected else 0
            outcomes.append({
                "outcome_id": outcome_id,
                "snapshot_id": snap["snapshot_id"], "ticker": ticker,
                "horizon_days": int(h), "entry_day": entry_day,
                "matured_day": int(as_of_day),
                "entry_price": entry_price, "exit_price": round(px, 6),
                "outcome_return": round(ret, 6),
                "residual_return": round(residual, 6),
                "benchmark": benchmark,
                "edge": snap.get("delta_p_conv"),
                "direction": snap.get("direction"), "hit": hit,
                "source_mode": "LIVE",
                "adapter_run_id": snap.get("adapter_run_id", ""),
                "source_hash": snap.get("source_hash", ""),
                "map_version": snap.get("map_version"),
                "advisory_status": ADVISORY_STATUS,
            })
            statuses[MATURED_SCORED] += 1
    return {"outcomes": outcomes, "statuses": statuses,
            "fixture_snapshots_ignored": fixture_ignored,
            "live_open_snapshots": live_open,
            "as_of_day": int(as_of_day),
            "advisory_status": ADVISORY_STATUS, "real_money": REAL_MONEY}


def append_outcomes(path: Path, outcomes: list[dict[str, Any]], *,
                    mode: str = "dry_run") -> dict[str, Any]:
    existing = {r.get("outcome_id") for r in _rows(path)}
    fresh = [o for o in outcomes if o["outcome_id"] not in existing]
    if mode == "write":
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for o in fresh:
                fh.write(json.dumps(o, sort_keys=True) + "\n")
    return {"mode": mode, "written": len(fresh) if mode == "write" else 0,
            "would_write": len(fresh) if mode != "write" else 0,
            "skipped_duplicates": len(outcomes) - len(fresh)}


def _main() -> int:
    ap = argparse.ArgumentParser(description="Snapshot maturity scanner")
    ap.add_argument("--write", choices=("dry_run", "write"),
                    default="dry_run")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--snapshots", type=Path, default=SNAPSHOTS_DEFAULT)
    ap.add_argument("--outcomes", type=Path, default=OUTCOMES_DEFAULT)
    args = ap.parse_args()
    mode = "dry_run" if args.dry_run else args.write
    from datetime import datetime, timezone
    as_of_day = int(datetime.now(timezone.utc).timestamp()) // 86400 - 18262
    snapshots = _rows(args.snapshots)
    live = [s for s in snapshots if s.get("source_mode") == "LIVE"]
    prices: dict[str, dict[int, float]] = {}
    status = "OK"
    blocker = None
    due = [s for s in live if as_of_day >= int(s["entry_day"]) + 1]
    if due:
        try:
            import yfinance as yf
            for t in sorted({s["ticker"] for s in due}):
                hist = yf.Ticker(t).history(period="3mo", interval="1d")
                prices[t] = {int(ts.timestamp()) // 86400: float(c)
                             for ts, c in hist["Close"].items()}
        except Exception as exc:
            status, blocker = "BLOCKED", f"PRICE_FETCH_FAILED: {type(exc).__name__}"
    result = scan(snapshots, as_of_day=as_of_day, prices=prices,
                  existing_outcome_ids={r.get("outcome_id")
                                        for r in _rows(args.outcomes)})
    write_report = append_outcomes(args.outcomes, result["outcomes"],
                                   mode=mode)
    report = {**{k: v for k, v in result.items() if k != "outcomes"},
              "write": write_report, "status": status, "blocker": blocker,
              "mode": mode}
    out = Path("runtime/snapshot_maturity_report.json")
    if mode == "write":
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True),
                       encoding="utf-8")
        md = ["# Snapshot maturity report", "",
              f"as_of_day: {report['as_of_day']} · status: {status}",
              f"live open snapshots: {report['live_open_snapshots']} · "
              f"fixture ignored: {report['fixture_snapshots_ignored']}",
              f"statuses: {report['statuses']}",
              f"outcomes written: {write_report['written']}", "",
              f"{ADVISORY_STATUS} · real money: {REAL_MONEY}"]
        Path("runtime/snapshot_maturity_report.md").write_text(
            "\n".join(md), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if status != "BLOCKED" else 2


if __name__ == "__main__":
    raise SystemExit(_main())
