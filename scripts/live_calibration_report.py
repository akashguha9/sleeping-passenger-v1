"""Live calibration report — the self-grading readout of the Outcome Factory.

Consumes matured LIVE outcomes (never fixture, never imported-backtest) and
reports hit rates, residuals, and the calibration ladder:

  NO_LIVE_EVIDENCE (N=0) -> WARMING_UP (1-9) -> PROVISIONAL (10-29)
  -> FIRST_PASS (30-99) -> READY (>=100 and ECE acceptable)

LadderScore: 0 / 2.5 / 5.0 / 7.5 / 10.0. ADVISORY_ONLY.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
REAL_MONEY = "PROHIBITED"

OUTCOMES_DEFAULT = Path("data/calibration_corpus/live_outcomes.jsonl")
SNAPSHOTS_DEFAULT = Path("data/calibration_corpus/forward_snapshots.jsonl")
ECE_READY_THRESHOLD = 0.10


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def ladder(n: int, ece: float | None = None) -> tuple[str, float]:
    if n == 0:
        return "NO_LIVE_EVIDENCE", 0.0
    if n < 10:
        return "WARMING_UP", 2.5
    if n < 30:
        return "PROVISIONAL", 5.0
    if n < 100:
        return "FIRST_PASS", 7.5
    if ece is not None and ece > ECE_READY_THRESHOLD:
        return "FIRST_PASS", 7.5
    return "READY", 10.0


def build_report(outcomes: list[dict[str, Any]],
                 snapshots: list[dict[str, Any]],
                 retrocast_status: dict[str, Any] | None = None
                 ) -> dict[str, Any]:
    live_outcomes = [o for o in outcomes if o.get("source_mode") == "LIVE"]
    live_snaps = [s for s in snapshots if s.get("source_mode") == "LIVE"]
    open_snaps = [s for s in live_snaps
                  if s.get("status", "OPEN") == "OPEN"
                  and s.get("outcome") in (None, "PENDING")]
    by_h: dict[int, list[dict[str, Any]]] = {}
    for o in live_outcomes:
        by_h.setdefault(int(o["horizon_days"]), []).append(o)
    hit_rate_by_horizon = {}
    mean_residual_by_horizon = {}
    for h, rows in sorted(by_h.items()):
        hit_rate_by_horizon[str(h)] = round(
            sum(r["hit"] for r in rows) / len(rows), 4)
        mean_residual_by_horizon[str(h)] = round(
            sum(r["residual_return"] for r in rows) / len(rows), 6)
    # edge-bucket hit rate (|edge| terciles) — only meaningful with data
    buckets: dict[str, list[int]] = {}
    for o in live_outcomes:
        e = abs(float(o.get("edge") or 0.0))
        b = "high" if e >= 0.10 else ("mid" if e >= 0.05 else "low")
        buckets.setdefault(b, []).append(int(o["hit"]))
    edge_bucket_hit_rate = {b: round(sum(v) / len(v), 4)
                            for b, v in buckets.items()}
    n = len(live_outcomes)
    ladder_status, ladder_score = ladder(n)
    return {
        "live_snapshot_count": len(live_snaps),
        "open_snapshot_count": len(open_snaps),
        "matured_outcome_count": n,
        "hit_rate_by_horizon": hit_rate_by_horizon,
        "mean_residual_by_horizon": mean_residual_by_horizon,
        "brier_score_if_probability_available": None,   # needs model probs
        "edge_bucket_hit_rate": edge_bucket_hit_rate,
        "category_match_vs_retrocast": (
            retrocast_status or {"note": "no measured retrocast categories"}),
        "calibration_status": ladder_status,
        "ladder_score": ladder_score,
        "advisory_status": ADVISORY_STATUS, "real_money": REAL_MONEY,
    }


def _main() -> int:
    ap = argparse.ArgumentParser(description="Live calibration report")
    ap.add_argument("--write", choices=("dry_run", "write"),
                    default="dry_run")
    args = ap.parse_args()
    retro = None
    p = Path("runtime/retrocast_category_status.json")
    if p.exists():
        retro = json.loads(p.read_text(encoding="utf-8")).get(
            "real_category_status")
    report = build_report(_rows(OUTCOMES_DEFAULT), _rows(SNAPSHOTS_DEFAULT),
                          retro)
    if args.write == "write":
        out = Path("runtime/live_calibration_report.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True),
                       encoding="utf-8")
        md = ["# Live calibration report", "",
              f"ladder: **{report['calibration_status']}** "
              f"(score {report['ladder_score']})",
              f"live snapshots: {report['live_snapshot_count']} · open: "
              f"{report['open_snapshot_count']} · matured outcomes: "
              f"{report['matured_outcome_count']}",
              f"hit rate by horizon: {report['hit_rate_by_horizon']}", "",
              f"{ADVISORY_STATUS} · real money: {REAL_MONEY}"]
        Path("runtime/live_calibration_report.md").write_text(
            "\n".join(md), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
