"""Quant sprint — real-data readiness dashboard + sample-size gates.

One honest surface answering: does Sleeping Passenger currently hold
enough REAL observations to run each experiment?  No experimental module
may quietly act calibrated while its dataset is underpowered.

Sample-size gates (documented heuristics, per-test rationale, UNCALIBRATED):

    N == 0                   BLOCKED_BY_DATA
    0 < N < 20               INSUFFICIENT     (a sign check at N=20 still
                             has ±22pp s.e. on hit rate — direction only)
    20 <= N < 80             EXPLORATORY_ONLY (t-test power ~0.8 only for
                             effects >= ~0.6 sd; quantile tests unstable)
    N >= 80                  TESTABLE         (5-quantile study with >=16
                             per bucket; detects ~0.3 sd effects)

Writes reports/real_data_readiness_<date>.{json,md}.  RESEARCH_ONLY.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
import sys
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.prediction_market_series_builder import ledger_coverage, load_ledger
from scripts.quant_peg_dataset_builder import FROZEN_DIR, real_peg_census

BLOCKED_BY_DATA = "BLOCKED_BY_DATA"
INSUFFICIENT = "INSUFFICIENT"
EXPLORATORY_ONLY = "EXPLORATORY_ONLY"
TESTABLE = "TESTABLE"
# Depth annotation (not a gate): longitudinal collection has BEGUN but
# per-contract depth is still below every experiment's floor.
EARLY_LONGITUDINAL = "EARLY_LONGITUDINAL"

N_EXPLORATORY = 20
N_VALIDATION = 80


def gate(n: int, *, n_exploratory: int = N_EXPLORATORY,
         n_validation: int = N_VALIDATION) -> str:
    if n <= 0:
        return BLOCKED_BY_DATA
    if n < n_exploratory:
        return INSUFFICIENT
    if n < n_validation:
        return EXPLORATORY_ONLY
    return TESTABLE


def build_readiness(*, ledger_rows: list[dict[str, Any]] | None = None,
                    peg_census: dict[str, Any] | None = None,
                    frozen_dir: Path = FROZEN_DIR) -> dict[str, Any]:
    cov = ledger_coverage(ledger_rows if ledger_rows is not None
                          else load_ledger())
    peg = peg_census if peg_census is not None else real_peg_census()
    frozen_versions = (len(sorted(frozen_dir.glob("event_equity_map_v*.json")))
                       if frozen_dir.exists() else 0)
    n_peg_5d = peg["n_matured_by_horizon"].get(5, 0)
    hops = peg.get("hop_distribution", {})
    filing = peg.get("filing_confirmation_distribution", {})
    n_hop2plus = sum(v for k, v in hops.items()
                     if k not in ("0", "1", "None"))
    n_filing_strong = filing.get("STRONG", 0)

    experiments = {
        "peg_forward_ar": {
            "question": "does high PEG predict forward abnormal return?",
            "n": n_peg_5d, "n_unit": "matured 5d LIVE PEG observations",
            "status": gate(n_peg_5d)},
        "probability_dynamics": {
            "question": "are dP/dt / d2P/dt2 informative?",
            "n": cov["markets_ge_7_days"],
            "n_unit": "markets with >=7 daily observations",
            "status": gate(cov["markets_ge_7_days"]),
            "depth_note": (
                f"{EARLY_LONGITUDINAL}: {cov['markets_ge_2_days']} "
                "contracts have 2-day depth (ΔP/velocity only); "
                "acceleration needs 3, Z-shock needs 10"
                if cov["markets_ge_2_days"] > 0
                and cov["markets_ge_7_days"] == 0 else None)},
        "cross_venue_divergence": {
            "question": "does CES-matched divergence carry information?",
            "n": 0, "n_unit": "matched multi-day Kalshi x Polymarket pairs",
            "status": BLOCKED_BY_DATA,
            "note": "requires multi-day series on BOTH venues + CES match"},
        "hop_lag_wave": {
            "question": "do hop-2+ names reprice later than hop-0/1?",
            "n": n_hop2plus, "n_unit": "matured hop>=2 LIVE observations",
            "status": gate(n_hop2plus)},
        "filing_confirmation": {
            "question": "does STRONG filing confirmation outperform "
                        "narrative-only exposure?",
            "n": n_filing_strong,
            "n_unit": "matured STRONG-filing LIVE observations",
            "status": gate(n_filing_strong)},
        "threshold_titration": {
            "question": "does sensitivity rise near inferred transitions?",
            "n": 0, "n_unit": "persisted titration time-series days",
            "status": BLOCKED_BY_DATA,
            "note": "capture begins once operator activates watch events "
                    "with evidence feeds"},
        "halflife": {
            "question": "how fast does probability-shock predictiveness "
                        "decay?",
            "n": n_peg_5d, "n_unit": "matured PEG observations "
                                     "(same corpus, horizon ladder)",
            "status": gate(n_peg_5d)},
    }
    return {
        "prediction_market_coverage": cov,
        "frozen_exposure_map_versions": frozen_versions,
        "real_peg": peg,
        "experiments": experiments,
        "gates": {"n_exploratory": N_EXPLORATORY,
                  "n_validation": N_VALIDATION,
                  "rationale": "documented heuristics — see module "
                               "docstring; UNCALIBRATED"},
        "signal_class": "RESEARCH_ONLY",
        "advisory_status": "ADVISORY_ONLY",
    }


def write_report(readiness: dict[str, Any], *, run_date: str,
                 out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    jp = out_dir / f"real_data_readiness_{run_date}.json"
    jp.write_text(json.dumps(readiness, indent=2, default=str),
                  encoding="utf-8")
    cov = readiness["prediction_market_coverage"]
    peg = readiness["real_peg"]
    lines = [f"# Real Data Readiness — {run_date}", "",
             "RESEARCH_ONLY. Gates: BLOCKED_BY_DATA / INSUFFICIENT(<20) / "
             "EXPLORATORY_ONLY(<80) / TESTABLE(>=80).", "",
             "## Prediction-market temporal depth", "",
             f"- Observations: {cov['total_observations']} raw rows across "
             f"{cov['distinct_markets']} contracts on "
             f"{cov['distinct_days']} distinct days "
             f"({cov['first_day']} → {cov['last_day']}, "
             f"{cov['elapsed_calendar_days']} elapsed calendar days)",
             f"- Contracts by depth: ≥2 days: {cov['markets_ge_2_days']} | "
             f"≥3: {cov['markets_ge_3_days']} | "
             f"≥7: {cov['markets_ge_7_days']} | "
             f"≥14: {cov['markets_ge_14_days']} | "
             f"≥21: {cov['markets_ge_21_days']}",
             f"- Max depth: {cov['max_depth_days']} days | median: "
             f"{cov['median_depth_days']} day(s)",
             f"- Feature capability: {cov['feature_capability_counts']}",
             f"- Per venue: {cov['per_venue']}",
             "", "## Event → equity / PEG", "",
             f"- Frozen exposure-map versions: "
             f"{readiness['frozen_exposure_map_versions']}",
             f"- Real PEG observations (LIVE): "
             f"{peg['n_live_observations']}",
             f"- Horizon maturity (matured LIVE ARs): "
             f"{peg['n_matured_by_horizon']}",
             f"- Hop distribution: {peg['hop_distribution']} | filing "
             f"confirmation: {peg['filing_confirmation_distribution']}",
             "", "| Experiment | N | Unit | Status |",
             "|---|--:|---|---|"]
    for name, e in readiness["experiments"].items():
        note = f" _{e['depth_note']}_" if e.get("depth_note") else ""
        lines.append(f"| {name} | {e['n']} | {e['n_unit']} | "
                     f"**{e['status']}**{note} |")
    mp = out_dir / f"real_data_readiness_{run_date}.md"
    mp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": jp, "md": mp}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-date", default=date.today().isoformat())
    ap.add_argument("--out-dir", default=str(_REPO / "reports"))
    args = ap.parse_args(argv)
    readiness = build_readiness()
    paths = write_report(readiness, run_date=args.run_date,
                         out_dir=Path(args.out_dir))
    statuses = {k: v["status"] for k, v in readiness["experiments"].items()}
    print(json.dumps(statuses, indent=2))
    print(f"report: {paths['md']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
