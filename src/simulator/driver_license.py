"""Driver license penalty system: the user is part of the risk model.

Danger points decay with a half-life:

    Danger Points(t) = initial_points * 0.5 ** (days_since / penalty_half_life)

Discipline:

    Driver Discipline Score =
        thesis_logging + invalidation_compliance + sizing_discipline
        + confirmation_patience + replay_completion + calibration_honesty
        - danger_points - override_abuse - revenge_flags

A good stock score is capped by bad driver behavior via the permission
multiplier in [0, 1]. This gates journal promotion language only — it never
places or blocks real orders (there is no execution path).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clamp01
from src.utils.validation_utils import normalized_score

PENALTY_HALF_LIFE_DAYS = 30.0

LICENSE_LEVELS: tuple[str, ...] = (
    "learner",
    "rookie",
    "club_racer",
    "pro_am",
    "pro_driver",
    "engineer",
    "team_principal",
)

VIOLATION_POINTS: dict[str, float] = {
    "chasing_stale_signal": 8.0,
    "oversizing_under_crash_risk": 12.0,
    "ignoring_thesis_damage": 10.0,
    "no_thesis_no_helmet": 15.0,
    "tailgating_hype": 6.0,
    "red_light_jump": 10.0,
    "wrong_signal_compound": 6.0,
    "driving_through_dirty_air": 5.0,
    "revenge_trading": 20.0,
    "override_abuse": 12.0,
}

# (max_points_exclusive, status, permission_multiplier)
_STATUS_BANDS: tuple[tuple[float, str, float], ...] = (
    (10.0, "clean", 1.0),
    (25.0, "caution", 0.85),
    (40.0, "warning", 0.65),
    (60.0, "probation", 0.40),
    (80.0, "suspended", 0.15),
    (float("inf"), "black_flag", 0.0),
)


@dataclass(slots=True)
class Violation:
    """One recorded dangerous behavior."""

    violation_type: str
    days_since: float
    initial_points: float
    decayed_points: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class DriverState:
    """Current discipline state of the human driver."""

    license_level: str
    danger_points: float
    status: str
    permission_multiplier: float
    discipline_score: float
    violations: list[Violation] = field(default_factory=list)
    black_flag: bool = False
    reason_codes: list[str] = field(default_factory=list)
    raw_components: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def decayed_violation_points(
    violation_type: str,
    days_since: float,
    *,
    penalty_half_life_days: float = PENALTY_HALF_LIFE_DAYS,
) -> float:
    """Points for one violation after exponential decay."""
    initial = VIOLATION_POINTS.get(str(violation_type), 5.0)
    days = max(float(days_since), 0.0)
    half_life = max(float(penalty_half_life_days), 1e-9)
    return initial * 0.5 ** (days / half_life)


def status_for_points(points: float) -> tuple[str, float]:
    """Map total danger points to (status, permission_multiplier)."""
    for ceiling, status, multiplier in _STATUS_BANDS:
        if points < ceiling:
            return status, multiplier
    return "black_flag", 0.0  # pragma: no cover — inf ceiling always matches


def license_rank(level: str) -> int:
    """Ordinal rank of a license level (unknown levels rank lowest)."""
    try:
        return LICENSE_LEVELS.index(str(level).strip().lower())
    except ValueError:
        return 0


def license_meets_circuit(license_level: str, required_license: str) -> bool:
    """Trade-review allowed only if the license covers the circuit."""
    return license_rank(license_level) >= license_rank(required_license)


def score_driver(
    *,
    license_level: str = "learner",
    violations: list[dict[str, float | str]] | None = None,
    thesis_logging_quality: float = 0.0,
    invalidation_compliance: float = 0.0,
    position_sizing_discipline: float = 0.0,
    confirmation_patience: float = 0.0,
    replay_audit_completion: float = 0.0,
    calibration_honesty: float = 0.0,
    override_abuse_level: float = 0.0,
    revenge_trading_flags: int = 0,
    penalty_half_life_days: float = PENALTY_HALF_LIFE_DAYS,
) -> DriverState:
    """Score the driver. Violations are ``{"type": str, "days_since": float}``.

    Discipline score is on a 0–100 scale: six process components worth up
    to ~16.7 each, minus danger points, override abuse, and revenge flags.
    """
    records: list[Violation] = []
    for raw in violations or []:
        vtype = str(raw.get("type", "unknown"))
        days = float(raw.get("days_since", 0.0) or 0.0)
        decayed = decayed_violation_points(
            vtype, days, penalty_half_life_days=penalty_half_life_days
        )
        records.append(
            Violation(
                violation_type=vtype,
                days_since=max(days, 0.0),
                initial_points=VIOLATION_POINTS.get(vtype, 5.0),
                decayed_points=decayed,
            )
        )

    danger_points = sum(v.decayed_points for v in records)
    status, multiplier = status_for_points(danger_points)

    process_components = {
        "thesis_logging_quality": normalized_score(thesis_logging_quality),
        "invalidation_compliance": normalized_score(invalidation_compliance),
        "position_sizing_discipline": normalized_score(position_sizing_discipline),
        "confirmation_patience": normalized_score(confirmation_patience),
        "replay_audit_completion": normalized_score(replay_audit_completion),
        "calibration_honesty": normalized_score(calibration_honesty),
    }
    process_score = sum(process_components.values()) / len(process_components) * 100.0
    override_penalty = normalized_score(override_abuse_level) * 15.0
    revenge_penalty = max(int(revenge_trading_flags), 0) * 10.0
    discipline = max(
        process_score - danger_points - override_penalty - revenge_penalty, 0.0
    )

    black_flag = status == "black_flag" or revenge_trading_flags >= 3
    if black_flag:
        status = "black_flag"
        multiplier = 0.0

    reasons: list[str] = [f"DRIVER_STATUS_{status.upper()}"]
    if black_flag:
        reasons.append("BLACK_FLAG_NO_ACTION_PERMITTED")
    if danger_points >= 25.0:
        reasons.append("DANGER_POINTS_ELEVATED")
    if normalized_score(override_abuse_level) >= 0.5:
        reasons.append("OVERRIDE_ABUSE")
    if revenge_trading_flags > 0:
        reasons.append("REVENGE_TRADING_FLAGGED")
    if discipline >= 70.0 and not records:
        reasons.append("DISCIPLINED_DRIVER")

    return DriverState(
        license_level=str(license_level).strip().lower(),
        danger_points=danger_points,
        status=status,
        permission_multiplier=clamp01(multiplier),
        discipline_score=discipline,
        violations=records,
        black_flag=black_flag,
        reason_codes=reasons,
        raw_components={
            **process_components,
            "danger_points": danger_points,
            "override_penalty": override_penalty,
            "revenge_penalty": revenge_penalty,
        },
    )
