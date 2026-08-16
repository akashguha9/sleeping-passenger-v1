"""Regime-transition sprint — titration / buffer / threshold engine.

Answers ONE question (reflection §42–51):

    How much contradictory-to-the-old-regime evidence has ACCUMULATED,
    how much absorptive buffer remains, and how close is the system to a
    nonlinear threshold?

Distinct from ``tension_accumulation_tracker.py`` (TAT tracks
prediction-market momentum vs resolution for ENTRY timing) — this module
accumulates heterogeneous EVIDENCE with decay, contradiction, duplicate
suppression and source-independence weighting, then divides by inertia +
remaining buffer to get Threshold Pressure.

Key honesty rules:
- duplicate evidence (same normalized content) accumulates ZERO extra
  pressure — the last headline never gets all the causal credit twice;
- repeated evidence from one source_id gets geometrically diminishing
  weight (independence discipline, reflection failure 17);
- volatility/sensitivity spikes WITHOUT accumulated-pressure support are
  labeled UNCONFIRMED_NOISE (reflection failure 12) — never a signal;
- all thresholds are documented UNCALIBRATED defaults.  Advisory-only.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
REAL_MONEY = "PROHIBITED"
CALIBRATION_STATUS = "UNCALIBRATED_DEFAULTS"
OK = "OK"
UNKNOWN = "UNKNOWN"

DEFAULT_DECAY_LAMBDA = 0.97       # per-day retention of accumulated pressure
_INDEPENDENCE_FACTOR = 0.5        # repeat items from same source halve
_STALE_EVIDENCE_DAYS = 90         # older than this contributes ~0 anyway via decay

# Threshold-pressure bands (uncalibrated defaults).
TP_LOW = "LOW"
TP_ELEVATED = "ELEVATED"
TP_CRITICAL_ZONE = "CRITICAL_ZONE"
_TP_BANDS = ((0.5, TP_LOW), (1.2, TP_ELEVATED))

UNCONFIRMED_NOISE = "UNCONFIRMED_NOISE"
SENSITIVITY_RISING = "SENSITIVITY_RISING_WITH_EVIDENCE"


@dataclass
class EvidenceDrop:
    """One titration 'drop'.

    ``direction`` +1 supports the NEW regime, -1 supports the OLD regime
    (contradictory evidence subtracts).  ``weight``/``confidence`` in [0,1].
    """

    day: int
    weight: float
    direction: int
    source_id: str
    content: str
    confidence: float = 1.0


def _content_key(content: str) -> str:
    norm = re.sub(r"\s+", " ", content.strip().lower())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def accumulate_evidence(drops: list[EvidenceDrop], *,
                        as_of_day: int,
                        decay_lambda: float = DEFAULT_DECAY_LAMBDA,
                        ) -> dict[str, Any]:
    """Accumulated pressure A_t with decay, dedup and independence weighting.

    A_t = Σ_i λ^(as_of_day − day_i) · w_i · dir_i · conf_i · indep_i
    (equivalent to the recursive λA_{t-1} + Σ w·e form, computed directly).
    """
    if not 0.0 < decay_lambda <= 1.0:
        raise ValueError("decay_lambda must be in (0, 1]")
    seen_content: set[str] = set()
    source_counts: dict[str, int] = {}
    duplicates = 0
    stale = 0
    contributions: list[dict[str, Any]] = []
    pressure = 0.0
    for d in sorted(drops, key=lambda d: d.day):
        if d.day > as_of_day:
            continue  # future-data leakage guard
        key = _content_key(d.content)
        if key in seen_content:
            duplicates += 1
            contributions.append({"day": d.day, "source_id": d.source_id,
                                  "contribution": 0.0, "reason": "DUPLICATE"})
            continue
        seen_content.add(key)
        n_prior = source_counts.get(d.source_id, 0)
        source_counts[d.source_id] = n_prior + 1
        indep = _INDEPENDENCE_FACTOR ** n_prior
        age = as_of_day - d.day
        if age > _STALE_EVIDENCE_DAYS:
            stale += 1
        decay = decay_lambda ** age
        c = (max(0.0, min(1.0, d.weight))
             * (1 if d.direction >= 0 else -1)
             * max(0.0, min(1.0, d.confidence)) * indep * decay)
        pressure += c
        contributions.append({"day": d.day, "source_id": d.source_id,
                              "contribution": round(c, 6),
                              "independence_weight": round(indep, 4),
                              "decay_weight": round(decay, 4)})
    return {
        "status": OK if contributions else UNKNOWN,
        "accumulated_pressure": round(pressure, 6),
        "as_of_day": as_of_day,
        "drops_considered": len(contributions),
        "duplicates_suppressed": duplicates,
        "stale_drops": stale,
        "independent_sources": len(source_counts),
        "contributions": contributions,
        "decay_lambda": decay_lambda,
        "calibration_status": CALIBRATION_STATUS,
    }


@dataclass
class BufferItem:
    """One absorptive buffer (inventory, reserves, spare capacity, cash…)."""

    kind: str
    capacity: float          # [0, 1] relative absorptive capacity
    evidence_ref: str | None
    confidence: float = 1.0


def buffer_state(buffers: list[BufferItem],
                 absorbed_stress: float = 0.0) -> dict[str, Any]:
    """BufferCapacityScore [0, 100] and remaining buffer after stress.

    Uncited buffers are dropped (cite-or-drop).  ``absorbed_stress`` is the
    cumulative stress already soaked up, in the same [0, ~n] units as the
    summed capacities.
    """
    cited = [b for b in buffers if b.evidence_ref]
    dropped = len(buffers) - len(cited)
    if not cited:
        return {"status": UNKNOWN, "buffer_capacity_score": None,
                "remaining_buffer": None, "dropped_uncited": dropped}
    initial = sum(max(0.0, min(1.0, b.capacity))
                  * max(0.0, min(1.0, b.confidence)) for b in cited)
    remaining = max(0.0, initial - max(0.0, absorbed_stress))
    score = 100.0 * (1.0 - math.exp(-1.2 * initial))
    return {"status": OK,
            "buffer_capacity_score": round(score, 2),
            "initial_buffer": round(initial, 4),
            "remaining_buffer": round(remaining, 4),
            "depletion_fraction": round(1.0 - (remaining / initial), 4)
            if initial > 0 else None,
            "dropped_uncited": dropped}


def threshold_pressure(*, accumulated: dict[str, Any],
                       composite_inertia_0_100: float | None,
                       buffer: dict[str, Any]) -> dict[str, Any]:
    """TP = AccumulatedPressure / (Inertia + RemainingBuffer)  (reflection §51).

    Inertia and buffer must be KNOWN — an unknown denominator yields an
    UNKNOWN TP, not an inflated one.
    """
    if accumulated.get("status") != OK:
        return {"status": UNKNOWN, "threshold_pressure": None,
                "reason": "no accumulated evidence"}
    if composite_inertia_0_100 is None or buffer.get("status") != OK:
        return {"status": UNKNOWN, "threshold_pressure": None,
                "reason": "inertia or buffer unavailable"}
    pressure = max(0.0, accumulated["accumulated_pressure"])
    denom = (composite_inertia_0_100 / 100.0) + buffer["remaining_buffer"] + 0.10
    tp = pressure / denom
    band = TP_CRITICAL_ZONE
    for ceiling, label in _TP_BANDS:
        if tp < ceiling:
            band = label
            break
    return {"status": OK, "threshold_pressure": round(tp, 4), "band": band,
            "numerator_pressure": round(pressure, 4),
            "denominator": round(denom, 4),
            "calibration_status": CALIBRATION_STATUS}


def threshold_sensitivity_diagnostic(
    observations: list[tuple[float, float]],
    *,
    accumulated_pressure: float | None,
) -> dict[str, Any]:
    """DIAGNOSTIC ONLY — ΔPrice per ΔInformation trend (reflection §45–46).

    ``observations`` is a chronological list of (delta_information,
    delta_price) pairs.  A rising ratio WITHOUT accumulated-pressure
    support is labeled UNCONFIRMED_NOISE — volatility alone never proves
    threshold proximity.  Output must never feed a ranking directly.
    """
    ratios = [abs(dp) / abs(di) for di, dp in observations if abs(di) > 1e-9]
    if len(ratios) < 2:
        return {"status": UNKNOWN, "diagnostic_only": True,
                "sensitivity_trend": None}
    half = len(ratios) // 2
    early = sum(ratios[:half]) / half
    late = sum(ratios[half:]) / (len(ratios) - half)
    rising = late > early * 1.5
    if rising and (accumulated_pressure is not None
                   and accumulated_pressure > 0.5):
        label = SENSITIVITY_RISING
    elif rising:
        label = UNCONFIRMED_NOISE
    else:
        label = "STABLE_SENSITIVITY"
    return {"status": OK, "diagnostic_only": True,
            "sensitivity_early": round(early, 4),
            "sensitivity_late": round(late, 4),
            "label": label,
            "volatility_alone_insufficient": True}
