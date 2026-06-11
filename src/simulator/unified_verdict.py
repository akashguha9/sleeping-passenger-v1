"""The Stewards' Room: one unified verdict across all three engines.

Before this module, the physics simulator, the consent engine, and the
strategy layer produced three verdicts in three vocabularies with no
reconciliation — letting an operator act on whichever engine agreed with
them. The unified verdict closes that confirmation-bias hole:

    1. Every engine's verdict is mapped onto one conservatism scale.
    2. THE MOST CONSERVATIVE ENGINE WINS — a disagreement never averages
       up, it resolves down.
    3. Disagreement is information: every cross-engine contradiction is a
       first-class, cited output (the reflection's Contradiction Card:
       "market says X, data says Y"), and a wide split places the verdict
       under CONTRADICTION_HOLD pending human resolution.
    4. Strategy self-report passes cross-examination first; low
       credibility blocks upgrades but never blocks downgrades.

ADVISORY_ONLY. The unified state is a research classification.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.strategy.cross_exam import CrossExamReport

# Conservatism ranks (higher = more permissive review state). Interrupt
# states resolve outside the scale and always win.
LADDER_RANKS: dict[str, int] = {
    "reject": 0,
    "archive": 1,
    "watchlist": 2,
    "active_watch": 3,
    "buy_candidate": 4,
    "high_conviction_candidate": 5,
}
INTERRUPT_STATES = ("pit_stop", "black_flag")

STRATEGY_CLASS_RANKS: dict[str, int] = {
    "REJECT": 0,
    "AVOID": 0,
    "SHORT_RISK": 0,
    "THRESHOLD_NOT_CROSSED": 2,
    "NEEDS_MORE_EVIDENCE": 2,
    "EVENT_DRIVEN_ONLY": 2,
    "WATCHLIST": 2,
    "BUY": 4,
}

RANK_TO_STATE: dict[int, str] = {
    0: "reject", 1: "archive", 2: "watchlist",
    3: "active_watch", 4: "buy_candidate", 5: "high_conviction_candidate",
}

# A rank gap at or above this is a contradiction, not a nuance.
CONTRADICTION_RANK_GAP = 2


@dataclass(slots=True)
class Contradiction:
    """One cross-engine disagreement, fully cited."""

    kind: str
    severity: float
    left: str
    right: str
    resolution: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class UnifiedVerdict:
    """Single reconciled verdict across physics, consent, and strategy."""

    final_state: str
    state_before_unification: str
    unified_score_10: float
    contradiction_hold: bool
    engines_present: list[str] = field(default_factory=list)
    engine_states: dict[str, str] = field(default_factory=dict)
    contradictions: list[Contradiction] = field(default_factory=list)
    strategy_credibility: float | None = None
    strategy_upgrade_blocked: bool = False
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_unified_verdict(
    *,
    simulator_state: str,
    simulator_score_100: float,
    strategy_result: dict[str, Any] | None = None,
    cross_exam: CrossExamReport | None = None,
    consent_revenue_label: str = "",
    crash_gate_passed: bool = True,
) -> UnifiedVerdict:
    """Reconcile every engine into one conservative verdict."""
    engines = ["simulator"]
    engine_states = {"simulator": simulator_state}
    rationale: list[str] = []
    contradictions: list[Contradiction] = []

    sim_score_10 = max(min(simulator_score_100 / 10.0, 10.0), 0.0)

    # Interrupt states (driver black flag / pit stop) outrank everything.
    if simulator_state in INTERRUPT_STATES:
        return UnifiedVerdict(
            final_state=simulator_state,
            state_before_unification=simulator_state,
            unified_score_10=sim_score_10,
            contradiction_hold=False,
            engines_present=engines,
            engine_states=engine_states,
            rationale=[
                f"interrupt state '{simulator_state}' outranks all engines"
            ],
        )

    sim_rank = LADDER_RANKS.get(simulator_state, 0)
    unified_rank = sim_rank
    unified_score = sim_score_10

    if consent_revenue_label:
        engines.append("consent")
        engine_states["consent"] = consent_revenue_label

    strategy_decision = (strategy_result or {}).get("decision") or {}
    strategy_class = str(strategy_decision.get("decision_class", ""))
    credibility = cross_exam.credibility_factor if cross_exam else None
    upgrade_blocked = bool(cross_exam and not cross_exam.can_upgrade_unified_verdict)

    if strategy_class:
        engines.append("strategy")
        engine_states["strategy"] = strategy_class
        strategy_rank = STRATEGY_CLASS_RANKS.get(strategy_class, 0)
        strategy_score = float(
            strategy_decision.get("final_opportunity_score", 0.0)
        )

        # Asymmetric credibility: a discredited strategy section cannot
        # lift the verdict, but its conservatism still counts.
        if upgrade_blocked and strategy_rank > sim_rank:
            rationale.append(
                "strategy verdict more permissive than physics but its "
                f"self-report failed cross-examination (credibility "
                f"{credibility:.2f}) — upgrade blocked"
            )
            strategy_rank = sim_rank

        gap = abs(strategy_rank - sim_rank)
        if gap >= CONTRADICTION_RANK_GAP:
            contradictions.append(
                Contradiction(
                    kind="physics_vs_strategy",
                    severity=min(gap / 4.0, 1.0),
                    left=f"simulator: {simulator_state} "
                         f"({simulator_score_100:.1f}/100)",
                    right=f"strategy: {strategy_class} "
                          f"({strategy_score:.2f}/10)",
                    resolution="most conservative engine wins; verdict held "
                               "for human review",
                )
            )
        unified_rank = min(unified_rank, strategy_rank)
        unified_score = min(unified_score, strategy_score)

        if consent_revenue_label in ("fragile", "extractive_risk") and (
            strategy_class == "BUY"
        ):
            contradictions.append(
                Contradiction(
                    kind="consent_vs_strategy",
                    severity=0.9,
                    left=f"consent: revenue quality '{consent_revenue_label}'",
                    right="strategy: BUY",
                    resolution="extractive revenue blocks any BUY class",
                )
            )
            unified_rank = min(unified_rank, LADDER_RANKS["watchlist"])

        if not crash_gate_passed and strategy_class == "BUY":
            contradictions.append(
                Contradiction(
                    kind="crash_vs_strategy",
                    severity=0.9,
                    left="simulator: crash gate failed",
                    right="strategy: BUY",
                    resolution="the crash wall outranks opportunity",
                )
            )
            unified_rank = min(unified_rank, LADDER_RANKS["watchlist"])

        underground = (
            (strategy_result or {}).get("breakdown") or {}
        ).get("underground") or {}
        if underground.get("verdict") in ("BURIED_FOR_REASON", "ONE_HIT_NOISE") and (
            strategy_score >= 7.0
        ):
            contradictions.append(
                Contradiction(
                    kind="underground_vs_score",
                    severity=0.6,
                    left=f"underground: {underground.get('verdict')}",
                    right=f"strategy composite {strategy_score:.2f}/10",
                    resolution="buried-noise verdicts cap the composite's "
                               "meaning",
                )
            )

    hold = any(c.severity >= 0.5 for c in contradictions)
    final_state = RANK_TO_STATE[unified_rank]

    if final_state != simulator_state:
        rationale.append(
            f"conservative-wins: {simulator_state} -> {final_state} "
            f"(most conservative of {len(engines)} engine(s))"
        )
    if contradictions:
        rationale.append(
            f"{len(contradictions)} cross-engine contradiction(s) recorded — "
            "disagreement is information, not noise"
        )
    if hold:
        rationale.append(
            "CONTRADICTION_HOLD: engines disagree materially; human "
            "resolution required before any promotion"
        )
    if not rationale:
        rationale.append("engines agree; no unification adjustment needed")

    return UnifiedVerdict(
        final_state=final_state,
        state_before_unification=simulator_state,
        unified_score_10=round(unified_score, 4),
        contradiction_hold=hold,
        engines_present=engines,
        engine_states=engine_states,
        contradictions=contradictions,
        strategy_credibility=credibility,
        strategy_upgrade_blocked=upgrade_blocked,
        rationale=rationale,
    )
