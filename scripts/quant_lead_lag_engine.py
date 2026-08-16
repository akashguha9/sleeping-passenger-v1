"""Quant hackathon — learned lead-lag engine (mission 13).

For aligned series (x_t, y_t):

    ρ_xy(k) = Corr(x_t, y_{t+k}),   k ∈ [−K, +K]
    k*      = argmax_k |ρ_xy(k)|

Discipline (mission 42): a peak cross-correlation is labeled ASSOCIATED.
It is upgraded to PREDICTIVE only if a Granger-style out-of-sample test
passes: an AR(p) model of y augmented with lagged x must beat the plain
AR(p) model on chronologically later data (walk-forward, no lookahead).
The word CAUSAL is never emitted by this module.

Minimum-sample gates everywhere; UNKNOWN never becomes zero.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

from scripts.quant_statistics_engine import EPS, pearson
from scripts.quant_walk_forward_split import walk_forward_folds

OK = "OK"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
ASSOCIATED = "ASSOCIATED"
PREDICTIVE = "PREDICTIVE"
NOT_PREDICTIVE = "NOT_PREDICTIVE"


def cross_correlation(x: Sequence[float], y: Sequence[float], *,
                      max_lag: int = 5, n_min: int = 20) -> dict[str, Any]:
    """ρ_xy(k) for k in [−max_lag, max_lag]; positive k ⇒ x leads y."""
    n = min(len(x), len(y))
    if n < n_min + max_lag:
        return {"status": INSUFFICIENT_DATA, "n": n,
                "n_min": n_min + max_lag}
    rows = []
    for k in range(-max_lag, max_lag + 1):
        if k >= 0:
            xa, ya = x[: n - k], y[k:n]
        else:
            xa, ya = x[-k:n], y[: n + k]
        rho = pearson(list(xa), list(ya))
        if rho is not None:
            # Fisher-z two-sided p-value approximation.
            m = len(xa)
            z = 0.5 * math.log((1 + rho + EPS) / (1 - rho + EPS))
            se = 1.0 / math.sqrt(max(m - 3, 1))
            p = 2.0 * (1.0 - _phi(abs(z) / se))
            rows.append({"k": k, "rho": rho, "n": m, "p_value": p})
    if not rows:
        return {"status": INSUFFICIENT_DATA, "n": n}
    best = max(rows, key=lambda r: abs(r["rho"]))
    return {"status": OK, "n": n, "lags": rows, "best_lag": best["k"],
            "best_rho": best["rho"], "best_p_value": best["p_value"],
            "relationship": ASSOCIATED,
            "note": "correlation peak != causal leadership"}


def _phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _ols(features: list[list[float]], target: list[float],
         ) -> list[float] | None:
    """Tiny ridge-stabilized OLS (normal equations + 1e-6 ridge)."""
    k = len(features[0])
    xtx = [[sum(f[i] * f[j] for f in features) + (1e-6 if i == j else 0.0)
            for j in range(k)] for i in range(k)]
    xty = [sum(f[i] * t for f, t in zip(features, target)) for i in range(k)]
    # Gaussian elimination.
    for col in range(k):
        pivot = max(range(col, k), key=lambda r: abs(xtx[r][col]))
        if abs(xtx[pivot][col]) < EPS:
            return None
        xtx[col], xtx[pivot] = xtx[pivot], xtx[col]
        xty[col], xty[pivot] = xty[pivot], xty[col]
        div = xtx[col][col]
        xtx[col] = [v / div for v in xtx[col]]
        xty[col] /= div
        for r in range(k):
            if r != col and abs(xtx[r][col]) > EPS:
                factor = xtx[r][col]
                xtx[r] = [a - factor * b for a, b in zip(xtx[r], xtx[col])]
                xty[r] -= factor * xty[col]
    return xty


def granger_style_oos(x: Sequence[float], y: Sequence[float], *,
                      p: int = 2, q: int = 2, n_folds: int = 3,
                      n_min: int = 30) -> dict[str, Any]:
    """Does lagged x improve OUT-OF-SAMPLE prediction of y beyond y's own
    lags?  Walk-forward MSE comparison; chronological only.

        M0: y_t = Σ a_i y_{t-i} + ε
        M1: y_t = Σ a_i y_{t-i} + Σ b_j x_{t-j} + ε
    """
    n = min(len(x), len(y))
    if n < n_min:
        return {"status": INSUFFICIENT_DATA, "n": n, "n_min": n_min}
    lag0 = max(p, q)
    rows = []
    for t in range(lag0, n):
        base = [1.0] + [y[t - i] for i in range(1, p + 1)]
        aug = base + [x[t - j] for j in range(1, q + 1)]
        rows.append({"t": t, "y": y[t], "base": base, "aug": aug})
    times = [str(r["t"]).zfill(6) for r in rows]
    folds = walk_forward_folds(times, n_folds=n_folds,
                               min_train=max(10, len(rows) // 3))
    if folds["status"] != OK:
        return {"status": INSUFFICIENT_DATA, "n": len(rows)}
    mse0_all, mse1_all = [], []
    for fold in folds["folds"]:
        tr = [r for r, tm in zip(rows, times) if tm in set(fold["train_times"])]
        te = [r for r, tm in zip(rows, times) if tm in set(fold["test_times"])]
        if len(tr) < 10 or not te:
            continue
        b0 = _ols([r["base"] for r in tr], [r["y"] for r in tr])
        b1 = _ols([r["aug"] for r in tr], [r["y"] for r in tr])
        if b0 is None or b1 is None:
            continue
        mse0 = sum((r["y"] - sum(c * v for c, v in zip(b0, r["base"]))) ** 2
                   for r in te) / len(te)
        mse1 = sum((r["y"] - sum(c * v for c, v in zip(b1, r["aug"]))) ** 2
                   for r in te) / len(te)
        mse0_all.append(mse0)
        mse1_all.append(mse1)
    if not mse0_all:
        return {"status": INSUFFICIENT_DATA, "n": len(rows),
                "reason": "no usable folds"}
    avg0 = sum(mse0_all) / len(mse0_all)
    avg1 = sum(mse1_all) / len(mse1_all)
    improvement = (avg0 - avg1) / (avg0 + EPS)
    verdict = PREDICTIVE if improvement > 0.02 else NOT_PREDICTIVE
    return {"status": OK, "n": len(rows), "folds_used": len(mse0_all),
            "oos_mse_baseline": avg0, "oos_mse_augmented": avg1,
            "oos_improvement_frac": improvement,
            "relationship": verdict,
            "threshold_note": "PREDICTIVE requires >2% OOS MSE improvement "
                              "(documented heuristic floor, uncalibrated)",
            "epistemic_status": "ESTIMATED"}


def lead_lag_study(x: Sequence[float], y: Sequence[float], *,
                   label_x: str, label_y: str,
                   max_lag: int = 5) -> dict[str, Any]:
    """Full lead-lag study: cross-correlation + OOS Granger-style check."""
    cc = cross_correlation(x, y, max_lag=max_lag)
    out: dict[str, Any] = {"pair": f"{label_x}->{label_y}",
                           "cross_correlation": cc}
    if cc["status"] != OK:
        out["verdict"] = INSUFFICIENT_DATA
        return out
    gr = granger_style_oos(x, y)
    out["granger_style_oos"] = gr
    if gr.get("relationship") == PREDICTIVE and abs(cc["best_rho"]) > 0.2:
        out["verdict"] = PREDICTIVE
    elif cc["best_p_value"] < 0.05:
        out["verdict"] = ASSOCIATED
    else:
        out["verdict"] = NOT_PREDICTIVE
    return out
