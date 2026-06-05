"""Pure, deterministic statistical helpers used by parsers and scoring.

Every formula here mirrors the spec exactly.  No I/O, no randomness.
"""
from __future__ import annotations

import math

EPS = 1e-12


def elo_expected_white(delta_elo: float) -> float:
    """E_white = 1 / (1 + 10^(-ΔElo/400))."""
    return 1.0 / (1.0 + 10.0 ** (-float(delta_elo) / 400.0))


def brier_score(pairs: list[tuple[float, float]]) -> float | None:
    """Brier = (1/n) Σ (p_i - y_i)^2.  ``pairs`` = [(p, y), ...]."""
    if not pairs:
        return None
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs)


def log_loss(pairs: list[tuple[float, float]]) -> float | None:
    """LogLoss = -(1/n) Σ [y ln(p+ε) + (1-y) ln(1-p+ε)]."""
    if not pairs:
        return None
    total = 0.0
    for p, y in pairs:
        total += y * math.log(p + EPS) + (1 - y) * math.log(1 - p + EPS)
    return -total / len(pairs)


def expected_calibration_error(
    pairs: list[tuple[float, float]], bins: int = 10
) -> float | None:
    """ECE over M equal-width bins on [0,1]."""
    if not pairs:
        return None
    n = len(pairs)
    edges = [i / bins for i in range(bins + 1)]
    ece = 0.0
    for m in range(bins):
        lo, hi = edges[m], edges[m + 1]
        if m == bins - 1:
            members = [(p, y) for p, y in pairs if lo <= p <= hi]
        else:
            members = [(p, y) for p, y in pairs if lo <= p < hi]
        if not members:
            continue
        acc = sum(y for _, y in members) / len(members)
        conf = sum(p for p, _ in members) / len(members)
        ece += (len(members) / n) * abs(acc - conf)
    return ece


def reliability_decomposition(
    pairs: list[tuple[float, float]], bins: int = 10
) -> dict[str, float] | None:
    """Brier = REL - RES + UNC decomposition."""
    if not pairs:
        return None
    n = len(pairs)
    o_bar = sum(y for _, y in pairs) / n
    edges = [i / bins for i in range(bins + 1)]
    rel = 0.0
    res = 0.0
    for m in range(bins):
        lo, hi = edges[m], edges[m + 1]
        if m == bins - 1:
            members = [(p, y) for p, y in pairs if lo <= p <= hi]
        else:
            members = [(p, y) for p, y in pairs if lo <= p < hi]
        if not members:
            continue
        nm = len(members)
        p_m = sum(p for p, _ in members) / nm
        o_m = sum(y for _, y in members) / nm
        rel += (nm / n) * (p_m - o_m) ** 2
        res += (nm / n) * (o_m - o_bar) ** 2
    unc = o_bar * (1 - o_bar)
    return {
        "REL": rel,
        "RES": res,
        "UNC": unc,
        "BS_decomposed": rel - res + unc,
        "o_bar": o_bar,
    }


def shannon_diversity(source_counts: dict[str, int]) -> dict[str, float]:
    """Shannon entropy + normalized diversity D = H / log(K)."""
    n = sum(source_counts.values())
    k = len([c for c in source_counts.values() if c > 0])
    if n == 0 or k <= 1:
        return {"entropy": 0.0, "normalized_diversity": 0.0, "unique_sources": k}
    h = 0.0
    for c in source_counts.values():
        if c <= 0:
            continue
        p = c / n
        h -= p * math.log(p)
    d = h / math.log(k)
    return {"entropy": h, "normalized_diversity": d, "unique_sources": k}


def duplicate_ratio(total_documents: int, duplicate_count: int) -> float:
    """duplicate_count / max(total_documents, 1)."""
    return duplicate_count / max(total_documents, 1)


def saturating_volume_score(n_records: int, tau: float = 1000.0) -> float:
    """100 * (1 - exp(-N/τ))."""
    return 100.0 * (1.0 - math.exp(-max(0, n_records) / tau))


# --- Market metrics (only invoked when valid market data exists) -----------


def simple_returns(prices: list[float]) -> list[float]:
    out = []
    for i in range(1, len(prices)):
        prev = prices[i - 1]
        if prev == 0:
            out.append(0.0)
        else:
            out.append((prices[i] - prev) / prev)
    return out


def cumulative_return(strategy_returns: list[float]) -> float:
    eq = 1.0
    for r in strategy_returns:
        eq *= (1.0 + r)
    return eq - 1.0


def sharpe_ratio(
    strategy_returns: list[float], rf: float = 0.0, periods: int | None = None
) -> float | None:
    if len(strategy_returns) < 2:
        return None
    excess = [r - rf for r in strategy_returns]
    mean = sum(excess) / len(excess)
    var = sum((x - mean) ** 2 for x in excess) / (len(excess) - 1)
    sd = math.sqrt(var)
    if sd < EPS:
        return None
    n = periods if periods is not None else len(strategy_returns)
    return (mean / sd) * math.sqrt(n)


def max_drawdown(strategy_returns: list[float]) -> float | None:
    if not strategy_returns:
        return None
    eq = 1.0
    peak = 1.0
    mdd = 0.0
    for r in strategy_returns:
        eq *= (1.0 + r)
        peak = max(peak, eq)
        dd = eq / peak - 1.0
        mdd = min(mdd, dd)
    return mdd


def win_rate(wins: int, total_closed: int) -> float:
    return wins / max(total_closed, 1)


def profit_factor(gross_profit: float, gross_loss: float) -> float:
    return gross_profit / max(abs(gross_loss), EPS)


__all__ = [
    "EPS",
    "elo_expected_white",
    "brier_score",
    "log_loss",
    "expected_calibration_error",
    "reliability_decomposition",
    "shannon_diversity",
    "duplicate_ratio",
    "saturating_volume_score",
    "simple_returns",
    "cumulative_return",
    "sharpe_ratio",
    "max_drawdown",
    "win_rate",
    "profit_factor",
]
