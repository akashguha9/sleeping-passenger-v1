"""Candidate memory decay — old watchlist names fade without fresh evidence.

A repeated candidate that keeps appearing on the board but has NO new supporting
signal should not retain yesterday's conviction. We decay its score smoothly:

    DecayFactor(t)     = exp(-lambda * d(t))
    Score_decayed(t)   = base_score_yesterday(t) * exp(-lambda * d(t))
    ACQS(t)            = CQS(t) * exp(-lambda * d(t))

with lambda = 0.25 and d(t) = days since the last *fresh* supporting signal.

    d = 0 -> 1.000   d = 3 -> ~0.472
    d = 1 -> ~0.779   d = 5 -> ~0.287
    d = 2 -> ~0.607   d = 7 -> ~0.174

A fresh signal today resets d(t) = 0. Fresh signal = FRESH_TODAY/UPDATED_TODAY
price mover, a live news/filing event today, or an explicit operator/model note
of a new development. With no fresh evidence we infer d(t) (default 1 for a
repeated yesterday name, 0 for a brand-new static-universe name — but a new
static-universe name's WHY_TODAY_SCORE stays low, so it cannot become executable
on decay alone).

Pure module: no I/O, no fabrication of freshness.
"""
from __future__ import annotations

import math
from typing import Any

try:
    from scripts.daily_discovery_config import load_discovery_thresholds
    from scripts.daily_payload import normalize_ticker
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from daily_discovery_config import load_discovery_thresholds
    from daily_payload import normalize_ticker


DEFAULT_LAMBDA = 0.25

# Freshness labels that count as a fresh supporting signal (reset d -> 0).
FRESH_FRESHNESS_LABELS = {"FRESH_TODAY", "UPDATED_TODAY"}


def _resolve_lambda(decay_lambda: float | None, thresholds: dict[str, Any] | None) -> float:
    if decay_lambda is not None:
        return float(decay_lambda)
    table = thresholds or load_discovery_thresholds()
    try:
        return float(table.get("memory_decay_lambda", DEFAULT_LAMBDA))
    except (TypeError, ValueError):
        return DEFAULT_LAMBDA


def decay_factor(days_without_fresh_signal: float, decay_lambda: float = DEFAULT_LAMBDA) -> float:
    """exp(-lambda * d). d is clamped to >= 0."""
    d = max(0.0, float(days_without_fresh_signal))
    return round(math.exp(-float(decay_lambda) * d), 4)


def decayed_score(
    base_score: float,
    days_without_fresh_signal: float,
    decay_lambda: float = DEFAULT_LAMBDA,
) -> float:
    """base_score * exp(-lambda * d), clamped to [0, base_score]."""
    factor = math.exp(-float(decay_lambda) * max(0.0, float(days_without_fresh_signal)))
    return round(max(0.0, float(base_score)) * factor, 4)


def infer_days_without_fresh_signal(
    *,
    fresh_signal_present: bool,
    in_yesterday: bool,
    prior_days: float | None = None,
) -> int:
    """Infer d(t) when it is not supplied explicitly.

    * fresh signal today                    -> 0
    * known prior d                         -> prior_days + 1
    * repeated yesterday name, no fresh      -> 1
    * brand-new name, no fresh               -> 0  (low WHY_TODAY keeps it gated)
    """
    if fresh_signal_present:
        return 0
    if prior_days is not None:
        return int(max(0.0, float(prior_days)) + 1)
    if in_yesterday:
        return 1
    return 0


def compute_memory_decay(
    ticker: str,
    base_candidate_score: float,
    *,
    days_without_fresh_signal: float | None = None,
    fresh_signal_present: bool = False,
    in_yesterday: bool = False,
    prior_days: float | None = None,
    decay_lambda: float | None = None,
    thresholds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the full memory-decay record for one ticker."""
    lam = _resolve_lambda(decay_lambda, thresholds)
    if days_without_fresh_signal is None:
        d = infer_days_without_fresh_signal(
            fresh_signal_present=fresh_signal_present,
            in_yesterday=in_yesterday,
            prior_days=prior_days,
        )
    else:
        d = 0 if fresh_signal_present else max(0.0, float(days_without_fresh_signal))
    factor = decay_factor(d, lam)
    return {
        "ticker": normalize_ticker(ticker),
        "base_candidate_score": round(float(base_candidate_score), 4),
        "days_without_fresh_signal": d,
        "decay_lambda": lam,
        "decay_factor": factor,
        "decayed_candidate_score": decayed_score(base_candidate_score, d, lam),
        "fresh_signal_present": bool(fresh_signal_present),
    }


def fresh_signal_from_freshness(label: Any) -> bool:
    """True if a freshness label denotes a fresh supporting signal today."""
    return str(label or "").strip().upper() in FRESH_FRESHNESS_LABELS


def adjusted_cqs(
    cqs: float,
    days_without_fresh_signal: float,
    *,
    fresh_signal_present: bool = False,
    decay_lambda: float | None = None,
    thresholds: dict[str, Any] | None = None,
) -> float:
    """ACQS(t) = CQS(t) * exp(-lambda * d(t)). Fresh signal resets d -> 0."""
    lam = _resolve_lambda(decay_lambda, thresholds)
    d = 0 if fresh_signal_present else max(0.0, float(days_without_fresh_signal))
    return decayed_score(cqs, d, lam)


__all__ = [
    "DEFAULT_LAMBDA",
    "FRESH_FRESHNESS_LABELS",
    "decay_factor",
    "decayed_score",
    "infer_days_without_fresh_signal",
    "compute_memory_decay",
    "fresh_signal_from_freshness",
    "adjusted_cqs",
]
