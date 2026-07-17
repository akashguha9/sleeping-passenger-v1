"""Uncertainty quantification helpers — distributions, never point forecasts.

GROMACS-lens principle: treat the market as an *ensemble* of plausible states
and summarize central tendency, dispersion, tails, and metastable states rather
than emitting one deterministic number.
"""
from __future__ import annotations

import math
from typing import Sequence

try:
    from scripts.simulation_intelligence.contracts import UncertaintyBand
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from simulation_intelligence.contracts import UncertaintyBand  # type: ignore[no-redef]


def _percentile(sorted_xs: list[float], q: float) -> float:
    """Linear-interpolation percentile; ``q`` in [0, 1]. Assumes sorted input."""
    if not sorted_xs:
        return 0.0
    if len(sorted_xs) == 1:
        return sorted_xs[0]
    pos = q * (len(sorted_xs) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_xs[lo]
    frac = pos - lo
    return sorted_xs[lo] * (1 - frac) + sorted_xs[hi] * frac


def summarize(samples: Sequence[float], convergence: str = "UNKNOWN") -> UncertaintyBand:
    """Build an :class:`UncertaintyBand` from a sample set.

    Fails closed: an empty sample set yields an all-zero band flagged
    ``convergence="NO_SAMPLES"`` so callers never mistake it for a real
    distribution.
    """
    xs = sorted(float(x) for x in samples if x == x)
    n = len(xs)
    if n == 0:
        return UncertaintyBand(
            central=0.0, p05=0.0, p50=0.0, p95=0.0, dispersion=0.0,
            tail_low=0.0, tail_high=0.0, n_samples=0, convergence="NO_SAMPLES",
        )
    mean = sum(xs) / n
    if n > 1:
        var = sum((x - mean) ** 2 for x in xs) / (n - 1)
        std = math.sqrt(max(var, 0.0))
    else:
        std = 0.0
    return UncertaintyBand(
        central=round(mean, 8),
        p05=round(_percentile(xs, 0.05), 8),
        p50=round(_percentile(xs, 0.50), 8),
        p95=round(_percentile(xs, 0.95), 8),
        dispersion=round(std, 8),
        tail_low=round(_percentile(xs, 0.01), 8),
        tail_high=round(_percentile(xs, 0.99), 8),
        n_samples=n,
        convergence=convergence,
    )


def metastable_states(samples: Sequence[float], bins: int = 12) -> list[dict]:
    """Detect metastable modes (local density peaks) in a sample set.

    GROMACS-style: report the histogram modes so a caller can see whether the
    ensemble is unimodal (one likely regime) or multimodal (regime ambiguity).
    """
    xs = sorted(float(x) for x in samples if x == x)
    n = len(xs)
    if n < bins or xs[0] == xs[-1]:
        return []
    lo, hi = xs[0], xs[-1]
    width = (hi - lo) / bins
    counts = [0] * bins
    for x in xs:
        idx = min(bins - 1, int((x - lo) / width)) if width > 0 else 0
        counts[idx] += 1
    modes = []
    for i in range(bins):
        left = counts[i - 1] if i > 0 else -1
        right = counts[i + 1] if i < bins - 1 else -1
        if counts[i] > left and counts[i] >= right and counts[i] >= max(2, n // bins):
            modes.append({
                "center": round(lo + (i + 0.5) * width, 8),
                "density": round(counts[i] / n, 4),
            })
    return modes


def sensitivity_to_initial_conditions(
    baseline: Sequence[float],
    perturbed: Sequence[float],
) -> float:
    """A Lyapunov-flavoured sensitivity: |Δmean| / (dispersion + eps).

    High values mean a small change in initial conditions moved the ensemble a
    lot relative to its own spread — the system is sensitive/chaotic there.
    """
    b = [float(x) for x in baseline if x == x]
    p = [float(x) for x in perturbed if x == x]
    if not b or not p:
        return 0.0
    mb = sum(b) / len(b)
    mp = sum(p) / len(p)
    allx = b + p
    mean = sum(allx) / len(allx)
    var = sum((x - mean) ** 2 for x in allx) / max(1, len(allx) - 1)
    disp = math.sqrt(max(var, 0.0))
    return round(abs(mp - mb) / (disp + 1e-9), 6)


__all__ = [
    "summarize",
    "metastable_states",
    "sensitivity_to_initial_conditions",
]
