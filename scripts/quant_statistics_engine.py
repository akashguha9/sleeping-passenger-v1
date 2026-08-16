"""Quant hackathon — core statistical primitives (pure stdlib, deterministic).

Every function is a mathematical contract:
- explicit epsilon policy (``EPS = 1e-9``) — no /0, no log(0), no inf Z;
- explicit minimum-sample gates — below ``n_min`` the answer is
  ``INSUFFICIENT_DATA``, never a fake number (UNKNOWN != ZERO);
- deterministic bootstrap via seeded ``random.Random`` (IID and block);
- every output carries ``n`` and an epistemic label.

Implements: mean/CI (normal + bootstrap), t-statistic, Pearson/Spearman
information coefficients + IC information ratio, quantile monotonicity
test, Brier score, log loss, reliability (calibration) buckets,
Benjamini-Hochberg FDR, exponential-decay fit (half-life), and a
standardized shock Z with strictly-historical moments (no lookahead).
"""
from __future__ import annotations

import math
import random
from typing import Any, Sequence

EPS = 1e-9
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
OK = "OK"

DERIVED = "DERIVED"
ESTIMATED = "ESTIMATED"
HEURISTIC = "HEURISTIC"


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def _std(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def mean_with_ci(xs: Sequence[float], *, n_min: int = 5,
                 z: float = 1.96) -> dict[str, Any]:
    """Sample mean with normal-theory CI: mu ± z·s/sqrt(N)."""
    xs = [float(x) for x in xs]
    if len(xs) < n_min:
        return {"status": INSUFFICIENT_DATA, "n": len(xs), "n_min": n_min}
    m, s = _mean(xs), _std(xs)
    se = s / math.sqrt(len(xs))
    return {"status": OK, "n": len(xs), "mean": m, "median": _median(xs),
            "std": s, "se": se, "ci": [m - z * se, m + z * se],
            "epistemic_status": DERIVED}


def _median(xs: Sequence[float]) -> float:
    s = sorted(xs)
    k = len(s) // 2
    return s[k] if len(s) % 2 else (s[k - 1] + s[k]) / 2.0


def t_statistic(xs: Sequence[float], mu0: float = 0.0,
                *, n_min: int = 5) -> dict[str, Any]:
    """t = (x̄ − μ₀)/(s/√N).  Reports effect size, never 'significant ⇒ profitable'."""
    xs = [float(x) for x in xs]
    if len(xs) < n_min:
        return {"status": INSUFFICIENT_DATA, "n": len(xs), "n_min": n_min}
    s = _std(xs)
    t = (_mean(xs) - mu0) / (s / math.sqrt(len(xs)) + EPS)
    return {"status": OK, "n": len(xs), "t": t, "mean": _mean(xs),
            "effect_size": (_mean(xs) - mu0) / (s + EPS),
            "epistemic_status": DERIVED}


def bootstrap_ci(xs: Sequence[float], *, stat: str = "mean", b: int = 2000,
                 seed: int = 7, alpha: float = 0.05,
                 block: int | None = None, n_min: int = 8) -> dict[str, Any]:
    """Percentile bootstrap CI; ``block`` switches to circular block bootstrap
    for temporally dependent series."""
    xs = [float(x) for x in xs]
    n = len(xs)
    if n < n_min:
        return {"status": INSUFFICIENT_DATA, "n": n, "n_min": n_min}
    rng = random.Random(seed)
    fn = _mean if stat == "mean" else _median
    draws: list[float] = []
    for _ in range(b):
        if block and block > 1:
            sample: list[float] = []
            while len(sample) < n:
                start = rng.randrange(n)
                sample.extend(xs[(start + j) % n] for j in range(block))
            sample = sample[:n]
        else:
            sample = [xs[rng.randrange(n)] for _ in range(n)]
        draws.append(fn(sample))
    draws.sort()
    lo = draws[int((alpha / 2) * b)]
    hi = draws[min(b - 1, int((1 - alpha / 2) * b))]
    return {"status": OK, "n": n, "stat": stat, "point": fn(xs),
            "ci": [lo, hi], "b": b, "block": block,
            "epistemic_status": ESTIMATED}


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    mx, my = _mean(xs), _mean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    den = math.sqrt(sum((a - mx) ** 2 for a in xs)
                    * sum((b - my) ** 2 for b in ys))
    if den < EPS:
        return None
    return num / den


def _ranks(xs: Sequence[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def information_coefficient(signal: Sequence[float], fwd: Sequence[float],
                            *, n_min: int = 10) -> dict[str, Any]:
    """IC = Corr(S_t, R_{t+h}) and RankIC = Spearman(S_t, R_{t+h})."""
    if len(signal) != len(fwd) or len(signal) < n_min:
        return {"status": INSUFFICIENT_DATA, "n": len(signal), "n_min": n_min}
    ic = pearson(signal, fwd)
    rank_ic = pearson(_ranks(signal), _ranks(fwd))
    return {"status": OK, "n": len(signal), "ic": ic, "rank_ic": rank_ic,
            "epistemic_status": DERIVED}


def ic_information_ratio(ics: Sequence[float], *, n_min: int = 5,
                         ) -> dict[str, Any]:
    """IR_IC = E[IC]/σ(IC) over per-period ICs."""
    ics = [x for x in ics if x is not None]
    if len(ics) < n_min:
        return {"status": INSUFFICIENT_DATA, "n": len(ics), "n_min": n_min}
    return {"status": OK, "n": len(ics), "mean_ic": _mean(ics),
            "ic_vol": _std(ics),
            "ir": _mean(ics) / (_std(ics) + EPS),
            "epistemic_status": DERIVED}


def quantile_monotonicity(signal: Sequence[float], fwd: Sequence[float],
                          *, k: int = 5, n_min_per_bucket: int = 5,
                          ) -> dict[str, Any]:
    """Bucket forward returns by signal quantile; expose whether E[R|Q]
    is actually monotone.  A sophisticated score with no monotone
    relationship is exposed as such (mission 22)."""
    n = len(signal)
    if n != len(fwd) or n < k * n_min_per_bucket:
        return {"status": INSUFFICIENT_DATA, "n": n,
                "n_min": k * n_min_per_bucket}
    order = sorted(range(n), key=lambda i: signal[i])
    buckets: list[dict[str, Any]] = []
    per = n // k
    for q in range(k):
        idx = order[q * per: (q + 1) * per if q < k - 1 else n]
        rs = [fwd[i] for i in idx]
        buckets.append({"quantile": q + 1, "n": len(rs),
                        "mean_fwd": _mean(rs), "median_fwd": _median(rs),
                        "hit_rate": sum(1 for r in rs if r > 0) / len(rs)})
    means = [b["mean_fwd"] for b in buckets]
    increases = sum(1 for a, b2 in zip(means, means[1:]) if b2 > a)
    return {"status": OK, "n": n, "k": k, "buckets": buckets,
            "top_minus_bottom": means[-1] - means[0],
            "monotone_fraction": increases / (k - 1),
            "is_strictly_monotone": increases == k - 1,
            "epistemic_status": DERIVED}


def brier_score(ps: Sequence[float], ys: Sequence[int],
                *, n_min: int = 10) -> dict[str, Any]:
    """BS = mean (p − y)²; lower is better.  Baseline = constant base rate."""
    if len(ps) != len(ys) or len(ps) < n_min:
        return {"status": INSUFFICIENT_DATA, "n": len(ps), "n_min": n_min}
    bs = _mean([(p - y) ** 2 for p, y in zip(ps, ys)])
    base = _mean([float(y) for y in ys])
    bs_base = _mean([(base - y) ** 2 for y in ys])
    return {"status": OK, "n": len(ps), "brier": bs,
            "base_rate": base, "brier_baseline_constant": bs_base,
            "skill_vs_constant": bs_base - bs,   # >0 ⇒ beats dumb baseline
            "epistemic_status": DERIVED}


def log_loss(ps: Sequence[float], ys: Sequence[int],
             *, n_min: int = 10) -> dict[str, Any]:
    if len(ps) != len(ys) or len(ps) < n_min:
        return {"status": INSUFFICIENT_DATA, "n": len(ps), "n_min": n_min}
    ll = -_mean([y * math.log(max(p, EPS))
                 + (1 - y) * math.log(max(1 - p, EPS))
                 for p, y in zip(ps, ys)])
    return {"status": OK, "n": len(ps), "log_loss": ll,
            "epistemic_status": DERIVED}


def reliability_buckets(ps: Sequence[float], ys: Sequence[int],
                        *, k: int = 5, n_min_per_bucket: int = 5,
                        ) -> dict[str, Any]:
    """Calibration curve: within each forecast bucket, does P(Y=1|p̂≈p) ≈ p?
    Buckets below the sample floor are reported as INSUFFICIENT_DATA rows,
    never silently averaged."""
    if len(ps) != len(ys) or not ps:
        return {"status": INSUFFICIENT_DATA, "n": len(ps)}
    edges = [i / k for i in range(k + 1)]
    rows = []
    for lo, hi in zip(edges, edges[1:]):
        idx = [i for i, p in enumerate(ps)
               if (lo <= p < hi) or (hi == 1.0 and p == 1.0)]
        if len(idx) < n_min_per_bucket:
            rows.append({"bucket": [lo, hi], "n": len(idx),
                         "status": INSUFFICIENT_DATA})
            continue
        mean_p = _mean([ps[i] for i in idx])
        freq = _mean([float(ys[i]) for i in idx])
        rows.append({"bucket": [lo, hi], "n": len(idx), "status": OK,
                     "mean_forecast": mean_p, "observed_freq": freq,
                     "gap": freq - mean_p})
    usable = [r for r in rows if r["status"] == OK]
    ece = (sum(r["n"] * abs(r["gap"]) for r in usable)
           / max(1, sum(r["n"] for r in usable))) if usable else None
    return {"status": OK if usable else INSUFFICIENT_DATA,
            "n": len(ps), "buckets": rows,
            "expected_calibration_error": ece,
            "epistemic_status": DERIVED}


def benjamini_hochberg(pvals: Sequence[float], *, alpha: float = 0.05,
                       ) -> dict[str, Any]:
    """BH-FDR: returns which hypotheses survive at FDR ``alpha`` (mission 27)."""
    m = len(pvals)
    if m == 0:
        return {"status": INSUFFICIENT_DATA, "m": 0}
    order = sorted(range(m), key=lambda i: pvals[i])
    survives = [False] * m
    max_k = 0
    for rank, i in enumerate(order, 1):
        if pvals[i] <= alpha * rank / m:
            max_k = rank
    for rank, i in enumerate(order, 1):
        if rank <= max_k:
            survives[i] = True
    return {"status": OK, "m": m, "alpha": alpha,
            "n_survive": sum(survives), "survives": survives,
            "epistemic_status": DERIVED}


def standardized_shock(series: Sequence[tuple[int, float]], *,
                       window: int = 20, n_min: int = 8) -> dict[str, Any]:
    """Z^P_t = (ΔP_t − μ_ΔP)/(σ_ΔP + ε) with μ, σ from STRICTLY PRIOR deltas
    only (no lookahead).  ``series`` is (day, value) sorted ascending."""
    pts = sorted(series)
    if len(pts) < n_min + 1:
        return {"status": INSUFFICIENT_DATA, "n": len(pts),
                "n_min": n_min + 1}
    deltas = [b[1] - a[1] for a, b in zip(pts, pts[1:])]
    hist = deltas[:-1][-window:]          # strictly prior to the last delta
    if len(hist) < n_min:
        return {"status": INSUFFICIENT_DATA, "n": len(hist), "n_min": n_min}
    mu, sd = _mean(hist), _std(hist)
    z = (deltas[-1] - mu) / (sd + EPS)
    return {"status": OK, "n": len(hist), "delta": deltas[-1],
            "mu_hist": mu, "sigma_hist": sd, "z": z,
            "lookahead_free": True, "epistemic_status": DERIVED}


def fit_exponential_decay(points: Sequence[tuple[float, float]], *,
                          n_min: int = 4) -> dict[str, Any]:
    """Fit A(t) = A₀·e^(−λt) by log-linear least squares on positive points.
    Reports half-life t½ = ln2/λ and R² so a bad exponential fit is visible
    (mission 17: do not force exponential decay)."""
    pts = [(t, a) for t, a in points if a > EPS]
    if len(pts) < n_min:
        return {"status": INSUFFICIENT_DATA, "n": len(pts), "n_min": n_min}
    ts = [t for t, _ in pts]
    logs = [math.log(a) for _, a in pts]
    mt, ml = _mean(ts), _mean(logs)
    denom = sum((t - mt) ** 2 for t in ts)
    if denom < EPS:
        return {"status": INSUFFICIENT_DATA, "n": len(pts),
                "reason": "no time variation"}
    slope = sum((t - mt) * (l - ml) for t, l in zip(ts, logs)) / denom
    lam = -slope
    ss_res = sum((l - (ml + slope * (t - mt))) ** 2
                 for t, l in zip(ts, logs))
    ss_tot = sum((l - ml) ** 2 for l in logs)
    r2 = 1.0 - ss_res / (ss_tot + EPS)
    return {"status": OK, "n": len(pts), "lambda": lam,
            "half_life": (math.log(2) / lam) if lam > EPS else None,
            "r_squared": r2,
            "fit_adequate": r2 >= 0.6,   # documented heuristic floor
            "epistemic_status": ESTIMATED}
