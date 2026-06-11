"""Calibration bridge: simulator telemetry -> calibration evidence.

Bridges simulator decision telemetry (``src/simulator/telemetry.py``) into
the repo's existing calibration philosophy (``scripts/calibration_map.py``,
``scripts/calibration_recommendations.py``): metrics are computed with the
SAME Brier / ECE implementations the journal already trusts, and parameter
adjustments are RECOMMENDATION-ONLY — nothing here mutates production
defaults, and ``unsafe_to_autotune`` defaults to True.

    Brier:  BS  = (1/N) Σ (p_i - y_i)²
    ECE:    ECE = Σ_b (n_b / N) |acc(b) - conf(b)|
    Drift:  D_s = mean(error_s) - mean(error_global)
    Half-life proposal:  h_new = clamp(h_old · exp(-λ·D_s), h_min, h_max)
    Crash-beta proposal: β_new = clamp(β_old + η·residual, β_min, β_max)

Calibration modes (never conflated):
    insufficient_data — too few resolved rows to say anything
    fixture_replay    — rows include seeded/simulated data; numbers prove
                        the machinery, not the market
    empirical         — every row came from real caller decisions with
                        realized outcomes
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Reuse the journal's canonical metric implementations so simulator
# calibration can never drift from trade-log calibration.
from scripts.calibration_map import _brier as brier_score
from scripts.calibration_map import _ece as expected_calibration_error

from src.simulator.crash_simulator import DEFAULT_PAIR_BETA
from src.simulator.signal_tyres import BASE_HALF_LIFE_HOURS
from src.utils.math_utils import clip

MIN_SAMPLE_FOR_SIGNAL = 10
MIN_SAMPLE_FOR_AUTOTUNE = 50
ECE_AUTOTUNE_CEILING = 0.10

# Adjustment dynamics (doctrine defaults, conservative).
HALF_LIFE_LAMBDA = 0.5
HALF_LIFE_MIN_FACTOR = 0.25
HALF_LIFE_MAX_FACTOR = 4.0
CRASH_BETA_ETA = 0.2
CRASH_BETA_MIN = 0.1
CRASH_BETA_MAX = 1.5

SEGMENT_KEYS: tuple[str, ...] = (
    "circuit",
    "signal_compound",
    "exposure_class",
    "crash_density_bucket",
    "driver_license",
    "narrative_state",
)

MODE_INSUFFICIENT = "insufficient_data"
MODE_FIXTURE = "fixture_replay"
MODE_EMPIRICAL = "empirical"

ADVISORY_NOTE = (
    "ADVISORY_ONLY calibration report. Recommendations are never "
    "auto-applied; unsafe_to_autotune must be explicitly cleared by the "
    "safety gate AND a human before any default changes. Fixture-replay "
    "numbers validate the machinery, not the market."
)


@dataclass(slots=True)
class SegmentError:
    """Calibration error within one segment value."""

    segment_key: str
    segment_value: str
    sample_size: int
    mean_error: float
    mean_abs_error: float
    drift_vs_global: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class CalibrationBridgeReport:
    """Recommendation-only calibration output (matches required contract)."""

    sample_size: int
    calibration_mode: str
    brier: float | None
    ece: float | None
    global_mean_error: float | None
    error_by_segment: dict[str, list[SegmentError]] = field(default_factory=dict)
    recommended_adjustments: dict[str, Any] = field(default_factory=dict)
    unsafe_to_autotune: bool = True
    autotune_blockers: list[str] = field(default_factory=list)
    fixture_rows: int = 0
    empirical_rows: int = 0
    advisory_note: str = ADVISORY_NOTE

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["error_by_segment"] = {
            key: [s.to_dict() for s in segments]
            for key, segments in self.error_by_segment.items()
        }
        return payload


def _usable_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows that carry both a prediction and a resolved outcome."""
    usable = []
    for row in rows:
        predicted = row.get("predicted_probability")
        actual = row.get("actual_outcome_placeholder")
        if predicted is None or actual is None:
            continue
        if row.get("calibration_status") != "resolved":
            continue
        usable.append(row)
    return usable


def _mode(usable: list[dict[str, Any]]) -> tuple[str, int, int]:
    fixture = sum(1 for r in usable if r.get("data_source") == "fixture_replay")
    empirical = len(usable) - fixture
    if len(usable) < MIN_SAMPLE_FOR_SIGNAL:
        return MODE_INSUFFICIENT, fixture, empirical
    if fixture > 0:
        return MODE_FIXTURE, fixture, empirical
    return MODE_EMPIRICAL, fixture, empirical


def propose_half_life(h_old: float, drift: float) -> float:
    """h_new = clamp(h_old * exp(-λ * D_s), h_min, h_max).

    Positive drift (overconfident in this segment) shortens the half-life:
    signals there should age faster than doctrine assumed.
    """
    import math

    h_new = float(h_old) * math.exp(-HALF_LIFE_LAMBDA * float(drift))
    return clip(
        h_new, h_old * HALF_LIFE_MIN_FACTOR, h_old * HALF_LIFE_MAX_FACTOR
    )


def propose_crash_beta(beta_old: float, residual_interaction_error: float) -> float:
    """β_new = clamp(β_old + η * residual, β_min, β_max).

    Positive residual (outcomes worse than crash model predicted in crashy
    segments) raises interaction betas.
    """
    return clip(
        float(beta_old) + CRASH_BETA_ETA * float(residual_interaction_error),
        CRASH_BETA_MIN,
        CRASH_BETA_MAX,
    )


def autotune_safety_gate(
    *, calibration_mode: str, sample_size: int, ece: float | None
) -> tuple[bool, list[str]]:
    """Strict gate for clearing ``unsafe_to_autotune``.

    Returns (safe, blockers). Default posture is unsafe; every blocker must
    clear AND a human must still review (the bridge never applies changes).
    """
    blockers: list[str] = []
    if calibration_mode != MODE_EMPIRICAL:
        blockers.append(f"calibration_mode is '{calibration_mode}', not empirical")
    if sample_size < MIN_SAMPLE_FOR_AUTOTUNE:
        blockers.append(
            f"sample_size {sample_size} < {MIN_SAMPLE_FOR_AUTOTUNE} required"
        )
    if ece is None or ece > ECE_AUTOTUNE_CEILING:
        blockers.append(
            f"ECE {ece if ece is not None else 'unknown'} above "
            f"{ECE_AUTOTUNE_CEILING} ceiling"
        )
    return (not blockers), blockers


def build_calibration_report(
    telemetry_rows: list[dict[str, Any]],
) -> CalibrationBridgeReport:
    """Compute segment-level calibration from telemetry replay rows."""
    usable = _usable_rows(telemetry_rows)
    mode, fixture_rows, empirical_rows = _mode(usable)

    if not usable:
        return CalibrationBridgeReport(
            sample_size=0,
            calibration_mode=MODE_INSUFFICIENT,
            brier=None,
            ece=None,
            global_mean_error=None,
            autotune_blockers=["no resolved telemetry rows"],
        )

    predictions = [float(r["predicted_probability"]) for r in usable]
    outcomes = [float(r["actual_outcome_placeholder"]) for r in usable]
    errors = [p - y for p, y in zip(predictions, outcomes)]
    global_mean_error = sum(errors) / len(errors)
    brier = brier_score(predictions, outcomes)
    ece = expected_calibration_error(predictions, outcomes)

    # Per-segment drift.
    error_by_segment: dict[str, list[SegmentError]] = {}
    for key in SEGMENT_KEYS:
        groups: dict[str, list[float]] = {}
        for row, error in zip(usable, errors):
            value = str((row.get("segments") or {}).get(key, "") or "unknown")
            groups.setdefault(value, []).append(error)
        segments = []
        for value, segment_errors in sorted(groups.items()):
            mean_error = sum(segment_errors) / len(segment_errors)
            segments.append(
                SegmentError(
                    segment_key=key,
                    segment_value=value,
                    sample_size=len(segment_errors),
                    mean_error=mean_error,
                    mean_abs_error=sum(abs(e) for e in segment_errors)
                    / len(segment_errors),
                    drift_vs_global=mean_error - global_mean_error,
                )
            )
        error_by_segment[key] = segments

    # Recommendation-only adjustments.
    recommended: dict[str, Any] = {"applied": False, "auto_apply": False}
    half_life_proposals: dict[str, dict[str, float]] = {}
    for segment in error_by_segment.get("signal_compound", []):
        compound = segment.segment_value
        h_old = BASE_HALF_LIFE_HOURS.get(compound)
        if h_old is None or segment.sample_size < MIN_SAMPLE_FOR_SIGNAL:
            continue
        half_life_proposals[compound] = {
            "h_old_hours": h_old,
            "h_new_hours": propose_half_life(h_old, segment.drift_vs_global),
            "segment_drift": segment.drift_vs_global,
            "sample_size": segment.sample_size,
        }
    if half_life_proposals:
        recommended["half_life_hours"] = half_life_proposals

    crashy = [
        s
        for s in error_by_segment.get("crash_density_bucket", [])
        if s.segment_value in ("high", "extreme")
        and s.sample_size >= MIN_SAMPLE_FOR_SIGNAL
    ]
    if crashy:
        residual = sum(
            # Underprediction of failure in crashy buckets shows up as
            # positive error (predicted > realized).
            s.mean_error * s.sample_size
            for s in crashy
        ) / sum(s.sample_size for s in crashy)
        recommended["crash_pair_beta"] = {
            "beta_old": DEFAULT_PAIR_BETA,
            "beta_new": propose_crash_beta(DEFAULT_PAIR_BETA, residual),
            "residual_interaction_error": residual,
            "sample_size": sum(s.sample_size for s in crashy),
        }

    safe, blockers = autotune_safety_gate(
        calibration_mode=mode, sample_size=len(usable), ece=ece
    )

    return CalibrationBridgeReport(
        sample_size=len(usable),
        calibration_mode=mode,
        brier=brier,
        ece=ece,
        global_mean_error=global_mean_error,
        error_by_segment=error_by_segment,
        recommended_adjustments=recommended,
        unsafe_to_autotune=not safe,
        autotune_blockers=blockers,
        fixture_rows=fixture_rows,
        empirical_rows=empirical_rows,
    )
