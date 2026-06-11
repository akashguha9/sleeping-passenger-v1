"""Final Decision Engine + strategy orchestrator (advisory research only).

Runs the full strategy chain on one payload:

    mechanism -> doctrine filter -> predator node -> competition density
    -> node payoff matrix -> chess promotion -> underground -> distribution
    -> backhand defence -> final research verdict

Final Opportunity Score (0–10) is a weighted composite; HARD RULES cap
the verdict regardless of score — a high score cannot override an
unresolved existential bear case, an uncrossed threshold, a missing
mechanism, terrible casino odds, prey-like deterioration, or fake
outliers. Verdict labels are RESEARCH CLASSIFICATIONS for the journal,
never instructions; the lifecycle (Match OS) record maps doctrine,
battlefield, recalibration hooks, and forensic-learning surfaces.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.strategy import STRATEGY_ADVISORY_NOTE, STRATEGY_DOCTRINE
from src.strategy.backhand import BackhandAssessment, assess_backhand_defence
from src.strategy.chess_promotion import ChessStateAssessment, assess_chess_state
from src.strategy.competition_density import (
    CompetitionAssessment,
    assess_competition_density,
)
from src.strategy.distribution import DistributionAssessment, assess_distribution
from src.strategy.doctrine_filter import DoctrineVerdict, apply_doctrine_filter
from src.strategy.mechanism import MechanismAssessment, assess_mechanism
from src.strategy.node_payoff import NodePayoffMatrix, evaluate_node_payoff
from src.strategy.predator_nodes import NodeClassification, classify_predator_node
from src.strategy.underground import UndergroundAssessment, assess_underground
from src.utils.math_utils import clip
from src.utils.validation_utils import coerce_float, normalized_score

DECISION_CLASSES: tuple[str, ...] = (
    "BUY",
    "WATCHLIST",
    "REJECT",
    "AVOID",
    "SHORT_RISK",
    "NEEDS_MORE_EVIDENCE",
    "EVENT_DRIVEN_ONLY",
    "THRESHOLD_NOT_CROSSED",
)

# Component weights for the 0–10 composite.
WEIGHTS: dict[str, float] = {
    "base_quality": 0.10,
    "narrative_mechanism": 0.10,
    "value_chain_position": 0.08,
    "distribution_intelligence": 0.10,
    "predator_node_fit": 0.08,
    "node_payoff_matrix": 0.14,
    "dynamic_table": 0.10,
    "underground_breakout": 0.06,
    "backhand_defence": 0.14,
    "competition_density": 0.06,
    "inflection": 0.04,
}
PENALTY_WEIGHTS: dict[str, float] = {
    "fragility_penalty": 1.5,
    "unresolved_bear_penalty": 2.0,
    "hype_penalty": 1.0,
    "evidence_weakness_penalty": 1.0,
    "fake_outlier_penalty": 1.0,
}


def score_band(score: float) -> str:
    if score >= 8.5:
        return "high_conviction_candidate"
    if score >= 7.0:
        return "strong_watchlist_staged_entry"
    if score >= 5.5:
        return "monitor_only"
    if score >= 4.0:
        return "weak_unclear"
    return "reject_avoid"


@dataclass(slots=True)
class StrategyDecision:
    """Final research verdict with full transparency."""

    ticker: str
    decision_class: str
    final_opportunity_score: float
    band: str
    hard_rules_triggered: list[str] = field(default_factory=list)
    positive_contributors: dict[str, float] = field(default_factory=dict)
    penalties: dict[str, float] = field(default_factory=dict)
    decision_reason: str = ""
    rationale: list[str] = field(default_factory=list)
    advisory_note: str = STRATEGY_ADVISORY_NOTE
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _section(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return dict(value) if isinstance(value, dict) else {}


def decide(
    *,
    ticker: str,
    base_quality: float,
    mechanism: MechanismAssessment,
    doctrine: DoctrineVerdict,
    node: NodeClassification,
    competition: CompetitionAssessment,
    payoff: NodePayoffMatrix,
    chess: ChessStateAssessment,
    underground: UndergroundAssessment,
    distribution: DistributionAssessment,
    backhand: BackhandAssessment,
    value_chain_position_score: float = 0.0,
    food_chain_deteriorating: bool = False,
    short_risk_flagged: bool = False,
) -> StrategyDecision:
    """Compose the final research verdict with hard-rule gating."""
    contributors = {
        "base_quality": normalized_score(base_quality),
        "narrative_mechanism": mechanism.narrative_value,
        "value_chain_position": normalized_score(value_chain_position_score),
        "distribution_intelligence": distribution.distribution_intelligence_score / 10.0,
        "predator_node_fit": node.node_fit_score,
        "node_payoff_matrix": payoff.node_adjusted_score / 10.0,
        "dynamic_table": chess.dynamic_table_score / 10.0,
        "underground_breakout": (
            underground.buried_gem_score / 10.0
            if underground.underground_status
            else 0.5  # neutral when the name simply is not underground
        ),
        "backhand_defence": backhand.backhand_defence_score / 10.0,
        "competition_density": competition.competition_adjusted_strength,
        "inflection": payoff.inflection_value,
    }
    weighted = {
        name: WEIGHTS[name] * value for name, value in contributors.items()
    }

    hype = (
        1.0
        if distribution.archetype == "right_tail_narrative_weak_fundamentals"
        else (0.5 if underground.temporary_pavilion else 0.0)
    )
    penalties = {
        "fragility_penalty": backhand.fragility * PENALTY_WEIGHTS["fragility_penalty"],
        "unresolved_bear_penalty": (
            len(backhand.unresolved_bear_cases)
            / max(len(backhand.attacks), 1)
        ) * PENALTY_WEIGHTS["unresolved_bear_penalty"] if backhand.attacks else 0.0,
        "hype_penalty": hype * PENALTY_WEIGHTS["hype_penalty"],
        "evidence_weakness_penalty": (
            (1.0 - backhand.evidence_strength)
            * PENALTY_WEIGHTS["evidence_weakness_penalty"] * 0.5
        ),
        "fake_outlier_penalty": (
            min(len(distribution.fake_outlier_flags), 2) * 0.5
        ) * PENALTY_WEIGHTS["fake_outlier_penalty"],
    }

    raw = sum(weighted.values()) * 10.0 - sum(penalties.values())
    score = clip(raw, 0.0, 10.0)

    # ---------------- HARD RULES (caps override scores) ----------------
    hard: list[str] = []
    if not doctrine.passed:
        hard.append("doctrine_filter_reject: " + ", ".join(doctrine.reject_reasons))
    if not mechanism.mechanism_valid:
        hard.append("no_mechanism_no_trade")
    if not payoff.threshold_crossed:
        hard.append("threshold_not_crossed")
    if backhand.existential_bear_unresolved:
        hard.append("existential_bear_case_unresolved")
    if backhand.attacks and backhand.bear_case_survival < 0.3:
        hard.append("bear_case_survival_too_low")
    if not backhand.attacks:
        hard.append("thesis_never_attacked_needs_bear_case")
    if payoff.casino_ev <= 0 and payoff.upside > 0:
        hard.append("terrible_casino_odds_despite_upside")
    if payoff.food_chain_position in ("prey", "parasite") and food_chain_deteriorating:
        hard.append("prey_like_and_deteriorating")
    if distribution.fake_outlier_flags:
        hard.append("outlier_status_from_one_off_or_weak_peers")
    if distribution.confidence_penalty >= 0.6:
        hard.append("invalid_peer_universe_confidence_penalty")
    if backhand.evidence_strength < 0.25:
        hard.append("evidence_too_weak_for_any_buy")

    # ---------------- Decision class ----------------
    band = score_band(score)
    if short_risk_flagged:
        decision_class = "SHORT_RISK"
    elif "doctrine_filter_reject: " + ", ".join(doctrine.reject_reasons) in hard and (
        "no_economic_mechanism" in doctrine.reject_reasons
        or "hype_only_narrative" in doctrine.reject_reasons
        or "pure_story_no_cash_flow_path" in doctrine.reject_reasons
    ):
        decision_class = "REJECT"
    elif "threshold_not_crossed" in hard:
        decision_class = "THRESHOLD_NOT_CROSSED"
    elif "existential_bear_case_unresolved" in hard or (
        "prey_like_and_deteriorating" in hard
    ):
        decision_class = "AVOID" if score < 4.0 else "REJECT"
    elif "thesis_never_attacked_needs_bear_case" in hard or (
        "evidence_too_weak_for_any_buy" in hard
    ):
        decision_class = "NEEDS_MORE_EVIDENCE"
    elif underground.temporary_pavilion or (
        node.predator_node == "great_white" and payoff.inflection_value >= 0.3
        and score < 7.0
    ):
        decision_class = "EVENT_DRIVEN_ONLY"
    elif hard:
        decision_class = "WATCHLIST" if score >= 5.5 else "REJECT"
    elif score >= 8.5:
        decision_class = "BUY"
    elif score >= 5.5:
        decision_class = "WATCHLIST"
    elif score >= 4.0:
        decision_class = "NEEDS_MORE_EVIDENCE"
    else:
        decision_class = "REJECT"

    rationale = [
        f"composite {score:.2f}/10 (band: {band}); hard rules: "
        + (", ".join(hard) if hard else "none"),
        "verdict is a research classification, not an instruction",
    ]
    reason = (
        f"{decision_class}: score {score:.2f}/10"
        + (f"; capped by hard rules [{'; '.join(hard)}]" if hard else
           "; all hard rules clear")
        + ". " + STRATEGY_ADVISORY_NOTE
    )

    return StrategyDecision(
        ticker=str(ticker).upper(),
        decision_class=decision_class,
        final_opportunity_score=score,
        band=band,
        hard_rules_triggered=hard,
        positive_contributors={k: round(v, 4) for k, v in weighted.items()},
        penalties={k: round(v, 4) for k, v in penalties.items()},
        decision_reason=reason,
        rationale=rationale,
    )


def evaluate_strategy_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """One-payload orchestrator for the full strategy chain.

    JSON-friendly output: every engine's verdict, the final decision, the
    transparent score panel (contributors vs penalties), and the Match OS
    lifecycle record. ADVISORY_ONLY.
    """
    ticker = str(payload.get("ticker", "UNKNOWN"))

    mech_section = _section(payload, "mechanism")
    mechanism = assess_mechanism(
        narrative=str(payload.get("narrative", "unnamed narrative")),
        probability_shock=coerce_float(mech_section.get("probability_shock")),
        cash_flow_impact=coerce_float(mech_section.get("cash_flow_impact")),
        demand_impact=coerce_float(mech_section.get("demand_impact")),
        supply_impact=coerce_float(mech_section.get("supply_impact")),
        margin_impact=coerce_float(mech_section.get("margin_impact")),
        regulation_impact=coerce_float(mech_section.get("regulation_impact")),
        cost_of_capital_impact=coerce_float(
            mech_section.get("cost_of_capital_impact")
        ),
        multiple_impact=coerce_float(mech_section.get("multiple_impact")),
        risk_impact=coerce_float(mech_section.get("risk_impact")),
        transmission_path=str(mech_section.get("transmission_path", "")),
    )

    doctrine_section = _section(payload, "doctrine")
    doctrine = apply_doctrine_filter(
        mechanism=mechanism,
        evidence_source_count=int(
            coerce_float(doctrine_section.get("evidence_source_count"))
        ),
        value_chain_role_known=bool(
            doctrine_section.get("value_chain_role_known", False)
        ),
        balance_sheet_fragility=coerce_float(
            doctrine_section.get("balance_sheet_fragility")
        ),
        existential_bear_case_unresolved=bool(
            doctrine_section.get("existential_bear_case_unresolved", False)
        ),
        survival_threshold_crossed=bool(
            doctrine_section.get("survival_threshold_crossed", True)
        ),
        has_cash_flow_path=bool(doctrine_section.get("has_cash_flow_path", True)),
        hype_only=bool(doctrine_section.get("hype_only", False)),
    )

    node_section = _section(payload, "predator")
    node = classify_predator_node(
        dict(node_section.get("traits") or {}),
        payoff_asymmetry=coerce_float(node_section.get("payoff_asymmetry")),
        defensibility=coerce_float(node_section.get("defensibility")),
        mobility=coerce_float(node_section.get("mobility")),
        node_fragility=coerce_float(node_section.get("node_fragility")),
    )

    comp_section = _section(payload, "competition")
    competition = assess_competition_density(
        raw_performance=coerce_float(comp_section.get("raw_performance")),
        era_difficulty=coerce_float(comp_section.get("era_difficulty"), 0.5),
        opponent_quality=coerce_float(comp_section.get("opponent_quality"), 0.5),
        evidence_confidence=coerce_float(
            comp_section.get("evidence_confidence"), 0.5
        ),
        fragility=coerce_float(comp_section.get("fragility")),
        main_competitors=list(comp_section.get("main_competitors", []) or []),
    )

    payoff_section = _section(payload, "node_payoff")
    payoff = evaluate_node_payoff(**{
        k: v for k, v in payoff_section.items()
        if k in evaluate_node_payoff.__kwdefaults__
    })

    chess_section = _section(payload, "chess")
    chess = assess_chess_state(**{
        k: v for k, v in chess_section.items()
        if k in assess_chess_state.__kwdefaults__
    })

    underground_section = _section(payload, "underground")
    underground = assess_underground(**{
        k: v for k, v in underground_section.items()
        if k in assess_underground.__kwdefaults__
    })

    dist_section = _section(payload, "distribution")
    distribution = assess_distribution(
        peer_universe_node=str(
            dist_section.get("peer_universe_node", node.predator_node)
        ),
        company_node=str(dist_section.get("company_node", node.predator_node)),
        metrics=dict(dist_section.get("metrics") or {}),
        quality_percentile=coerce_float(
            dist_section.get("quality_percentile"), 50.0
        ),
        fragility_percentile=coerce_float(
            dist_section.get("fragility_percentile"), 50.0
        ),
        narrative_percentile=coerce_float(
            dist_section.get("narrative_percentile"), 50.0
        ),
        visibility=coerce_float(dist_section.get("visibility"), 0.5),
        catalyst=coerce_float(dist_section.get("catalyst")),
        nonlinear_adoption=coerce_float(dist_section.get("nonlinear_adoption")),
        promotion_path=coerce_float(dist_section.get("promotion_path")),
        distribution_unlock=coerce_float(dist_section.get("distribution_unlock")),
        upside_asymmetry=coerce_float(dist_section.get("upside_asymmetry")),
    )

    backhand_section = _section(payload, "backhand")
    backhand = assess_backhand_defence(
        bull_thesis=str(backhand_section.get("bull_thesis", "")),
        bear_attacks=[
            a for a in backhand_section.get("bear_attacks", []) or []
            if isinstance(a, dict)
        ],
        weak_side_improvement=coerce_float(
            backhand_section.get("weak_side_improvement")
        ),
        evidence_strength=coerce_float(backhand_section.get("evidence_strength")),
        fragility=coerce_float(backhand_section.get("fragility")),
    )

    decision = decide(
        ticker=ticker,
        base_quality=coerce_float(payload.get("base_quality")),
        mechanism=mechanism,
        doctrine=doctrine,
        node=node,
        competition=competition,
        payoff=payoff,
        chess=chess,
        underground=underground,
        distribution=distribution,
        backhand=backhand,
        value_chain_position_score=coerce_float(
            payload.get("value_chain_position_score")
        ),
        food_chain_deteriorating=bool(payload.get("food_chain_deteriorating", False)),
        short_risk_flagged=bool(payload.get("short_risk_flagged", False)),
    )

    # Match OS lifecycle record: which stage each artifact belongs to.
    lifecycle = {
        "pre_pre_game": {
            "doctrine_filter_result": doctrine.passed,
            "reject_reasons": doctrine.reject_reasons,
            "minimum_thresholds": doctrine.minimum_required_thresholds,
        },
        "pre_game": {
            "strongest_bear_attack": backhand.strongest_bear_attack,
            "weakest_point": backhand.weakest_point,
            "node_specific_risks": node.node_specific_risks,
            "missing_thresholds": payoff.missing_thresholds,
        },
        "in_game": {
            "recalibration_surface": (
                "re-run this payload as evidence changes; hysteresis and "
                "telemetry live in the simulator pipeline"
            ),
        },
        "post_game": {
            "forensic_learning_surface": (
                "resolve outcomes via simulator telemetry / calibration "
                "bridge; weight adjustments are recommendation-only"
            ),
        },
    }

    return {
        "ticker": decision.ticker,
        "advisory_note": STRATEGY_ADVISORY_NOTE,
        "doctrine": list(STRATEGY_DOCTRINE),
        "decision": decision.to_dict(),
        "transparent_score_panel": {
            "positive_contributors": decision.positive_contributors,
            "penalties": decision.penalties,
            "final_score": decision.final_opportunity_score,
        },
        "lifecycle": lifecycle,
        "breakdown": {
            "mechanism": mechanism.to_dict(),
            "doctrine_filter": doctrine.to_dict(),
            "predator_node": node.to_dict(),
            "competition_density": competition.to_dict(),
            "node_payoff": payoff.to_dict(),
            "chess_state": chess.to_dict(),
            "underground": underground.to_dict(),
            "distribution": distribution.to_dict(),
            "backhand_defence": backhand.to_dict(),
        },
    }
