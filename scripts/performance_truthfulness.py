"""Sample-size-gated performance metrics that refuse to fabricate.

The dashboard already suppresses win-rate and calibration below threshold
(``score_calibration``: win_rate is None at n=0; sizing blocked below n=50).
This module extends the same honesty discipline to the remaining headline
performance metrics — Sharpe, Sortino, max drawdown — and gives every emitted
metric an explicit **finite display state**, a **provenance_type**, a
**sample_size**, and a **mode**, so a number can never appear on the dashboard
without saying where it came from and how much evidence backs it.

Core rule: when there is not enough evidence, return ``INSUFFICIENT_SAMPLE`` or
``NO_DATA`` with ``value = None`` — never a fabricated figure, never a
synthetic-only edge dressed up as live.

Pure module: no DB, no network, no broker calls.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Optional, Sequence

# Finite display states (Phase 7 — no infinite spinner allowed).
IDLE = "IDLE"
LOADING = "LOADING"
SUCCESS = "SUCCESS"
EMPTY = "EMPTY"
ERROR = "ERROR"
STALE = "STALE"
NO_DATA = "NO_DATA"
INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
DISPLAY_STATES: frozenset[str] = frozenset(
    {IDLE, LOADING, SUCCESS, EMPTY, ERROR, STALE, NO_DATA, INSUFFICIENT_SAMPLE}
)

# Sample-size gates (Phase 7).  Raising the bar, never lowering it.
WIN_RATE_MIN_N = 10
SHARPE_MIN_N = 30
SORTINO_MIN_N = 30
SORTINO_MIN_DOWNSIDE = 5
DRAWDOWN_MIN_POINTS = 10
CALIBRATION_MIN_N = 30

# Provenance vocabulary a displayed metric may carry.
_VALID_PROVENANCE = frozenset(
    {
        "LIVE_MANUAL", "PAPER", "IMPORTED_BACKTEST", "SYNTHETIC",
        "RUNTIME_DB", "NO_DATA",
    }
)


@dataclass(slots=True)
class GatedMetric:
    name: str
    value: Optional[float]
    status: str  # one of DISPLAY_STATES (SUCCESS/INSUFFICIENT_SAMPLE/NO_DATA)
    provenance_type: str
    sample_size: int
    mode: str
    expected_min_n: int
    note: str = ""

    def __post_init__(self) -> None:
        if self.status not in DISPLAY_STATES:
            raise ValueError(f"status must be a finite display state, got {self.status!r}")
        if self.provenance_type not in _VALID_PROVENANCE:
            raise ValueError(f"bad provenance_type {self.provenance_type!r}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _gate(
    name: str,
    value: Optional[float],
    n: int,
    min_n: int,
    *,
    provenance_type: str,
    mode: str,
    extra_ok: bool = True,
    note: str = "",
) -> GatedMetric:
    if n <= 0:
        return GatedMetric(name, None, NO_DATA, "NO_DATA", n, mode, min_n,
                           note or "no samples")
    if n < min_n or not extra_ok or value is None:
        return GatedMetric(name, None, INSUFFICIENT_SAMPLE, provenance_type, n, mode,
                           min_n, note or f"need n>={min_n}")
    return GatedMetric(name, round(float(value), 6), SUCCESS, provenance_type, n, mode,
                       min_n, note)


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _stdev(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    var = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return math.sqrt(var)


def win_rate(labels: Sequence[str], *, provenance_type: str, mode: str) -> GatedMetric:
    """Win rate over resolved labels; suppressed below WIN_RATE_MIN_N."""
    resolved = [str(s).upper() for s in labels if str(s).upper() in {"WIN", "LOSS", "BREAKEVEN"}]
    n = len(resolved)
    wins = sum(1 for s in resolved if s == "WIN")
    value = (wins / n) if n else None
    return _gate("win_rate", value, n, WIN_RATE_MIN_N,
                 provenance_type=provenance_type, mode=mode)


def sharpe_ratio(returns: Sequence[float], *, provenance_type: str, mode: str,
                 risk_free: float = 0.0) -> GatedMetric:
    """Sharpe = mean(excess)/stdev(excess); suppressed below SHARPE_MIN_N."""
    rs = [float(r) for r in returns]
    n = len(rs)
    sd = _stdev([r - risk_free for r in rs])
    value = (_mean([r - risk_free for r in rs]) / sd) if (n >= SHARPE_MIN_N and sd > 0) else None
    return _gate("sharpe_ratio", value, n, SHARPE_MIN_N,
                 provenance_type=provenance_type, mode=mode,
                 extra_ok=(sd > 0), note="" if sd > 0 else "zero variance")


def sortino_ratio(returns: Sequence[float], *, provenance_type: str, mode: str,
                  target: float = 0.0) -> GatedMetric:
    """Sortino = mean(excess)/downside_dev; needs N and >=5 downside points."""
    rs = [float(r) for r in returns]
    n = len(rs)
    downside = [min(0.0, r - target) for r in rs]
    downside_count = sum(1 for d in downside if d < 0)
    dd = math.sqrt(sum(d * d for d in downside) / n) if n else 0.0
    enough = n >= SORTINO_MIN_N and downside_count >= SORTINO_MIN_DOWNSIDE and dd > 0
    value = (_mean([r - target for r in rs]) / dd) if enough else None
    return _gate("sortino_ratio", value, n, SORTINO_MIN_N,
                 provenance_type=provenance_type, mode=mode,
                 extra_ok=enough, note=f"downside_count={downside_count}")


def max_drawdown(equity_curve: Sequence[float], *, provenance_type: str, mode: str) -> GatedMetric:
    """Max drawdown of an equity curve; suppressed below DRAWDOWN_MIN_POINTS."""
    pts = [float(x) for x in equity_curve]
    n = len(pts)
    value = None
    if n >= DRAWDOWN_MIN_POINTS:
        peak = pts[0]
        worst = 0.0
        for x in pts:
            peak = max(peak, x)
            if peak > 0:
                worst = min(worst, (x - peak) / peak)
        value = worst
    return _gate("max_drawdown", value, n, DRAWDOWN_MIN_POINTS,
                 provenance_type=provenance_type, mode=mode)


def calibration_availability(n_eligible: int, *, provenance_type: str, mode: str) -> GatedMetric:
    """Whether calibration may be shown at all (needs CALIBRATION_MIN_N)."""
    value = 1.0 if n_eligible >= CALIBRATION_MIN_N else None
    return _gate("calibration_available", value, n_eligible, CALIBRATION_MIN_N,
                 provenance_type=provenance_type, mode=mode)


def build_performance_panel(
    *,
    labels: Sequence[str],
    returns: Sequence[float],
    equity_curve: Sequence[float],
    n_calibration_eligible: int,
    provenance_type: str,
    mode: str,
) -> dict[str, Any]:
    """A full panel of gated metrics for one provenance/mode.

    Every metric carries its provenance, sample size, and finite state.  If
    there are no real outcomes the panel is honest NO_DATA/INSUFFICIENT_SAMPLE
    rather than fabricated numbers — and ``mode`` makes synthetic/paper panels
    impossible to mistake for live.
    """
    metrics = [
        win_rate(labels, provenance_type=provenance_type, mode=mode),
        sharpe_ratio(returns, provenance_type=provenance_type, mode=mode),
        sortino_ratio(returns, provenance_type=provenance_type, mode=mode),
        max_drawdown(equity_curve, provenance_type=provenance_type, mode=mode),
        calibration_availability(n_calibration_eligible, provenance_type=provenance_type, mode=mode),
    ]
    return {
        "mode": mode,
        "provenance_type": provenance_type,
        "metrics": [m.to_dict() for m in metrics],
        "any_displayable": any(m.status == SUCCESS for m in metrics),
        "advisory_only": True,
    }


__all__ = [
    "DISPLAY_STATES", "GatedMetric",
    "WIN_RATE_MIN_N", "SHARPE_MIN_N", "SORTINO_MIN_N", "SORTINO_MIN_DOWNSIDE",
    "DRAWDOWN_MIN_POINTS", "CALIBRATION_MIN_N",
    "win_rate", "sharpe_ratio", "sortino_ratio", "max_drawdown",
    "calibration_availability", "build_performance_panel",
]
