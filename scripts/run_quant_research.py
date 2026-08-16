"""Quant hackathon — research experiment runner.

Runs every experiment the AVAILABLE data supports, records each in the
append-only research ledger, and writes a human-readable report.  It
never fabricates observations: an experiment without sufficient real
data is recorded as BLOCKED_BY_DATA with the exact N found.

Experiments:
  E1  PM settlement calibration      REAL (pm_settlements.jsonl)
  E2  Cross-asset lead-lag           REAL (signal_events daily closes)
  E3  Momentum signal-decay ladder   REAL (baseline control, mission 31/33)
  E4  PEG quantile study             FIXTURE_DEMONSTRATION (retrocast) +
                                     honest real-N statement

RESEARCH_ONLY.  Read-only over canonical data; writes only the ledger
and reports/.  No broker, no execution.
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

from scripts.quant_lead_lag_engine import lead_lag_study
from scripts.quant_peg_research_engine import (
    build_peg_dataset,
    load_retrocast_corpus,
    peg_experiment,
)
from scripts.quant_research_ledger import (
    ACCEPTED,
    BLOCKED_BY_DATA,
    INCONCLUSIVE,
    REJECTED,
    record_experiment,
)
from scripts.quant_return_engine import load_close_series, log_return
from scripts.quant_statistics_engine import (
    OK,
    benjamini_hochberg,
    brier_score,
    information_coefficient,
    log_loss,
    reliability_buckets,
)

DB_PATH = _REPO / "runtime" / "mvp_local.db"
CORPUS = _REPO / "data" / "calibration_corpus"
RESEARCH_ONLY = "RESEARCH_ONLY"

# Lead-lag pairs: a small PRE-REGISTERED hypothesis family (mission 27 —
# declared up front so BH-FDR covers the whole family, no cherry-picking).
LEAD_LAG_PAIRS = [
    ("GLD", "TLT"), ("TLT", "GLD"), ("NVDA", "SPY"), ("SPY", "NVDA"),
    ("BTC-USD", "NVDA"), ("SPY", "AAPL"), ("TSLA", "SPY"), ("MSFT", "SPY"),
]
MOM_LOOKBACK = 5
DECAY_HORIZONS = (1, 3, 5, 10, 20)


def _returns(series: dict[str, float]) -> tuple[list[str], list[float]]:
    days = sorted(series)
    dates, rets = [], []
    for a, b in zip(days, days[1:]):
        r = log_return(series, a, b)
        if r is not None:
            dates.append(b)
            rets.append(r)
    return dates, rets


def e1_pm_calibration(run_date: str) -> dict[str, Any]:
    path = CORPUS / "pm_settlements.jsonl"
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("p") is not None and r.get("y") is not None:
                    rows.append(r)
    ps = [float(r["p"]) for r in rows]
    ys = [int(r["y"]) for r in rows]
    result: dict[str, Any] = {"n": len(rows), "source": str(path)}
    if len(rows) >= 10:
        result["brier"] = brier_score(ps, ys)
        result["log_loss"] = log_loss(ps, ys)
        result["reliability"] = reliability_buckets(ps, ys)
        skill = result["brier"].get("skill_vs_constant")
        verdict = ACCEPTED if (skill is not None and skill > 0) else REJECTED
        conclusion = (
            f"Kalshi settlement prices beat the constant-base-rate baseline "
            f"by {skill:.4f} Brier points (N={len(rows)})" if skill and skill > 0
            else f"no Brier skill vs constant baseline (N={len(rows)})")
    else:
        verdict, conclusion = BLOCKED_BY_DATA, f"only {len(rows)} settlements"
    record_experiment(
        experiment_id="E1_pm_settlement_calibration",
        hypothesis="Kalshi last prices are calibrated probabilities that "
                   "beat a constant base-rate forecast (Brier skill > 0)",
        data_range="2026-07-02 observations, settled by 2026-07-17",
        features=["p"], target="y", config={"n_min": 10},
        result={k: v for k, v in result.items() if k != "reliability"},
        n=len(rows), conclusion=conclusion, verdict=verdict,
        run_date=run_date)
    return {"verdict": verdict, "conclusion": conclusion, **result}


def e2_lead_lag(run_date: str) -> dict[str, Any]:
    closes = load_close_series(DB_PATH, min_days=40)
    studies = []
    pvals = []
    for a, b in LEAD_LAG_PAIRS:
        if a not in closes or b not in closes:
            studies.append({"pair": f"{a}->{b}", "verdict": BLOCKED_BY_DATA})
            continue
        da, ra = _returns(closes[a])
        db_, rb = _returns(closes[b])
        common = sorted(set(da) & set(db_))
        xa = [ra[da.index(d)] for d in common]
        yb = [rb[db_.index(d)] for d in common]
        st = lead_lag_study(xa, yb, label_x=a, label_y=b)
        studies.append(st)
        cc = st.get("cross_correlation", {})
        if cc.get("status") == OK:
            pvals.append(cc["best_p_value"])
    fdr = benjamini_hochberg(pvals) if pvals else {"status": "EMPTY"}
    n_predictive = sum(1 for s in studies if s.get("verdict") == "PREDICTIVE")
    conclusion = (
        f"{n_predictive}/{len(studies)} pre-registered pairs show "
        f"out-of-sample predictive lead; {fdr.get('n_survive', 0)} of "
        f"{fdr.get('m', 0)} correlation peaks survive BH-FDR at 5%")
    verdict = ACCEPTED if n_predictive else REJECTED
    record_experiment(
        experiment_id="E2_cross_asset_lead_lag",
        hypothesis="Some pre-registered daily cross-asset return pairs "
                   "exhibit OOS-predictive lead-lag structure",
        data_range="signal_events daily bars ~1980..2026 (historical OHLCV backfill + live snapshots)",
        features=["lagged returns"], target="next-day return",
        config={"pairs": [f"{a}->{b}" for a, b in LEAD_LAG_PAIRS],
                "max_lag": 5},
        result={"n_predictive": n_predictive, "fdr": fdr},
        n=len(studies), conclusion=conclusion, verdict=verdict,
        run_date=run_date)
    return {"verdict": verdict, "conclusion": conclusion,
            "studies": studies, "fdr": fdr}


def e3_momentum_decay(run_date: str) -> dict[str, Any]:
    """Baseline control: does trailing 5-bar momentum predict forward
    market-adjusted return at any horizon (pooled cross-section)?"""
    closes = load_close_series(DB_PATH, min_days=60)
    bench = closes.get("SPY")
    if not bench:
        verdict, conclusion = BLOCKED_BY_DATA, "no SPY benchmark series"
        record_experiment(
            experiment_id="E3_momentum_decay", hypothesis="momentum IC(h)",
            data_range="n/a", features=["MOM"], target="AR",
            config={}, result={}, n=0, conclusion=conclusion,
            verdict=verdict, run_date=run_date)
        return {"verdict": verdict, "conclusion": conclusion}
    ladder: dict[int, dict[str, list[float]]] = {
        h: {"sig": [], "fwd": []} for h in DECAY_HORIZONS}
    for sym, series in closes.items():
        if sym == "SPY":
            continue
        days = sorted(series)
        for i in range(MOM_LOOKBACK, len(days) - max(DECAY_HORIZONS)):
            t = days[i]
            mom = log_return(series, days[i - MOM_LOOKBACK], t)
            if mom is None:
                continue
            for h in DECAY_HORIZONS:
                exit_day = days[i + h]
                ri = log_return(series, t, exit_day)
                rm = log_return(bench, t, exit_day)
                if ri is None or rm is None:
                    continue
                ladder[h]["sig"].append(mom)
                ladder[h]["fwd"].append(ri - rm)
    curve = {}
    for h in DECAY_HORIZONS:
        curve[h] = information_coefficient(
            ladder[h]["sig"], ladder[h]["fwd"], n_min=30)
    usable = {h: c for h, c in curve.items() if c["status"] == OK}
    sig_h = {h: c for h, c in usable.items() if abs(c["rank_ic"] or 0) > 0.05}
    conclusion = (
        "momentum rank-IC by horizon: "
        + ", ".join(f"h={h}: {c['rank_ic']:.3f} (N={c['n']})"
                    for h, c in usable.items())) if usable else "no usable data"
    verdict = INCONCLUSIVE if usable else BLOCKED_BY_DATA
    record_experiment(
        experiment_id="E3_momentum_decay",
        hypothesis="Trailing 5-bar momentum predicts forward "
                   "market-adjusted returns (baseline control, mission 31)",
        data_range="daily bars ~1980..2026 pooled cross-section (historical OHLCV backfill)",
        features=["MOM_5"], target="AR_h",
        config={"horizons": list(DECAY_HORIZONS)},
        result={str(h): {"rank_ic": c.get("rank_ic"), "n": c.get("n")}
                for h, c in curve.items()},
        n=sum(c.get("n", 0) for c in curve.values()),
        conclusion=conclusion, verdict=verdict, run_date=run_date)
    return {"verdict": verdict, "conclusion": conclusion, "curve": curve,
            "notable_horizons": sorted(sig_h)}


def e4_peg(run_date: str) -> dict[str, Any]:
    corpus = load_retrocast_corpus(CORPUS / "retrocast.jsonl")
    n_real = corpus.get("n_real", 0)
    result: dict[str, Any] = {"n_real": n_real,
                              "n_fixture": corpus.get("n_fixture", 0)}
    if n_real >= 8:
        samples = build_peg_dataset(corpus["real"])
        result["real_experiment"] = peg_experiment(samples)
        verdict = INCONCLUSIVE
        conclusion = f"real PEG experiment ran with N={n_real}"
    else:
        verdict = BLOCKED_BY_DATA
        conclusion = (f"REAL propagation-gap observations: N={n_real} — "
                      "no real PEG alpha claim is possible; machinery "
                      "demonstrated on fixture rows only")
        if corpus.get("n_fixture", 0) >= 8:
            samples = build_peg_dataset(corpus["fixture"])
            result["fixture_demonstration"] = peg_experiment(samples)
    record_experiment(
        experiment_id="E4_peg_quantile_study",
        hypothesis="High PEG (probability moved, price did not) predicts "
                   "positive forward abnormal return",
        data_range="data/calibration_corpus/retrocast.jsonl",
        features=["PEG", "delta_p"], target="fwd_return_{1,5,21}",
        config={"beta": 1.0, "exposure": "HEURISTIC_DEFAULT_1.0"},
        result={"n_real": n_real, "n_fixture": corpus.get("n_fixture", 0)},
        n=n_real, conclusion=conclusion, verdict=verdict,
        run_date=run_date)
    return {"verdict": verdict, "conclusion": conclusion, **result}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-date", default=date.today().isoformat())
    ap.add_argument("--out-dir", default=str(_REPO / "reports"))
    args = ap.parse_args(argv)

    results = {
        "run_date": args.run_date, "signal_class": RESEARCH_ONLY,
        "E1_pm_calibration": e1_pm_calibration(args.run_date),
        "E2_lead_lag": e2_lead_lag(args.run_date),
        "E3_momentum_decay": e3_momentum_decay(args.run_date),
        "E4_peg": e4_peg(args.run_date),
    }
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    jp = out / f"quant_research_report_{args.run_date}.json"
    jp.write_text(json.dumps(results, indent=2, default=str),
                  encoding="utf-8")
    lines = [f"# Quant Research Report — {args.run_date}",
             "", "RESEARCH_ONLY — no experiment output may feed a trade "
             "decision.", ""]
    for key in ("E1_pm_calibration", "E2_lead_lag", "E3_momentum_decay",
                "E4_peg"):
        r = results[key]
        lines += [f"## {key}", f"- verdict: **{r['verdict']}**",
                  f"- {r['conclusion']}", ""]
    (out / f"quant_research_report_{args.run_date}.md").write_text(
        "\n".join(lines), encoding="utf-8")
    print(json.dumps({k: results[k]["verdict"] for k in results
                      if k.startswith("E")}, indent=2))
    print(f"report: {jp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
