"""Retrocast calibration — resolved prediction markets as a pre-labeled corpus.

Every *resolved* event market is a completed belief→outcome experiment with a
public price path. This harness replays ΔP shocks from resolved-market
histories through a frozen event taxonomy and measures whether mapped
equities moved in the taxonomy's direction afterwards ("transmission").

Outputs:
  * RetrocastRecord rows (evidence_class=IMPORTED_BACKTEST — never confused
    with live evidence; the calibration ladder counts LIVE rows only)
  * a per-category transmission report with a VALIDATED / UNVALIDATED /
    BANNED_NO_TRANSMISSION status — the category ban list is the live
    bridge's kill-switch: no live edge may be emitted for a banned category.

Anti-hindsight discipline: mapping is category-level (taxonomy rules frozen
before the study), never per-event hand-tuning. Fixture mode is explicit and
labeled; adapter mode is deliberately not wired in this sprint.

Pure/deterministic (seeded fixtures, integer days, no network, no wall
clock). ADVISORY_ONLY — no broker execution, no order placement.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import Any

from scripts.prediction_market_shock_engine import delta_p, is_persistent

ADVISORY_STATUS = "ADVISORY_ONLY"
REAL_MONEY = "PROHIBITED"

IMPORTED_BACKTEST = "IMPORTED_BACKTEST"
FIXTURE_DEMONSTRATION = "FIXTURE_DEMONSTRATION"

STATUS_VALIDATED = "VALIDATED"
STATUS_UNVALIDATED_N = "UNVALIDATED_INSUFFICIENT_N"
STATUS_UNVALIDATED_WEAK = "UNVALIDATED_WEAK"
STATUS_BANNED = "BANNED_NO_TRANSMISSION"

MIN_N_FOR_VERDICT = 12
VALIDATE_HIT_RATE = 0.55
VALIDATE_TSTAT = 1.5
BAN_HIT_RATE = 0.45

HORIZONS = (1, 5, 21)
PRIMARY_HORIZON = 5

# Live calibration ladder (LIVE evidence only; imported rows never count).
LADDER = ((100, "STRONGER"), (30, "FIRST_PASS"), (10, "PROVISIONAL"),
          (1, "CAPTURE_STARTED_NO_LABELS"), (0, "NO_LIVE_EVIDENCE"))


def _fwd_return(series: dict[int, float], day: int, horizon: int) -> float | None:
    p0 = series.get(day)
    if p0 is None or p0 <= 0:
        return None
    for d in range(day + horizon, day + horizon + 4):  # tolerate short gaps
        if d in series:
            return (series[d] - p0) / p0
    return None


def _shock_days(history: list[dict[str, Any]], threshold: float,
                window: int) -> list[tuple[int, float]]:
    """Scan the full price path for persistent shocks (one per breach day)."""
    pts = sorted(history, key=lambda r: int(r["day"]))
    out: list[tuple[int, float]] = []
    last_day = -10**9
    for i in range(window, len(pts) + 1):
        sub = pts[:i]
        dp = delta_p(sub, window)
        if abs(dp) >= threshold and is_persistent(sub, window):
            day = int(sub[-1]["day"])
            if day - last_day >= window:          # de-overlap
                out.append((day, dp))
                last_day = day
    return out


def run_retrocast(markets: list[dict[str, Any]], taxonomy: dict[str, Any],
                  equity_prices: dict[str, dict[int, float]], *,
                  threshold: float = 0.10, window: int = 5,
                  data_mode: str = FIXTURE_DEMONSTRATION) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for mkt in markets:
        cat = str(mkt["category"])
        rule = taxonomy.get("categories", {}).get(cat)
        if rule is None:
            continue
        direction_mult = 1.0 if str(rule.get("direction", "UP")).upper() == "UP" else -1.0
        for day, dp in _shock_days(mkt["price_history"], threshold, window):
            for ticker in rule.get("tickers", []):
                series = equity_prices.get(str(ticker), {})
                fwd = {h: _fwd_return(series, day, h) for h in HORIZONS}
                if fwd[PRIMARY_HORIZON] is None:
                    continue
                expected_sign = math.copysign(1.0, dp * direction_mult)
                rec = {
                    "record_id": f"{mkt['market_id']}|{ticker}|{day}",
                    "market_id": str(mkt["market_id"]), "category": cat,
                    "ticker": str(ticker), "shock_day": day,
                    "delta_p": round(dp, 6),
                    "resolved_outcome": mkt.get("resolved_outcome"),
                    "evidence_class": IMPORTED_BACKTEST,
                    "data_mode": data_mode,
                    "advisory_status": ADVISORY_STATUS,
                }
                for h in HORIZONS:
                    rec[f"fwd_return_{h}"] = (None if fwd[h] is None
                                              else round(fwd[h], 6))
                    rec[f"aligned_{h}"] = (None if fwd[h] is None else
                                           (math.copysign(1.0, fwd[h])
                                            == expected_sign))
                rec["aligned_return_primary"] = round(
                    fwd[PRIMARY_HORIZON] * expected_sign, 6)
                records.append(rec)
    report = _category_report(records)
    return {"records": records, "category_report": report,
            "category_ban_list": [c for c, r in report.items()
                                  if r["status"] == STATUS_BANNED],
            "data_mode": data_mode, "advisory_status": ADVISORY_STATUS,
            "real_money": REAL_MONEY}


def _category_report(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        by_cat.setdefault(r["category"], []).append(r)
    out: dict[str, dict[str, Any]] = {}
    for cat, rows in sorted(by_cat.items()):
        aligned = [r["aligned_return_primary"] for r in rows]
        n = len(aligned)
        hits = sum(1 for r in rows if r[f"aligned_{PRIMARY_HORIZON}"])
        hit_rate = hits / n if n else 0.0
        mean = sum(aligned) / n if n else 0.0
        var = (sum((x - mean) ** 2 for x in aligned) / (n - 1)) if n > 1 else 0.0
        std = math.sqrt(var)
        tstat = (mean / (std / math.sqrt(n))) if (n > 1 and std > 0) else 0.0
        if n < MIN_N_FOR_VERDICT:
            status = STATUS_UNVALIDATED_N
        elif hit_rate >= VALIDATE_HIT_RATE and tstat >= VALIDATE_TSTAT:
            status = STATUS_VALIDATED
        elif hit_rate <= BAN_HIT_RATE:
            status = STATUS_BANNED
        else:
            status = STATUS_UNVALIDATED_WEAK
        out[cat] = {"n": n, "hit_rate": round(hit_rate, 4),
                    "mean_aligned_return": round(mean, 6),
                    "tstat": round(tstat, 3), "status": status,
                    "horizon_days": PRIMARY_HORIZON}
    return out


def ladder_status(live_labeled_count: int) -> str:
    for floor, name in LADDER:
        if live_labeled_count >= floor and floor > 0:
            return name
        if floor == 0:
            return name
    return "NO_LIVE_EVIDENCE"


def evidence_separation(records: list[dict[str, Any]],
                        snapshots_path: Path | None) -> dict[str, Any]:
    """Imported-backtest vs live evidence must never be pooled: the ladder
    advances on LIVE labeled rows only."""
    n_imported = sum(1 for r in records
                     if r.get("evidence_class") == IMPORTED_BACKTEST)
    n_live_pending = 0
    n_live_labeled = 0
    if snapshots_path is not None and snapshots_path.exists():
        for line in snapshots_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("data_mode") != "LIVE":
                continue
            if row.get("outcome") in (None, "PENDING"):
                n_live_pending += 1
            else:
                n_live_labeled += 1
    return {"n_imported_backtest": n_imported,
            "n_live_pending": n_live_pending,
            "n_live_labeled": n_live_labeled,
            "ladder_status_live_only": ladder_status(n_live_labeled),
            "imported_counts_toward_ladder": False}


def write_outputs(result: dict[str, Any], *, records_path: Path,
                  report_path: Path, snapshots_path: Path | None = None,
                  mode: str = "dry_run") -> dict[str, Any]:
    sep = evidence_separation(result["records"], snapshots_path)
    full_report = {"category_report": result["category_report"],
                   "category_ban_list": result["category_ban_list"],
                   "evidence_separation": sep,
                   "data_mode": result["data_mode"],
                   "advisory_status": ADVISORY_STATUS,
                   "real_money": REAL_MONEY}
    if mode == "write":
        records_path.parent.mkdir(parents=True, exist_ok=True)
        with records_path.open("w", encoding="utf-8") as fh:
            for r in result["records"]:
                fh.write(json.dumps(r, sort_keys=True) + "\n")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(full_report, indent=2, sort_keys=True),
                               encoding="utf-8")
    return {"mode": mode, "n_records": len(result["records"]),
            "report": full_report}


# --- deterministic fixture corpus ----------------------------------------------

def fixture_taxonomy() -> dict[str, Any]:
    return {"schema": "event_taxonomy/v1", "frozen": True,
            "categories": {
                "policy_rates": {"tickers": ["FIXA"], "direction": "UP"},
                "elections_noise": {"tickers": ["FIXB"], "direction": "UP"},
            }}


def fixture_resolved_markets_and_prices(
        n_per_category: int = 28, seed: int = 7,
) -> tuple[list[dict[str, Any]], dict[str, dict[int, float]]]:
    """Two categories: `policy_rates` has real transmission (FIXA drifts with
    the shock sign); `elections_noise` has none (FIXB is a coin flip).
    Deterministic via seeded RNG."""
    rng = random.Random(seed)
    markets: list[dict[str, Any]] = []
    fixa: dict[int, float] = {}
    fixb: dict[int, float] = {}
    pa, pb = 100.0, 100.0
    day0 = 100
    horizon_pad = max(HORIZONS) + 6
    span = 40
    for i in range(n_per_category):
        base = day0 + i * (span + horizon_pad)
        up = rng.random() < 0.5
        p = 0.50
        hist = []
        for d in range(span):
            drift = (0.035 if up else -0.035) if 20 <= d < 26 else 0.0
            p = min(0.97, max(0.03, p + drift + rng.uniform(-0.004, 0.004)))
            hist.append({"day": base + d, "p": round(p, 4)})
        markets.append({"market_id": f"FIX-RATES-{i:02d}",
                        "category": "policy_rates",
                        "resolved_outcome": 1 if up else 0,
                        "price_history": hist})
        markets.append({"market_id": f"FIX-ELEC-{i:02d}",
                        "category": "elections_noise",
                        "resolved_outcome": rng.randint(0, 1),
                        "price_history": [dict(r) for r in hist]})
        shock_sign = 1.0 if up else -1.0
        noise_sign = 1.0 if rng.random() < 0.5 else -1.0
        for d in range(span + horizon_pad):
            day = base + d
            in_window = 24 <= d < 24 + max(HORIZONS) + 2
            pa *= 1.0 + (0.004 * shock_sign if in_window else 0.0) \
                + rng.uniform(-0.001, 0.001)
            pb *= 1.0 + (0.004 * noise_sign if in_window else 0.0) \
                + rng.uniform(-0.001, 0.001)
            fixa[day] = round(pa, 4)
            fixb[day] = round(pb, 4)
    return markets, {"FIXA": fixa, "FIXB": fixb}


def _main() -> int:
    ap = argparse.ArgumentParser(
        description="Retrocast resolved-market fixture study (advisory)")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--mode", choices=("dry_run", "write"), default="dry_run")
    ap.add_argument("--records-out", type=Path,
                    default=Path("data/calibration_corpus/retrocast.jsonl"))
    ap.add_argument("--report-out", type=Path,
                    default=Path("runtime/retrocast_report.json"))
    ap.add_argument("--snapshots", type=Path,
                    default=Path("data/calibration_corpus/forward_snapshots.jsonl"))
    args = ap.parse_args()
    if not args.demo:
        raise SystemExit("live adapter mode not wired in this sprint; use --demo")
    markets, prices = fixture_resolved_markets_and_prices()
    result = run_retrocast(markets, fixture_taxonomy(), prices)
    out = write_outputs(result, records_path=args.records_out,
                        report_path=args.report_out,
                        snapshots_path=args.snapshots, mode=args.mode)
    print(json.dumps(out["report"], indent=2, sort_keys=True))
    print(json.dumps({"mode": out["mode"], "n_records": out["n_records"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
