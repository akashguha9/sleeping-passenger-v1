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


def sortino_ratio(
    strategy_returns: list[float], mar: float = 0.0, periods: int | None = None
) -> float | None:
    """Sortino = sqrt(N) * mean(sr - MAR) / downside_deviation."""
    if not strategy_returns:
        return None
    excess = [r - mar for r in strategy_returns]
    mean = sum(excess) / len(excess)
    downside = [min(0.0, x) for x in excess]
    dd = math.sqrt(sum(x * x for x in downside) / len(downside))
    if dd < EPS:
        return None
    n = periods if periods is not None else len(strategy_returns)
    return (mean / dd) * math.sqrt(n)


# --- Sprint 2: calibration / abstention / bootstrap ------------------------ #
def max_calibration_error(
    pairs: list[tuple[float, float]], bins: int = 10
) -> float | None:
    """MCE = max_m |acc(B_m) - conf(B_m)|."""
    if not pairs:
        return None
    edges = [i / bins for i in range(bins + 1)]
    worst = 0.0
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
        worst = max(worst, abs(acc - conf))
    return worst


def abstention_grid(
    pairs: list[tuple[float, float]],
    thresholds: list[float] | None = None,
    *,
    alpha: float = 0.5,
    beta: float = 2.0,
) -> list[dict[str, float]]:
    """Abstention/decision-quality grid over confidence thresholds.

    A prediction p acts iff ``max(p, 1-p) >= τ``; it is "correct" iff the
    rounded class matches y.  Returns one row per threshold with coverage,
    accuracy, abstention, high-confidence-failure rate, and DQS.
    """
    if thresholds is None:
        thresholds = [round(0.50 + 0.05 * i, 2) for i in range(10)]  # .50..0.95
    n = len(pairs)
    rows: list[dict[str, float]] = []
    for tau in thresholds:
        acted = correct = high_conf_wrong = 0
        for p, y in pairs:
            conf = max(p, 1 - p)
            if conf >= tau:
                acted += 1
                pred = 1.0 if p >= 0.5 else 0.0
                if pred == y:
                    correct += 1
                else:
                    high_conf_wrong += 1
        coverage = acted / max(n, 1)
        accuracy = correct / max(acted, 1)
        hcfr = high_conf_wrong / max(acted, 1)
        dqs = accuracy * (coverage ** alpha) * ((1 - hcfr) ** beta)
        rows.append(
            {
                "threshold": tau,
                "coverage": coverage,
                "accuracy": accuracy,
                "abstention": 1 - coverage,
                "hcfr": hcfr,
                "dqs": dqs,
            }
        )
    return rows


def best_decision_threshold(grid: list[dict[str, float]]) -> dict[str, float] | None:
    """τ* = argmax_τ DQS(τ).  Deterministic tie-break: lowest threshold."""
    if not grid:
        return None
    return max(grid, key=lambda r: (r["dqs"], -r["threshold"]))


def _quantile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def bootstrap_ci(
    values: list[float],
    statistic,
    *,
    samples: int = 1000,
    seed: int = 42,
    min_n: int = 30,
    ci: float = 0.95,
) -> dict[str, object]:
    """Percentile bootstrap CI for ``statistic`` over ``values``.

    Deterministic given ``seed``.  Returns NO_DATA_INSUFFICIENT_N when
    ``len(values) < min_n``.
    """
    import random

    n = len(values)
    if n < min_n:
        return {"status": "NO_DATA_INSUFFICIENT_N", "n": n, "min_n": min_n}
    rng = random.Random(seed)
    stats: list[float] = []
    for _ in range(samples):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        try:
            stats.append(float(statistic(sample)))
        except (ValueError, ZeroDivisionError, TypeError):
            continue
    if not stats:
        return {"status": "NO_DATA", "n": n}
    stats.sort()
    lo = (1 - ci) / 2
    hi = 1 - lo
    return {
        "status": "OK",
        "n": n,
        "samples": len(stats),
        "point": round(float(statistic(values)), 6),
        "ci_low": round(_quantile(stats, lo), 6),
        "ci_high": round(_quantile(stats, hi), 6),
        "ci_level": ci,
        "seed": seed,
    }


def walk_forward_split(
    n: int, train: float = 0.70, validation: float = 0.15
) -> dict[str, tuple[int, int]]:
    """Chronological 70/15/15 split index ranges (no shuffling)."""
    t_end = int(n * train)
    v_end = int(n * (train + validation))
    return {
        "train": (0, t_end),
        "validation": (t_end, v_end),
        "test": (v_end, n),
    }


def token_similarity(a: str, b: str) -> float:
    """Lightweight normalized similarity: 1.0 exact (lowercased), else a
    token Jaccard over non-alnum splits.  Cheap, dependency-free."""
    a1 = a.strip().lower()
    b1 = b.strip().lower()
    if a1 == b1:
        return 1.0
    import re as _re

    ta = set(_re.split(r"[^a-z0-9]+", a1)) - {""}
    tb = set(_re.split(r"[^a-z0-9]+", b1)) - {""}
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    base = inter / union
    # Substring bonus so "adj_close" ~ "close" scores high.
    if a1 in b1 or b1 in a1:
        base = max(base, 0.85)
    return base


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
    "sortino_ratio",
    "max_calibration_error",
    "abstention_grid",
    "best_decision_threshold",
    "bootstrap_ci",
    "walk_forward_split",
    "token_similarity",
]
