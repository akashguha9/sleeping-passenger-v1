"""Score recalibration map — isotonic (PAV) + Platt scaling, OOS-validated.

The raw signal scores are hand-tuned and (when outcomes exist) often
miscalibrated: a "0.9" may not win 90% of the time. This module *learns* a
monotonic mapping ``calibrated_p = f(raw_score)`` from resolved outcomes so the
number the operator sees is an honest probability — and validates the
improvement OUT OF SAMPLE so we never claim a fit that only memorised the
training data.

Two methods, both stdlib-only (no numpy/sklearn):
  * Isotonic regression via Pool-Adjacent-Violators (non-parametric, monotone).
  * Platt scaling (logistic ``sigmoid(A·s + B)``).

The chooser fits both on a TRAIN split and keeps whichever has the lower Brier
on the held-out TEST split — and only if it beats the raw scores OOS. If
neither beats raw, ``method='identity'`` (we do not pretend to recalibrate).

Honesty contract
----------------
Pure compute. No DB, no network, no broker. A recalibrated probability is still
advisory: it NEVER enables sizing on its own — provenance gating (real_n>=50 +
human approval) still applies upstream. BREAKEVEN outcomes are y=0.5.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

_EPS = 1e-6


def _clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


def _clamp_prob(p: float) -> float:
    return min(1 - _EPS, max(_EPS, p))


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


# ---------------------------------------------------------------------------
# Isotonic regression (Pool Adjacent Violators)
# ---------------------------------------------------------------------------

def isotonic_pav(xs: Sequence[float], ys: Sequence[float],
                 weights: Sequence[float] | None = None) -> tuple[list[float], list[float]]:
    """Fit a non-decreasing step function to (xs, ys).

    Returns (xs_sorted_unique-ish, fitted_values) suitable for interpolation.
    xs need not be sorted; ties are pooled. Pure PAV, O(n).
    """
    n = len(xs)
    if n == 0:
        return [], []
    w = list(weights) if weights is not None else [1.0] * n
    order = sorted(range(n), key=lambda i: xs[i])
    sx = [float(xs[i]) for i in order]
    sy = [float(ys[i]) for i in order]
    sw = [float(w[i]) for i in order]

    # blocks: [weighted_sum_y, weight, count, value]
    blocks: list[list[float]] = []
    for y, wt in zip(sy, sw):
        blocks.append([y * wt, wt, 1.0, y])
        while len(blocks) >= 2 and blocks[-2][3] > blocks[-1][3] + 0.0:
            wy2, w2, c2, _ = blocks.pop()
            wy1, w1, c1, _ = blocks.pop()
            wy, ww, cc = wy1 + wy2, w1 + w2, c1 + c2
            blocks.append([wy, ww, cc, wy / ww])

    fitted_sorted: list[float] = []
    for wy, ww, cc, val in blocks:
        fitted_sorted.extend([val] * int(cc))
    return sx, fitted_sorted


@dataclass
class IsotonicModel:
    xs: list[float]
    ys: list[float]  # fitted, monotonic non-decreasing

    def predict(self, s: float) -> float:
        xs, ys = self.xs, self.ys
        if not xs:
            return _clamp01(s)
        if s <= xs[0]:
            return _clamp01(ys[0])
        if s >= xs[-1]:
            return _clamp01(ys[-1])
        # binary search for interval
        lo, hi = 0, len(xs) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if xs[mid] <= s:
                lo = mid
            else:
                hi = mid
        x0, x1 = xs[lo], xs[hi]
        y0, y1 = ys[lo], ys[hi]
        if x1 == x0:
            return _clamp01(y1)
        t = (s - x0) / (x1 - x0)
        return _clamp01(y0 + t * (y1 - y0))


def fit_isotonic(scores: Sequence[float], ys: Sequence[float]) -> IsotonicModel:
    xs, fitted = isotonic_pav(scores, ys)
    return IsotonicModel(xs=xs, ys=fitted)


# ---------------------------------------------------------------------------
# Platt scaling (logistic regression on the 1-D score)
# ---------------------------------------------------------------------------

@dataclass
class PlattModel:
    a: float
    b: float

    def predict(self, s: float) -> float:
        return _clamp01(_sigmoid(self.a * s + self.b))


def fit_platt(scores: Sequence[float], ys: Sequence[float],
              *, iters: int = 500, lr: float = 0.5) -> PlattModel:
    """Fit sigmoid(a·s + b) by gradient descent on cross-entropy.

    Deterministic (fixed init + iters). Soft labels (y=0.5) are supported.
    """
    a, b = 0.0, 0.0
    n = len(scores)
    if n == 0:
        return PlattModel(a=1.0, b=0.0)
    for _ in range(iters):
        ga = gb = 0.0
        for s, y in zip(scores, ys):
            p = _sigmoid(a * s + b)
            err = p - y
            ga += err * s
            gb += err
        a -= lr * ga / n
        b -= lr * gb / n
    return PlattModel(a=a, b=b)


# ---------------------------------------------------------------------------
# Metrics on (score, y) pairs
# ---------------------------------------------------------------------------

_DEFAULT_BINS = ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.75), (0.75, 0.9), (0.9, 1.0001))


def _ece(ps: Sequence[float], ys: Sequence[float], bins=_DEFAULT_BINS) -> float:
    n = len(ps)
    if n == 0:
        return 0.0
    total = 0.0
    for lo, hi in bins:
        idx = [i for i in range(n) if lo <= ps[i] < hi]
        if not idx:
            continue
        conf = sum(ps[i] for i in idx) / len(idx)
        acc = sum(ys[i] for i in idx) / len(idx)
        total += (len(idx) / n) * abs(acc - conf)
    return total


def _brier(ps: Sequence[float], ys: Sequence[float]) -> float:
    n = len(ps)
    return sum((ps[i] - ys[i]) ** 2 for i in range(n)) / n if n else 0.0


# ---------------------------------------------------------------------------
# Chooser: fit on train, validate OOS, keep only if it beats raw
# ---------------------------------------------------------------------------

@dataclass
class CalibrationMap:
    method: str            # "isotonic" | "platt" | "identity"
    isotonic: IsotonicModel | None = None
    platt: PlattModel | None = None
    train_n: int = 0
    test_n: int = 0
    raw_test_brier: float = 0.0
    cal_test_brier: float = 0.0
    raw_test_ece: float = 0.0
    cal_test_ece: float = 0.0
    improved: bool = False
    advisory_only: bool = True
    human_review_required: bool = True
    broker_api_called: bool = False

    def apply(self, raw_score: float) -> float:
        s = _clamp01(float(raw_score))
        if self.method == "isotonic" and self.isotonic is not None:
            return self.isotonic.predict(s)
        if self.method == "platt" and self.platt is not None:
            return self.platt.predict(s)
        return s  # identity

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "train_n": self.train_n,
            "test_n": self.test_n,
            "raw_test_brier": self.raw_test_brier,
            "cal_test_brier": self.cal_test_brier,
            "raw_test_ece": self.raw_test_ece,
            "cal_test_ece": self.cal_test_ece,
            "brier_improvement": self.raw_test_brier - self.cal_test_brier,
            "ece_improvement": self.raw_test_ece - self.cal_test_ece,
            "improved_out_of_sample": self.improved,
            "advisory_only": True,
            "human_review_required": True,
            "broker_api_called": False,
        }


def _split(pairs: list[tuple[float, float]], test_frac: float) -> tuple[list, list]:
    """Deterministic split: interleave so train/test cover the score range."""
    ordered = sorted(pairs, key=lambda p: p[0])
    train, test = [], []
    step = max(2, int(round(1 / test_frac))) if test_frac > 0 else 0
    for i, p in enumerate(ordered):
        if step and i % step == 0:
            test.append(p)
        else:
            train.append(p)
    return train, test


def fit_calibration_map(
    scores: Sequence[float],
    ys: Sequence[float],
    *,
    test_frac: float = 0.34,
    min_train: int = 10,
) -> CalibrationMap:
    """Fit isotonic + Platt on train, keep whichever beats raw OOS by Brier.

    ``ys`` may be soft (BREAKEVEN -> 0.5). Returns method='identity' when there
    is too little data or neither method improves out of sample — we never
    claim a recalibration that does not generalise.
    """
    pairs = [(_clamp01(float(s)), float(y)) for s, y in zip(scores, ys)]
    if len(pairs) < min_train + 2:
        return CalibrationMap(method="identity", train_n=len(pairs), test_n=0)

    train, test = _split(pairs, test_frac)
    if len(train) < min_train or len(test) < 2:
        return CalibrationMap(method="identity", train_n=len(train), test_n=len(test))

    tr_s = [p[0] for p in train]
    tr_y = [p[1] for p in train]
    te_s = [p[0] for p in test]
    te_y = [p[1] for p in test]

    iso = fit_isotonic(tr_s, tr_y)
    platt = fit_platt(tr_s, tr_y)

    raw_brier = _brier(te_s, te_y)
    raw_ece = _ece(te_s, te_y)
    iso_p = [iso.predict(s) for s in te_s]
    platt_p = [platt.predict(s) for s in te_s]
    iso_brier = _brier(iso_p, te_y)
    platt_brier = _brier(platt_p, te_y)

    # Choose the better OOS Brier; require strict improvement over raw.
    best_method, best_brier = "identity", raw_brier
    if iso_brier < best_brier - 1e-9:
        best_method, best_brier = "isotonic", iso_brier
    if platt_brier < best_brier - 1e-9:
        best_method, best_brier = "platt", platt_brier

    if best_method == "isotonic":
        cal_p = iso_p
    elif best_method == "platt":
        cal_p = platt_p
    else:
        cal_p = te_s

    return CalibrationMap(
        method=best_method,
        isotonic=iso,
        platt=platt,
        train_n=len(train),
        test_n=len(test),
        raw_test_brier=raw_brier,
        cal_test_brier=_brier(cal_p, te_y),
        raw_test_ece=raw_ece,
        cal_test_ece=_ece(cal_p, te_y),
        improved=best_method != "identity",
    )


def fit_from_outcomes(outcomes: list[Any], **kwargs) -> CalibrationMap:
    """Fit a calibration map from eligible OutcomeEvidence records."""
    try:
        from scripts import outcome_evidence as oe
        from scripts.score_calibration import _normalize_score, _y_of
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        import outcome_evidence as oe  # type: ignore[no-redef]
        from score_calibration import _normalize_score, _y_of  # type: ignore[no-redef]
    scores: list[float] = []
    ys: list[float] = []
    for o in oe.eligible_outcomes(list(outcomes)):
        y = _y_of(o.outcome_label)
        s = _normalize_score(o.score_at_entry)
        if y is None or s is None:
            continue
        scores.append(s)
        ys.append(y)
    return fit_calibration_map(scores, ys, **kwargs)


__all__ = [
    "isotonic_pav", "IsotonicModel", "fit_isotonic",
    "PlattModel", "fit_platt",
    "CalibrationMap", "fit_calibration_map", "fit_from_outcomes",
]
