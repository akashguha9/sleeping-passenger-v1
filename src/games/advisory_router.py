"""Advisory Action Router: staged research actions, never instructions.

Maps the unified verdict (plus reality classification and contradiction
state) onto the staged advisory vocabulary:

    Reject · Watch · Research More · Paper Trade · Buy Candidate
    · Hold · Exit Candidate

Rules:
  * a contradiction hold always routes to Research More — disagreement
    demands research, not action;
  * tradeable-but-dangerous reality blocks investment-grade actions
    (Paper Trade / Buy Candidate) and explains why;
  * demotion from a previously held candidate state routes to
    Exit Candidate — leaving is also a decision;
  * interrupt states: pit_stop -> Hold (re-score first), black_flag ->
    Reject (driver is not allowed to act at all).

Every action is a research label for the advisory journal. ADVISORY_ONLY.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.games.reality_anchor import RealityAssessment

ADVISORY_ACTIONS: tuple[str, ...] = (
    "Reject", "Watch", "Research More", "Paper Trade", "Buy Candidate",
    "Hold", "Exit Candidate",
)

_STATE_TO_ACTION: dict[str, str] = {
    "reject": "Reject",
    "archive": "Watch",
    "watchlist": "Watch",
    "active_watch": "Research More",
    "buy_candidate": "Paper Trade",
    "high_conviction_candidate": "Buy Candidate",
    "pit_stop": "Hold",
    "black_flag": "Reject",
}

_CANDIDATE_STATES = ("buy_candidate", "high_conviction_candidate")
_INVESTMENT_ACTIONS = ("Paper Trade", "Buy Candidate")


@dataclass(slots=True)
class AdvisoryAction:
    """One staged, explained research action."""

    action: str
    explanation: str
    downgraded_from: str = ""
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def route_advisory_action(
    *,
    final_state: str,
    contradiction_hold: bool = False,
    previous_state: str | None = None,
    reality: RealityAssessment | None = None,
    calibration_risk_severe: bool = False,
) -> AdvisoryAction:
    """Route the verdict to a staged advisory action with its reasons."""
    base_action = _STATE_TO_ACTION.get(str(final_state), "Reject")
    rationale: list[str] = [f"ladder state '{final_state}' -> {base_action}"]

    # Exit detection: a previously held candidate demoted below candidate
    # grade is an exit question, not a watch question.
    if (
        previous_state in _CANDIDATE_STATES
        and final_state not in _CANDIDATE_STATES
        and final_state not in ("pit_stop", "black_flag")
    ):
        rationale.append(
            f"demoted from '{previous_state}' — leaving is also a decision"
        )
        return AdvisoryAction(
            action="Exit Candidate",
            explanation=(
                f"Previously {previous_state}, now {final_state}: review the "
                "position for exit. ADVISORY_ONLY — a research label, not an "
                "instruction."
            ),
            downgraded_from=base_action,
            rationale=rationale,
        )

    if contradiction_hold:
        rationale.append(
            "contradiction hold active — disagreement demands research, "
            "not action"
        )
        return AdvisoryAction(
            action="Research More",
            explanation=(
                "Engines disagree materially (CONTRADICTION_HOLD): resolve "
                "the cited contradictions before any staged action. "
                "ADVISORY_ONLY."
            ),
            downgraded_from=base_action if base_action != "Research More" else "",
            rationale=rationale,
        )

    if calibration_risk_severe and base_action in _INVESTMENT_ACTIONS:
        rationale.append(
            "dice audit reports severe calibration risk (overconfident or "
            "loaded) on a load-bearing source"
        )
        return AdvisoryAction(
            action="Research More",
            explanation=(
                "A dice audit flags severe calibration risk on the evidence "
                "behind this verdict: the assumed uncertainty profile has "
                "not matched realized outcomes. Investment-grade actions "
                "are blocked until the source is re-audited. ADVISORY_ONLY."
            ),
            downgraded_from=base_action,
            rationale=rationale,
        )

    if (
        reality is not None
        and reality.classification == "tradeable_but_dangerous"
        and base_action in _INVESTMENT_ACTIONS
    ):
        rationale.append(
            "reality check: tradeability is not investability — "
            f"investment {reality.investment_score:.1f}/10 vs tradeability "
            f"{reality.tradeability_score:.1f}/10"
        )
        return AdvisoryAction(
            action="Research More",
            explanation=(
                "Score earned an investment-grade state, but the reality "
                "layer classifies this as tradeable-but-dangerous "
                f"(simulacra: {reality.simulacra_layer}). Investment-grade "
                "actions are blocked; study the danger score first. "
                "ADVISORY_ONLY."
            ),
            downgraded_from=base_action,
            rationale=rationale,
        )

    return AdvisoryAction(
        action=base_action,
        explanation=(
            f"{base_action}: staged research action for state "
            f"'{final_state}'. ADVISORY_ONLY — a research label, not an "
            "instruction."
        ),
        rationale=rationale,
    )
