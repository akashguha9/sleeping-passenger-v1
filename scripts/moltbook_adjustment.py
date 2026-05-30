"""Objective 6 — Moltbook read-back penalty hook (deterministic, conservative).

Moltbook today is a write-only loss journal: entries are recorded but nothing
reads them back into scoring/admission.  This module is the *minimal* closed
loop — a deterministic, smoothed penalty that lets prior bad-process / loss
patterns gently down-weight a new candidate's advisory probability.  It is NOT
a learning engine and makes no predictive claim.

Math (fixed constants, no fitting):

    pattern signature
        φ(c) = sha1(country | sector | signal_class | source_mix |
                    market_regime | failure_type)

    counts over Moltbook entries matching φ
        n_bad   = #{outcome_quality in BAD_OUTCOMES}
        n_good  = #{outcome_quality in GOOD_OUTCOMES}
        n_total = n_bad + n_good

    smoothed bad rate (α=1, β=3)
        BadRate(φ) = (n_bad + α) / (n_total + α + β)

    evidence weight (N_min=5)
        EvidenceWeight(φ) = min(1, n_total / N_min)

    penalty (λ=0.15)
        M_penalty(φ) = λ · BadRate(φ) · EvidenceWeight(φ)

    adjusted probability
        p_adj = σ(logit(p_base) − M_penalty(φ))

Safety: Moltbook can only DOWNGRADE or warn.  It never increases probability,
never unlocks execution, never produces broker/execution permission.  No
matching history → penalty 0 and reason ``NO_MATCHING_MOLTBOOK_HISTORY``.
"""
from __future__ import annotations

import hashlib
import math
from typing import Any, Iterable, Mapping

try:
    from scripts.advisory_contract import advisory_safety_stamps
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]

ALPHA: float = 1.0
BETA: float = 3.0
N_MIN: int = 5
LAMBDA: float = 0.15

# Default penalty above which a CANDIDATE advisory is downgraded to WATCHLIST.
DEFAULT_DOWNGRADE_THRESHOLD: float = 0.05

BAD_OUTCOMES: frozenset[str] = frozenset(
    {"BAD_PROCESS", "LOSS", "STOP_LOSS_HIT", "STOP_LOSS", "TRAILING_STOP_HIT"}
)
GOOD_OUTCOMES: frozenset[str] = frozenset(
    {"GOOD_PROCESS", "WIN", "TP_HIT", "TAKE_PROFIT_HIT", "PARTIAL_TP_HIT"}
)

NO_MATCH_REASON = "NO_MATCHING_MOLTBOOK_HISTORY"


def _norm(value: Any) -> str:
    return str(value if value is not None else "").strip().lower()


def compute_pattern_signature(
    *,
    country: Any = None,
    signal_class: Any = None,
    source_mix: Any = None,
    sector: Any = None,
    market_regime: Any = None,
    failure_type: Any = None,
) -> str:
    """Deterministic signature over the pattern dimensions.

    ``source_mix`` may be a string or an iterable of source names; it is
    normalised + sorted so order never changes the signature.
    """
    if isinstance(source_mix, (list, tuple, set, frozenset)):
        mix = ",".join(sorted(_norm(s) for s in source_mix))
    else:
        mix = _norm(source_mix)
    parts = [
        _norm(country),
        _norm(sector),
        _norm(signal_class),
        mix,
        _norm(market_regime),
        _norm(failure_type),
    ]
    raw = "|".join(parts).encode("utf-8")
    digest = hashlib.sha1(raw, usedforsecurity=False).hexdigest()
    return f"MBPAT_{digest[:20]}"


def signature_from_dict(d: Mapping[str, Any]) -> str:
    """Signature from a candidate/entry mapping (tolerant of missing keys)."""
    return compute_pattern_signature(
        country=d.get("country"),
        signal_class=d.get("signal_class"),
        source_mix=d.get("source_mix"),
        sector=d.get("sector"),
        market_regime=d.get("market_regime"),
        failure_type=d.get("failure_type"),
    )


def classify_outcome(entry: Mapping[str, Any]) -> str:
    """Return ``BAD`` / ``GOOD`` / ``NEUTRAL`` for a Moltbook entry."""
    oq = str(entry.get("outcome_quality") or "").strip().upper()
    if oq in BAD_OUTCOMES:
        return "BAD"
    if oq in GOOD_OUTCOMES:
        return "GOOD"
    return "NEUTRAL"


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1.0 - 1e-6)
    return math.log(p / (1.0 - p))


def moltbook_penalty_for_pattern(
    signature: str,
    entries: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compute the smoothed penalty for a pattern signature over entries."""
    n_bad = 0
    n_good = 0
    for e in entries:
        if signature_from_dict(e) != signature:
            continue
        verdict = classify_outcome(e)
        if verdict == "BAD":
            n_bad += 1
        elif verdict == "GOOD":
            n_good += 1
    n_total = n_bad + n_good
    if n_total == 0:
        return {
            "signature": signature,
            "moltbook_pattern_n": 0,
            "n_bad": 0,
            "n_good": 0,
            "moltbook_bad_rate": 0.0,
            "evidence_weight": 0.0,
            "moltbook_penalty": 0.0,
            "reason": NO_MATCH_REASON,
        }
    bad_rate = (n_bad + ALPHA) / (n_total + ALPHA + BETA)
    evidence_weight = min(1.0, n_total / N_MIN)
    penalty = LAMBDA * bad_rate * evidence_weight
    return {
        "signature": signature,
        "moltbook_pattern_n": n_total,
        "n_bad": n_bad,
        "n_good": n_good,
        "moltbook_bad_rate": round(bad_rate, 6),
        "evidence_weight": round(evidence_weight, 6),
        "moltbook_penalty": round(penalty, 6),
        "reason": "MOLTBOOK_PATTERN_MATCH",
    }


def apply_moltbook_adjustment(
    p_base: float,
    signature: str,
    entries: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Adjust ``p_base`` downward by the pattern penalty.  Advisory-only.

    Returns metadata (``moltbook_penalty``, ``moltbook_pattern_n``,
    ``moltbook_bad_rate``, ``moltbook_adjustment_applied``) plus the adjusted
    probability.  Never increases the probability; never unlocks execution.
    """
    block = moltbook_penalty_for_pattern(signature, list(entries))
    penalty = float(block["moltbook_penalty"])
    p_clamped = min(max(float(p_base), 0.0), 1.0)
    if penalty <= 0.0:
        p_adj = p_clamped
        applied = False
    else:
        p_adj = _sigmoid(_logit(p_clamped) - penalty)
        # Hard guarantee: penalty can only lower (or hold) the probability.
        p_adj = min(p_adj, p_clamped)
        applied = True

    stamps = advisory_safety_stamps()
    return {
        "p_base": round(p_clamped, 6),
        "p_adj": round(p_adj, 6),
        "moltbook_penalty": penalty,
        "moltbook_pattern_n": block["moltbook_pattern_n"],
        "moltbook_bad_rate": block["moltbook_bad_rate"],
        "moltbook_adjustment_applied": applied,
        "reason": block["reason"],
        # Safety: Moltbook is advisory-only and can never grant execution.
        "moltbook_can_unlock_execution": False,
        "execution_gate": stamps["execution_gate"],
        "broker_api_called": stamps["broker_api_called"],
        "ai_execution_count": stamps["ai_execution_count"],
    }


def adjust_admission(
    base_admission: str,
    penalty: float,
    *,
    threshold: float = DEFAULT_DOWNGRADE_THRESHOLD,
) -> str:
    """Downgrade a CANDIDATE advisory to WATCHLIST when the penalty is large.

    Conservative + monotone: only ever downgrades, never promotes.
    """
    if penalty >= threshold and str(base_admission).upper() in {
        "ADVISORY_CANDIDATE_FOR_HUMAN_REVIEW",
        "CANDIDATE",
    }:
        return "WATCHLIST"
    return base_admission


__all__ = [
    "ALPHA",
    "BETA",
    "N_MIN",
    "LAMBDA",
    "DEFAULT_DOWNGRADE_THRESHOLD",
    "BAD_OUTCOMES",
    "GOOD_OUTCOMES",
    "NO_MATCH_REASON",
    "compute_pattern_signature",
    "signature_from_dict",
    "classify_outcome",
    "moltbook_penalty_for_pattern",
    "apply_moltbook_adjustment",
    "adjust_admission",
]
