"""Cross-examination of strategy self-report against pipeline evidence.

The strategy layer's inputs are caller-supplied judgements. Inside the
unified pipeline they stop being taken on faith: every claim that can be
checked against the rest of the payload IS checked.

    1. evidence_strength_overclaim — backhand evidence confidence must be
       carried by actual evidence volume (narrative mentions/origins,
       signals supplied, meal-box completeness) — the same humility law
       scrutineering applies to confirmation claims.
    2. hidden_asset_visibility_conflict — claiming giant-squid traits
       (hidden assets, low visibility) while also claiming high
       visibility elsewhere is self-contradiction.
    3. shock_overclaim — mechanism.probability_shock cannot exceed the
       prediction-market delta actually present in the payload.
    4. threshold_without_extinguisher — claiming the investability
       threshold is crossed while the meal box carries no invalidation.

Credibility is asymmetric by design: low credibility blocks the strategy
verdict from UPGRADING the unified verdict, never from downgrading it —
gaming the inputs can only make the system more conservative.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.simulator.scrutineering import compute_humility_index
from src.utils.math_utils import clamp01
from src.utils.validation_utils import coerce_float, normalized_score

CREDIBILITY_FLOOR_FOR_UPGRADES = 0.5
SHOCK_OVERCLAIM_SLACK = 0.30


@dataclass(slots=True)
class CrossExamViolation:
    """One self-report claim contradicted by the payload's own evidence."""

    check: str
    severity: float
    claimed: str
    contradicted_by: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class CrossExamReport:
    """Credibility verdict over the strategy section's self-report."""

    credibility_factor: float
    can_upgrade_unified_verdict: bool
    violations: list[CrossExamViolation] = field(default_factory=list)
    checks_run: int = 0
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _section(payload: dict[str, Any], *keys: str) -> dict[str, Any]:
    current: Any = payload
    for key in keys:
        current = current.get(key) if isinstance(current, dict) else None
    return dict(current) if isinstance(current, dict) else {}


def cross_examine_strategy(payload: dict[str, Any]) -> CrossExamReport:
    """Cross-examine the ``strategy`` section against the full payload."""
    strategy = _section(payload, "strategy")
    violations: list[CrossExamViolation] = []
    checks = 0

    # 1. Evidence-strength overclaim vs actual evidence volume.
    checks += 1
    claimed_evidence = normalized_score(
        _section(strategy, "backhand").get("evidence_strength", 0.0)
    )
    narrative = _section(payload, "narrative")
    meal = _section(payload, "meal_box")
    meal_complete = all(
        len(str(meal.get(k) or "").strip()) >= 10 or meal.get(k) is True
        for k in ("thesis", "evidence", "catalyst", "invalidation")
    )
    humility = compute_humility_index(
        claimed_confidence=claimed_evidence,
        mention_count=int(coerce_float(narrative.get("mention_count"))),
        independent_origin_count=int(
            coerce_float(narrative.get("independent_origin_count"))
        ),
        tyre_count=len(payload.get("signals", []) or []),
        meal_box_complete=meal_complete,
    )
    if claimed_evidence >= 0.5 and humility < 0.6:
        violations.append(
            CrossExamViolation(
                check="evidence_strength_overclaim",
                severity=clamp01(1.0 - humility),
                claimed=f"backhand evidence_strength {claimed_evidence:.2f}",
                contradicted_by=(
                    "payload evidence volume supports a humility ceiling of "
                    f"{humility:.2f} (mentions/origins/signals/meal box)"
                ),
            )
        )

    # 2. Hidden-asset traits vs claimed visibility.
    checks += 1
    traits = _section(strategy, "predator").get("traits") or {}
    hidden_claim = max(
        normalized_score(traits.get("hidden_assets", 0.0)),
        normalized_score(traits.get("low_visibility", 0.0)),
    )
    visibility_claims = [
        normalized_score(_section(strategy, "distribution").get("visibility", 0.0)),
        normalized_score(_section(strategy, "underground").get("visibility", 0.0)),
    ]
    visible = max(visibility_claims)
    if hidden_claim >= 0.6 and visible >= 0.6:
        violations.append(
            CrossExamViolation(
                check="hidden_asset_visibility_conflict",
                severity=clamp01(min(hidden_claim, visible)),
                claimed=f"hidden/low-visibility traits at {hidden_claim:.2f}",
                contradicted_by=f"visibility claimed elsewhere at {visible:.2f}",
            )
        )

    # 3. Probability-shock overclaim vs the actual prediction-market delta.
    checks += 1
    radar = _section(payload, "prediction_market")
    claimed_shock = normalized_score(
        _section(strategy, "mechanism").get("probability_shock", 0.0)
    )
    if radar:
        actual_delta = abs(
            coerce_float(radar.get("probability_after"))
            - coerce_float(radar.get("probability_before"))
        )
        if claimed_shock > actual_delta + SHOCK_OVERCLAIM_SLACK:
            violations.append(
                CrossExamViolation(
                    check="shock_overclaim",
                    severity=clamp01(claimed_shock - actual_delta),
                    claimed=f"mechanism probability_shock {claimed_shock:.2f}",
                    contradicted_by=(
                        f"prediction-market delta in payload is {actual_delta:.2f}"
                    ),
                )
            )

    # 4. Threshold crossed while carrying no fire extinguisher.
    checks += 1
    threshold_crossed = bool(
        _section(strategy, "node_payoff").get("threshold_crossed", False)
    )
    invalidation_present = (
        len(str(meal.get("invalidation") or "").strip()) >= 10
        or meal.get("invalidation") is True
    )
    if threshold_crossed and meal and not invalidation_present:
        violations.append(
            CrossExamViolation(
                check="threshold_without_extinguisher",
                severity=0.5,
                claimed="investability threshold_crossed=True",
                contradicted_by="meal box carries no invalidation rule",
            )
        )

    # Compound violations like scrutineering does: 1 - Π(1 - severity).
    survival = 1.0
    for violation in violations:
        survival *= 1.0 - clamp01(violation.severity)
    credibility = clamp01(survival)
    can_upgrade = credibility >= CREDIBILITY_FLOOR_FOR_UPGRADES

    rationale: list[str] = []
    if violations:
        rationale.append(
            f"{len(violations)} self-report claim(s) contradicted by the "
            f"payload's own evidence — credibility {credibility:.2f}"
        )
        if not can_upgrade:
            rationale.append(
                "strategy verdict may DOWNGRADE the unified verdict but may "
                "not upgrade it (asymmetric credibility rule)"
            )
    else:
        rationale.append("strategy self-report consistent with payload evidence")

    return CrossExamReport(
        credibility_factor=credibility,
        can_upgrade_unified_verdict=can_upgrade,
        violations=violations,
        checks_run=checks,
        rationale=rationale,
    )
