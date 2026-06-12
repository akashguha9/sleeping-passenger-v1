"""Dice Audit Loop: the model tests whether its own dice were honest.

The dice profiles in ``dice_profiles.py`` are ASSUMPTIONS. This module
points the calibration machinery inward: resolved decision rows
(predicted confidence + realized outcome, e.g. from the wind tunnel or
the simulator store) are compared against what each assumed profile
promised, and drifted assumptions get recommendation-only adjustments.

    precision assumed, realized error high  -> downgrade toward rounded
    rounded assumed, calibration stable     -> keep (or upgrade note)
    extreme one-sided gap                   -> loaded_suspected, cap
    thin sample                             -> require_more_data, no verdict

Per-game calibration summaries group the same rows by the
``dominant_game`` telemetry segment — the first empirical test of "the
same signal means different things in different games."

All outputs are recommendation-only, mirroring the calibration bridge:
nothing here mutates a profile; a human reviews the audit. ADVISORY_ONLY.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Reuse the journal's canonical Brier so dice audits can never disagree
# with trade-log calibration arithmetic.
from scripts.calibration_map import _brier as brier_score

from src.utils.math_utils import clamp01
from src.utils.validation_utils import coerce_float

MIN_AUDIT_SAMPLE = 20
OVERCONFIDENT_GAP = 0.15
LOADED_GAP = 0.30

# How much EXCESS Brier each profile tolerates above the calibrated
# baseline. Raw Brier contains irreducible variance — a perfectly
# calibrated 0.7 forecaster scores p(1-p) = 0.21 by construction — so the
# audit judges brier - mean(p*(1-p)), never the raw number.
PROFILE_EXCESS_BRIER_TOLERANCE: dict[str, float] = {
    "precision": 0.05,
    "d4": 0.08,
    "d6": 0.10,
    "d10": 0.15,
    "d20": 0.20,
    "d100": 0.08,
    "rounded": 0.20,
    "loaded_possible": 0.20,
    "non_transitive": 0.20,
}

AUDIT_STATUSES: tuple[str, ...] = (
    "calibrated", "overconfident", "underconfident", "drifted",
    "loaded_suspected", "require_more_data",
)


@dataclass(slots=True)
class DiceAuditResult:
    """Verdict on one assumed dice profile vs its realized outcomes."""

    assumed_profile: str
    sample_size: int
    average_confidence: float
    realized_hit_rate: float
    confidence_gap: float
    brier: float
    calibration_status: str
    recommended_adjustment: str
    confidence_multiplier: float
    audit_notes: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def audit_dice_profile(
    rows: list[dict[str, Any]],
    *,
    assumed_profile: str,
    min_sample: int = MIN_AUDIT_SAMPLE,
) -> DiceAuditResult:
    """Audit one profile. Rows: ``{"confidence" 0–1, "outcome" 0/1}``.

    The audit never overreacts to thin samples, and adjustments are
    recommendations — the assumed profile is not mutated here.
    """
    profile = str(assumed_profile).strip().lower()
    usable = [
        (clamp01(coerce_float(r.get("confidence"))),
         clamp01(coerce_float(r.get("outcome"))))
        for r in rows or []
        if r.get("confidence") is not None and r.get("outcome") is not None
    ]
    n = len(usable)
    if n < min_sample:
        return DiceAuditResult(
            assumed_profile=profile,
            sample_size=n,
            average_confidence=0.0,
            realized_hit_rate=0.0,
            confidence_gap=0.0,
            brier=0.0,
            calibration_status="require_more_data",
            recommended_adjustment="require_more_data",
            confidence_multiplier=1.0,
            audit_notes=[
                f"{n} resolved row(s) < {min_sample} floor — no verdict; "
                "thin samples must not move assumptions"
            ],
        )

    confidences = [c for c, _ in usable]
    outcomes = [o for _, o in usable]
    avg_confidence = sum(confidences) / n
    hit_rate = sum(outcomes) / n
    gap = avg_confidence - hit_rate  # positive = overconfident
    brier = brier_score(confidences, outcomes)
    # Calibrated baseline: the Brier a PERFECT forecaster with these
    # stated probabilities would still incur (irreducible variance).
    baseline = sum(c * (1.0 - c) for c in confidences) / n
    excess_brier = max(brier - baseline, 0.0)
    tolerance = PROFILE_EXCESS_BRIER_TOLERANCE.get(profile, 0.15)

    notes: list[str] = [
        f"n={n}: avg confidence {avg_confidence:.3f} vs realized "
        f"{hit_rate:.3f} (gap {gap:+.3f}); excess Brier "
        f"{excess_brier:.3f} (raw {brier:.3f} - baseline {baseline:.3f}) "
        f"vs '{profile}' tolerance {tolerance:.2f}",
    ]

    if abs(gap) >= LOADED_GAP:
        status = "loaded_suspected"
        adjustment = "cap_confidence"
        multiplier = 0.25
        notes.append(
            "extreme one-sided gap — the die behaves loaded; confidence "
            "capped pending investigation of who benefits"
        )
    elif gap >= OVERCONFIDENT_GAP:
        status = "overconfident"
        adjustment = "downgrade"
        multiplier = clamp01(1.0 - 2.0 * gap)
        notes.append(
            f"systematically overconfident — recommend downgrading "
            f"'{profile}' toward a noisier profile"
        )
    elif gap <= -OVERCONFIDENT_GAP:
        status = "underconfident"
        adjustment = "upgrade"
        multiplier = 1.0
        notes.append(
            "systematically underconfident — the source is better than "
            "assumed; an upgrade may be reviewed (never auto-applied)"
        )
    elif excess_brier > tolerance:
        status = "drifted"
        adjustment = "downgrade"
        multiplier = clamp01(1.0 - (excess_brier - tolerance))
        notes.append(
            f"excess Brier beyond what '{profile}' promised — "
            "calibration drift without a one-sided gap"
        )
    else:
        status = "calibrated"
        adjustment = "keep"
        multiplier = 1.0
        notes.append("assumption holds against realized outcomes")

    notes.append("recommendation-only: no profile is mutated by an audit")
    return DiceAuditResult(
        assumed_profile=profile,
        sample_size=n,
        average_confidence=avg_confidence,
        realized_hit_rate=hit_rate,
        confidence_gap=gap,
        brier=brier,
        calibration_status=status,
        recommended_adjustment=adjustment,
        confidence_multiplier=multiplier,
        audit_notes=notes,
    )


@dataclass(slots=True)
class BucketAudit:
    """One d100 probability bucket vs realized hit rate."""

    lower: float
    upper: float
    count: int
    average_confidence: float
    realized_hit_rate: float
    gap: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def audit_d100_buckets(
    rows: list[dict[str, Any]],
    *,
    bucket_edges: tuple[float, ...] = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0001),
) -> list[BucketAudit]:
    """Bucketed reliability audit for probability-engine (d100) sources."""
    audits: list[BucketAudit] = []
    pairs = [
        (clamp01(coerce_float(r.get("confidence"))),
         clamp01(coerce_float(r.get("outcome"))))
        for r in rows or []
        if r.get("confidence") is not None and r.get("outcome") is not None
    ]
    for lower, upper in zip(bucket_edges, bucket_edges[1:]):
        bucket = [(c, o) for c, o in pairs if lower <= c < upper]
        if not bucket:
            continue
        avg_c = sum(c for c, _ in bucket) / len(bucket)
        hit = sum(o for _, o in bucket) / len(bucket)
        audits.append(BucketAudit(
            lower=lower, upper=min(upper, 1.0), count=len(bucket),
            average_confidence=avg_c, realized_hit_rate=hit,
            gap=avg_c - hit,
        ))
    return audits


@dataclass(slots=True)
class GameCalibrationSummary:
    """Calibration verdict for one dominant-game telemetry segment."""

    dominant_game: str
    sample_size: int
    average_confidence: float
    realized_hit_rate: float
    calibration_error: float
    recommendation: str
    audit_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def summarize_game_calibration(
    telemetry_rows: list[dict[str, Any]],
    *,
    min_sample: int = 10,
) -> list[GameCalibrationSummary]:
    """Group resolved telemetry by dominant_game; measure per-game drift.

    Rows are the simulator's telemetry shape (``predicted_probability``,
    ``actual_outcome_placeholder``, ``segments.dominant_game``). The
    first empirical test of game-conditional interpretation.
    """
    groups: dict[str, list[tuple[float, float]]] = {}
    for row in telemetry_rows or []:
        predicted = row.get("predicted_probability")
        actual = row.get("actual_outcome_placeholder")
        if predicted is None or actual is None:
            continue
        if row.get("calibration_status") != "resolved":
            continue
        game = str((row.get("segments") or {}).get("dominant_game") or "")
        if not game:
            continue
        groups.setdefault(game, []).append(
            (clamp01(float(predicted)), clamp01(float(actual)))
        )

    summaries: list[GameCalibrationSummary] = []
    for game, pairs in sorted(groups.items()):
        n = len(pairs)
        avg_c = sum(c for c, _ in pairs) / n
        hit = sum(o for _, o in pairs) / n
        error = avg_c - hit
        if n < min_sample:
            recommendation = "require_more_data"
            notes = [f"n={n} below {min_sample} — no per-game verdict yet"]
        elif error >= OVERCONFIDENT_GAP:
            recommendation = "treat_game_signals_as_overconfident"
            notes = [f"'{game}' decisions run {error:+.3f} overconfident"]
        elif error <= -OVERCONFIDENT_GAP:
            recommendation = "game_signals_underconfident"
            notes = [f"'{game}' decisions run {error:+.3f} underconfident"]
        else:
            recommendation = "stable"
            notes = [f"'{game}' calibration stable (gap {error:+.3f})"]
        summaries.append(GameCalibrationSummary(
            dominant_game=game,
            sample_size=n,
            average_confidence=avg_c,
            realized_hit_rate=hit,
            calibration_error=error,
            recommendation=recommendation,
            audit_notes=notes,
        ))
    return summaries
