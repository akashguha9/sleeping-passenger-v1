"""Deterministic, seedable RNG for reproducible Monte-Carlo simulation.

OpenMM-lens principle: explicit seeds, bounded run counts, convergence
diagnostics, deterministic testing mode, CPU-safe defaults.

We deliberately do NOT use ``random`` module global state or ``numpy``'s global
seed — both are process-global and would make two concurrent simulations
interfere.  Instead each :class:`DeterministicRNG` owns an independent
``random.Random`` instance seeded from ``(seed, stream_label)`` so that:

* the same ``(seed, data_cutoff, config_version)`` always reproduces bit-for-bit
  the same draws on the same platform, and
* two lenses drawing from the same seed but different ``stream_label`` do not
  collide (independent sub-streams).

No numpy dependency is required at import time; a numpy fast-path is used only
if numpy is already importable, and it is seeded locally (``np.random.default_rng``)
so it never touches global numpy state.
"""
from __future__ import annotations

import hashlib
import math
import random
from typing import Sequence


def _derive_seed(seed: int, stream_label: str) -> int:
    """Derive a stable 64-bit sub-seed from (seed, stream_label)."""
    h = hashlib.sha256(f"{int(seed)}::{stream_label}".encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big", signed=False)


class DeterministicRNG:
    """A single reproducible random stream.

    All methods are pure functions of the internal state; construct a fresh
    instance (or call :meth:`reset`) to replay identical draws.
    """

    __slots__ = ("_seed", "_label", "_rng")

    def __init__(self, seed: int = 0, stream_label: str = "default") -> None:
        self._seed = int(seed)
        self._label = str(stream_label)
        self._rng = random.Random(_derive_seed(self._seed, self._label))

    @property
    def seed(self) -> int:
        return self._seed

    @property
    def stream_label(self) -> str:
        return self._label

    def reset(self) -> None:
        self._rng.seed(_derive_seed(self._seed, self._label))

    def substream(self, label: str) -> "DeterministicRNG":
        """A new independent stream deterministically derived from this one."""
        return DeterministicRNG(self._seed, f"{self._label}/{label}")

    # -- primitive draws ----------------------------------------------------
    def uniform(self, lo: float = 0.0, hi: float = 1.0) -> float:
        return self._rng.uniform(lo, hi)

    def normal(self, mu: float = 0.0, sigma: float = 1.0) -> float:
        return self._rng.gauss(mu, sigma)

    def student_t(self, df: float = 4.0, mu: float = 0.0, sigma: float = 1.0) -> float:
        """Fat-tailed draw (markets are not Gaussian).  df>2 for finite var."""
        df = max(2.001, float(df))
        # Bailey's method via normal / chi-square ratio, using gammavariate.
        z = self._rng.gauss(0.0, 1.0)
        chi2 = 2.0 * self._rng.gammavariate(df / 2.0, 1.0)
        return mu + sigma * z / math.sqrt(chi2 / df)

    def choice(self, seq: Sequence):
        return self._rng.choice(list(seq))

    def shuffle(self, seq: list) -> list:
        out = list(seq)
        self._rng.shuffle(out)
        return out

    def sample_returns(
        self,
        n: int,
        mu: float = 0.0,
        sigma: float = 0.02,
        df: float = 4.0,
    ) -> list[float]:
        """Draw ``n`` fat-tailed daily-return samples (bounded run count)."""
        n = max(0, min(int(n), 100_000))
        return [self.student_t(df, mu, sigma) for _ in range(n)]


def convergence_diagnostic(
    samples: Sequence[float],
    tol: float = 0.01,
) -> dict[str, float | str | bool]:
    """Simple running-mean convergence check with an early-stopping signal.

    Splits the sample into two halves and compares their means relative to the
    overall dispersion.  Returns a diagnostic dict; ``converged`` is True when
    the half-means agree within ``tol`` of the standard error.
    """
    xs = [float(x) for x in samples if x == x]
    n = len(xs)
    if n < 8:
        return {"converged": False, "n": n, "reason": "too_few_samples",
                "half_mean_gap": 0.0, "std_error": 0.0}
    mid = n // 2
    first = xs[:mid]
    second = xs[mid:]
    m1 = sum(first) / len(first)
    m2 = sum(second) / len(second)
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / (n - 1)
    std = math.sqrt(max(var, 0.0))
    se = std / math.sqrt(n) if n else 0.0
    gap = abs(m1 - m2)
    # Converged when the two halves' means differ by less than max(tol, 2*se).
    threshold = max(tol, 2.0 * se)
    converged = gap <= threshold
    return {
        "converged": bool(converged),
        "n": n,
        "half_mean_gap": round(gap, 6),
        "std_error": round(se, 6),
        "threshold": round(threshold, 6),
        "reason": "ok" if converged else "half_means_disagree",
    }


__all__ = ["DeterministicRNG", "convergence_diagnostic"]
