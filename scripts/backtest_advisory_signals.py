"""Walk-forward backtester for ADVISORY signals (Pass 4).

Evaluates historical advisory signals against later reference prices.
STRICTLY advisory-only: no order placement, no broker interface, no
position management — the only outputs are metrics and a report that a
human reads.

Inputs are signal samples (dicts):

    {"signal_id", "symbol", "t_decision", "t_outcome",
     "entry_price", "exit_price", "side" ("LONG"|"ABSTAIN"),
     "benchmark_entry", "benchmark_exit",  # optional
     "t_observed", "t_published"}          # optional, for the guard

Formulas (test-pinned against synthetic datasets with known answers):

    R_i        = (P_exit - P_entry) / P_entry
    R_i^net    = R_i - cost - slippage
    HitRate    = (1/N) Σ 1[R_i^net > 0]
    E[R]       = (1/N) Σ R_i^net
    Sharpe     = (mean(R^net) - r_f) / std(R^net)
    Sortino    = (mean(R^net) - r_f) / downside_std(R^net)
    MDD        = max_t (peak_t - equity_t) / peak_t   (compounded equity)

Walk-forward split is chronological only:

    Train [t0, t1] · Validation (t1, t2] · Test (t2, t3]

Shuffled time-series splits are structurally impossible here; every
sample is temporal-guard-validated first and rejects are reported, not
silently dropped. Every report embeds its assumptions — a backtest
without printed assumptions is an opinion.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import math
import statistics
from typing import Iterable

try:
    from scripts.temporal_guard import filter_evaluation_samples, parse_utc
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from temporal_guard import filter_evaluation_samples, parse_utc  # type: ignore[no-redef]

ADVISORY_STAMP = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_mode": "HUMAN_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
}


@dataclasses.dataclass(frozen=True)
class Assumptions:
    """Explicit, report-embedded assumptions. No hidden defaults."""

    transaction_cost: float = 0.001   # 10 bps per round trip side
    slippage: float = 0.0005          # 5 bps
    risk_free_rate_per_period: float = 0.0
    note: str = (
        "Reference prices are observation points, not fills. This system "
        "never trades; returns describe what the advisory signal pointed "
        "at, after assumed cost+slippage, had a HUMAN acted at those "
        "reference prices."
    )

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def net_return(entry: float, exit_: float, a: Assumptions) -> float:
    if entry <= 0:
        raise ValueError(f"entry_price must be positive, got {entry}")
    gross = (exit_ - entry) / entry
    return gross - a.transaction_cost - a.slippage


def max_drawdown(returns: list[float]) -> float:
    """MDD over compounded equity, as a positive fraction."""
    equity = 1.0
    peak = 1.0
    mdd = 0.0
    for r in returns:
        equity *= (1.0 + r)
        peak = max(peak, equity)
        if peak > 0:
            mdd = max(mdd, (peak - equity) / peak)
    return mdd


def _downside_std(returns: list[float], floor: float = 0.0) -> float:
    downside = [min(0.0, r - floor) for r in returns]
    return math.sqrt(sum(d * d for d in downside) / len(returns)) if returns else 0.0


def compute_metrics(net_returns: list[float], a: Assumptions) -> dict:
    """All headline metrics for one set of net returns."""
    n = len(net_returns)
    if n == 0:
        return {"n": 0, "warning": "no usable samples — no metrics claimed"}
    mean = statistics.fmean(net_returns)
    std = statistics.pstdev(net_returns) if n > 1 else 0.0
    dstd = _downside_std(net_returns)
    rf = a.risk_free_rate_per_period
    return {
        "n": n,
        "hit_rate": sum(1 for r in net_returns if r > 0) / n,
        "expectancy": mean,
        "sharpe": (mean - rf) / std if std > 0 else None,
        "sortino": (mean - rf) / dstd if dstd > 0 else None,
        "max_drawdown": max_drawdown(net_returns),
        "best": max(net_returns),
        "worst": min(net_returns),
        "small_sample_warning": n < 30,
    }


def walk_forward_split(
    samples: list[dict],
    t1: str | _dt.datetime,
    t2: str | _dt.datetime,
) -> dict:
    """Chronological train/validation/test partition on t_decision.

    Train: t_decision <= t1 · Validation: t1 < t_decision <= t2 ·
    Test: t_decision > t2. Raises if t1 >= t2 (a degenerate split is a
    bug, not a configuration).
    """
    b1 = parse_utc(t1, "t1")
    b2 = parse_utc(t2, "t2")
    if b1 is None or b2 is None or b1 >= b2:
        raise ValueError("walk-forward requires t1 < t2 (aware timestamps)")
    split: dict = {"train": [], "validation": [], "test": []}
    for s in sorted(samples, key=lambda x: str(x.get("t_decision", ""))):
        td = parse_utc(s.get("t_decision"), "t_decision")
        if td is None:
            continue
        if td <= b1:
            split["train"].append(s)
        elif td <= b2:
            split["validation"].append(s)
        else:
            split["test"].append(s)
    return split


def run_backtest(
    samples: Iterable[dict],
    *,
    assumptions: Assumptions | None = None,
    t1: str | _dt.datetime | None = None,
    t2: str | _dt.datetime | None = None,
    regime_key: str = "regime",
) -> dict:
    """Temporal-guard → walk-forward → metrics. Returns a full report dict.

    With t1/t2 the report carries per-split metrics and the headline
    block is the TEST split only — quoting train-period performance as
    "the result" is the lie this module exists to prevent. Without
    t1/t2 the whole set is reported as IN-SAMPLE, loudly.
    """
    a = assumptions or Assumptions()
    guard = filter_evaluation_samples(list(samples))
    usable = [s for s in guard["usable"] if s.get("side", "LONG") != "ABSTAIN"]
    abstained = [s for s in guard["usable"] if s.get("side", "LONG") == "ABSTAIN"]

    def _nets(rows: list[dict]) -> list[float]:
        out = []
        for s in rows:
            out.append(net_return(float(s["entry_price"]), float(s["exit_price"]), a))
        return out

    def _bench(rows: list[dict]) -> float | None:
        diffs = []
        for s in rows:
            be, bx = s.get("benchmark_entry"), s.get("benchmark_exit")
            if be and bx and float(be) > 0:
                bench_r = (float(bx) - float(be)) / float(be)
                diffs.append(net_return(float(s["entry_price"]), float(s["exit_price"]), a) - bench_r)
        return statistics.fmean(diffs) if diffs else None

    report: dict = {
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "assumptions": a.as_dict(),
        "samples_in": len(guard["usable"]) + len(guard["rejected"]),
        "samples_rejected_by_temporal_guard": len(guard["rejected"]),
        "rejection_reasons": [
            {"signal_id": s.get("signal_id"), "reasons": list(r)}
            for s, r in guard["rejected"]
        ][:50],
        "abstention_rate": (
            len(abstained) / len(guard["usable"]) if guard["usable"] else None
        ),
        **ADVISORY_STAMP,
    }

    if t1 is not None and t2 is not None:
        split = walk_forward_split(usable, t1, t2)
        report["walk_forward"] = {
            name: compute_metrics(_nets(rows), a) for name, rows in split.items()
        }
        for name, rows in split.items():
            excess = _bench(rows)
            if excess is not None:
                report["walk_forward"][name]["mean_excess_vs_benchmark"] = excess
        report["headline"] = report["walk_forward"]["test"]
        report["headline_basis"] = "out_of_sample_test_split"
        if report["walk_forward"]["test"].get("n", 0) == 0:
            report["headline_basis"] = "NO_TEST_SAMPLES — no out-of-sample claim possible"
    else:
        report["headline"] = compute_metrics(_nets(usable), a)
        report["headline_basis"] = (
            "IN_SAMPLE_ONLY — this is NOT out-of-sample evidence and must "
            "not be quoted as expected performance"
        )
        excess = _bench(usable)
        if excess is not None:
            report["headline"]["mean_excess_vs_benchmark"] = excess

    # Regime segmentation when samples are tagged.
    regimes: dict[str, list[dict]] = {}
    for s in usable:
        tag = str(s.get(regime_key, "")).strip()
        if tag:
            regimes.setdefault(tag, []).append(s)
    if regimes:
        report["regimes"] = {
            tag: compute_metrics(_nets(rows), a) for tag, rows in regimes.items()
        }
    return report
