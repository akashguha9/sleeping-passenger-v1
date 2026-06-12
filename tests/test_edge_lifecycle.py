"""Edge lifecycle proofs: carrying capacity, acceleration paths,
arbitrage convergence, hedged-edge survival, the thesis expiry clock,
the Opportunity equation verdict, and pipeline gating."""

from __future__ import annotations

import copy
import json

import pytest

from src.simulator.pipeline import evaluate_candidate_payload
from src.strategy.edge_lifecycle import (
    assess_edge_lifecycle,
    compute_expiry_clock,
    decompose_hedged_edge,
    detect_arbitrage_gap,
    estimate_carrying_capacity,
    score_acceleration_path,
)
from tests.test_simulator_cherry_pick_pipeline import STRONG_PAYLOAD


def golden_section() -> dict:
    """The docs' worked example: live, underpriced, accelerating."""
    return {
        "crowding": 0.15, "live_edge": 0.7, "half_life_days": 40,
        "threshold": 0.2,
        "capacity": {
            "current_scale": 0.2, "tam_evidence": 0.8,
            "expansion_optionality": 0.6, "pricing_power": 0.7,
            "competitive_pressure": 0.2, "regulatory_headroom": 0.8,
            "claimed_growth_rate": 0.3,
            "growth_rate_trend": [0.2, 0.25, 0.3],
        },
        "path": {
            "latent_potential": 0.7, "realized_momentum": 0.45,
            "catalyst_strength": 0.7, "catalyst_proximity_days": 20,
            "evidence_support": 0.7, "friction": 0.1, "decay_risk": 0.2,
        },
        "arbitrage": {
            "reality_score": 0.75, "priced_belief": 0.45,
            "convergence_catalyst": "earnings re-rate",
            "convergence_probability": 0.6, "friction": 0.05,
            "break_risk": 0.15,
        },
        "hedge": {
            "thesis_edge": 0.6, "exposures": {"market_beta": 0.3},
            "hedge_cost": 0.1, "risk_reduced": 0.3,
        },
    }


# --- Carrying capacity -----------------------------------------------------------
def test_early_runway_with_evidenced_headroom() -> None:
    report = estimate_carrying_capacity(
        current_scale=0.2, tam_evidence=0.8, expansion_optionality=0.6,
        pricing_power=0.7, competitive_pressure=0.2,
        regulatory_headroom=0.8, claimed_growth_rate=0.3,
    )
    assert report.saturation_state == "early_runway"
    assert not report.fake_exponential
    assert report.k_proxy >= report.current_scale  # K never below scale


def test_deceleration_bends_the_curve() -> None:
    report = estimate_carrying_capacity(
        current_scale=0.55, market_penetration=0.65, tam_evidence=0.6,
        claimed_growth_rate=0.2, growth_rate_trend=[0.4, 0.3, 0.2],
    )
    assert report.saturation_state == "bending_toward_saturation"
    assert any("bending" in r for r in report.rationale)


def test_high_penetration_saturates() -> None:
    report = estimate_carrying_capacity(
        current_scale=0.8, market_penetration=0.9, tam_evidence=0.5,
    )
    assert report.saturation_state == "saturated"
    assert report.remaining_runway < 0.15


def test_fake_exponential_narrative_is_flagged() -> None:
    report = estimate_carrying_capacity(
        current_scale=0.3, tam_evidence=0.5, claimed_growth_rate=0.8,
        horizon_years=3.0,
    )
    assert report.fake_exponential
    assert any("logistic" in r for r in report.rationale)


def test_growth_quality_prefers_runway_over_rate() -> None:
    # The reflection's claim: a 60% grower near saturation is worse
    # than a 20% grower with remaining runway. r x (K - G).
    hot_but_full = estimate_carrying_capacity(
        current_scale=0.75, market_penetration=0.7, tam_evidence=0.6,
        claimed_growth_rate=0.6,
    )
    slow_but_early = estimate_carrying_capacity(
        current_scale=0.15, tam_evidence=0.8, expansion_optionality=0.5,
        claimed_growth_rate=0.2,
    )
    assert slow_but_early.growth_quality > hot_but_full.growth_quality


# --- Acceleration path ------------------------------------------------------------
def test_path_b_controlled_acceleration() -> None:
    report = score_acceleration_path(
        latent_potential=0.7, realized_momentum=0.45,
        catalyst_strength=0.7, evidence_support=0.7,
    )
    assert report.path_class == "controlled_acceleration"
    assert report.conversion_ratio == pytest.approx(0.45 / 0.7, abs=1e-3)


def test_path_a_reckless_drop_momentum_without_evidence() -> None:
    report = score_acceleration_path(
        latent_potential=0.4, realized_momentum=0.8,
        catalyst_strength=0.6, evidence_support=0.2,
    )
    assert report.path_class == "reckless_drop"


def test_path_c_and_stalled_potential() -> None:
    stalled = score_acceleration_path(
        latent_potential=0.8, realized_momentum=0.1,
        catalyst_strength=0.1, evidence_support=0.6,
    )
    assert stalled.path_class == "stalled_potential"
    slow = score_acceleration_path(
        latent_potential=0.3, realized_momentum=0.2,
        catalyst_strength=0.2, evidence_support=0.6,
    )
    assert slow.path_class == "slow_straight_line"


def test_catalyst_proximity_boosts_acceleration() -> None:
    near = score_acceleration_path(
        latent_potential=0.6, realized_momentum=0.5,
        catalyst_strength=0.6, catalyst_proximity_days=5,
        evidence_support=0.6,
    )
    far = score_acceleration_path(
        latent_potential=0.6, realized_momentum=0.5,
        catalyst_strength=0.6, catalyst_proximity_days=90,
        evidence_support=0.6,
    )
    assert near.acceleration_edge > far.acceleration_edge


# --- Arbitrage convergence -----------------------------------------------------------
def test_gap_with_catalyst_yields_positive_net_edge() -> None:
    report = detect_arbitrage_gap(
        reality_score=0.75, priced_belief=0.45,
        convergence_catalyst="earnings re-rate",
        convergence_probability=0.6, friction=0.05, break_risk=0.1,
    )
    assert report.gap == pytest.approx(0.3)
    assert report.net_edge > 0
    assert not report.value_trap


def test_gap_without_catalyst_is_a_value_trap() -> None:
    report = detect_arbitrage_gap(
        reality_score=0.8, priced_belief=0.4, convergence_catalyst="",
        convergence_probability=0.9,  # ignored without a catalyst
    )
    assert report.value_trap
    assert report.convergence_probability == 0.0
    assert any("value trap" in r for r in report.rationale)


def test_crowding_shortens_the_arbitrage_window() -> None:
    quiet = detect_arbitrage_gap(
        reality_score=0.7, priced_belief=0.4,
        convergence_catalyst="spin-off", convergence_probability=0.5,
        crowding=0.0, gap_half_life_days=60,
    )
    crowded = detect_arbitrage_gap(
        reality_score=0.7, priced_belief=0.4,
        convergence_catalyst="spin-off", convergence_probability=0.5,
        crowding=0.8, gap_half_life_days=60,
    )
    assert crowded.gap_half_life_days < quiet.gap_half_life_days


# --- Hedged edge -----------------------------------------------------------------------
def test_hedged_edge_viable_with_efficient_hedge() -> None:
    report = decompose_hedged_edge(
        thesis_edge=0.6, exposures={"market_beta": 0.3},
        hedge_cost=0.1, risk_reduced=0.3, ruin_risk=0.2,
    )
    assert report.hedged_edge > 0
    assert report.hedge_efficiency == pytest.approx(3.0)
    assert not report.over_hedged
    assert report.survival_viable


def test_over_hedging_kills_the_edge() -> None:
    report = decompose_hedged_edge(
        thesis_edge=0.3, exposures={"market_beta": 0.4},
        hedge_cost=0.35, risk_reduced=0.2,
    )
    assert report.over_hedged
    assert any("over-hedged" in r for r in report.rationale)


def test_ruin_risk_blocks_survival() -> None:
    report = decompose_hedged_edge(
        thesis_edge=0.6, exposures={}, hedge_cost=0.0, ruin_risk=0.7,
    )
    assert not report.survival_viable
    assert any("ruin" in r.lower() for r in report.rationale)


# --- Expiry clock -----------------------------------------------------------------------
def test_expiry_clock_math() -> None:
    # E0=0.8, T=0.2, h=30 -> t = 30 * log2(4) = exactly 60 days.
    clock = compute_expiry_clock(
        live_edge=0.8, threshold=0.2, half_life_days=30,
    )
    assert clock.days_to_expiry == pytest.approx(60.0)
    assert clock.status == "live"


def test_expired_and_marginal_states() -> None:
    assert compute_expiry_clock(
        live_edge=0.15, threshold=0.2
    ).status == "expired"
    marginal = compute_expiry_clock(
        live_edge=0.3, threshold=0.25, half_life_days=30,
    )
    assert marginal.status == "marginal"  # ~7.9 days < half of 30
    assert 0 < marginal.days_to_expiry < 15


# --- Orchestrator verdicts ---------------------------------------------------------------
def test_golden_state_live_underpriced_acceleration() -> None:
    report = assess_edge_lifecycle(golden_section())
    assert report.verdict == "live_underpriced_acceleration"
    assert report.opportunity_score > 0
    assert report.expiry["status"] == "live"
    json.dumps(report.to_dict())  # serializable


def test_priced_in_when_belief_caught_up() -> None:
    section = golden_section()
    section["arbitrage"]["priced_belief"] = 0.75  # belief == reality
    report = assess_edge_lifecycle(section)
    assert report.verdict == "priced_in"


def test_potential_without_catalyst() -> None:
    section = golden_section()
    section["path"]["catalyst_strength"] = 0.1
    section["path"]["realized_momentum"] = 0.1
    report = assess_edge_lifecycle(section)
    assert report.verdict == "potential_without_catalyst"


def test_decayed_below_threshold_wins_over_everything() -> None:
    section = golden_section()
    section["live_edge"] = 0.1  # below threshold 0.2
    report = assess_edge_lifecycle(section)
    assert report.verdict == "decayed_below_threshold"
    assert report.expiry["days_to_expiry"] == 0.0


def test_saturating_compounder() -> None:
    section = golden_section()
    section["capacity"] = {
        "current_scale": 0.8, "market_penetration": 0.9,
        "tam_evidence": 0.5,
    }
    section["arbitrage"]["priced_belief"] = 0.75  # nothing to converge
    report = assess_edge_lifecycle(section)
    assert report.verdict == "saturating_compounder"


def test_fake_exponential_blocks_the_golden_state() -> None:
    section = golden_section()
    section["capacity"]["current_scale"] = 0.3
    section["capacity"]["tam_evidence"] = 0.5
    section["capacity"]["claimed_growth_rate"] = 0.8
    report = assess_edge_lifecycle(section)
    assert report.capacity["fake_exponential"] is True
    assert report.verdict != "live_underpriced_acceleration"
    assert any("fake-exponential" in r for r in report.rationale)


# --- Pipeline integration ----------------------------------------------------------------
def test_pipeline_without_lifecycle_section_is_passthrough() -> None:
    out = evaluate_candidate_payload(copy.deepcopy(STRONG_PAYLOAD))
    assert out["lifecycle"] is None
    assert "lifecycle_gate" not in out["decision"]["gate_results"]


def test_pipeline_golden_state_with_self_fed_inputs() -> None:
    payload = copy.deepcopy(STRONG_PAYLOAD)
    payload["lifecycle"] = golden_section()
    out = evaluate_candidate_payload(payload)
    lifecycle = out["lifecycle"]
    assert lifecycle["verdict"] == "live_underpriced_acceleration"
    assert out["decision"]["gate_results"]["lifecycle_gate"] is True
    assert (
        "LIVE_UNDERPRICED_ACCELERATION" in out["decision"]["reason_codes"]
    )
    # The golden label never promotes: state unchanged from baseline.
    assert out["decision"]["final_state"] == "active_watch"
    # Self-fed: theme crowding (0.3 > caller 0.15) won conservatively,
    # and the prediction market's priced belief carried provenance.
    assert lifecycle["derived_inputs"]["crowding"] == (
        "theme_mapper.crowding"
    )
    assert lifecycle["derived_inputs"]["priced_belief"] == (
        "prediction_market.probability_after"
    )


def test_pipeline_expired_edge_caps_at_watchlist() -> None:
    payload = copy.deepcopy(STRONG_PAYLOAD)
    # Caller claims a fat live edge; the payload's own stale, weak tyre
    # says otherwise — the engine-derived (lower) edge wins.
    payload["lifecycle"] = {"live_edge": 0.9, "threshold": 0.6}
    payload["signals"] = [{
        "signal_type": "social_spike", "raw_strength": 60,
        "signal_age_hours": 120, "source_quality": 0.6,
    }]
    out = evaluate_candidate_payload(payload)
    lifecycle = out["lifecycle"]
    assert lifecycle["verdict"] == "decayed_below_threshold"
    assert lifecycle["expiry"]["edge_source"] == (
        "signal_tyres.blended_grip_pct/100"
    )
    assert out["decision"]["gate_results"]["lifecycle_gate"] is False
    assert "EDGE_EXPIRED" in out["decision"]["reason_codes"]
    assert out["decision"]["final_state"] == "watchlist"


def test_caller_conservative_edge_beats_engine_optimism() -> None:
    payload = copy.deepcopy(STRONG_PAYLOAD)
    # STRONG_PAYLOAD tyres are fresh (high grip); a caller who judges
    # the live edge LOWER than the engines is honored.
    payload["lifecycle"] = {**golden_section(), "live_edge": 0.05}
    out = evaluate_candidate_payload(payload)
    assert out["lifecycle"]["expiry"]["live_edge"] == pytest.approx(0.05)
    assert out["lifecycle"]["verdict"] == "decayed_below_threshold"


# --- Carrying-capacity bottleneck decomposition --------------------------------
def test_tightest_bottleneck_controls_k_effective() -> None:
    report = estimate_carrying_capacity(
        current_scale=0.2, tam_evidence=0.8, expansion_optionality=0.6,
        ceilings={"market": 0.9, "regulatory": 0.35, "attention": 0.5},
    )
    assert report.binding_constraint == "regulatory"
    assert report.k_proxy == pytest.approx(0.35)
    assert any("tightest bottleneck" in r for r in report.rationale)


def test_regulatory_bottleneck_caps_runway() -> None:
    unconstrained = estimate_carrying_capacity(
        current_scale=0.2, tam_evidence=0.8, expansion_optionality=0.6,
    )
    constrained = estimate_carrying_capacity(
        current_scale=0.2, tam_evidence=0.8, expansion_optionality=0.6,
        ceilings={"regulatory": 0.3},
    )
    assert constrained.remaining_runway < unconstrained.remaining_runway


def test_competition_bottleneck_exposes_fake_exponential() -> None:
    # 30%/yr for 3y from scale 0.3 fits a blended K but overruns a
    # tight competitive ceiling: the bottleneck exposes the fake.
    loose = estimate_carrying_capacity(
        current_scale=0.3, tam_evidence=0.9, expansion_optionality=0.7,
        claimed_growth_rate=0.3, horizon_years=3.0,
    )
    tight = estimate_carrying_capacity(
        current_scale=0.3, tam_evidence=0.9, expansion_optionality=0.7,
        claimed_growth_rate=0.3, horizon_years=3.0,
        ceilings={"competition": 0.45},
    )
    assert not loose.fake_exponential
    assert tight.fake_exponential
    assert tight.binding_constraint == "competition"


def test_attention_ceiling_names_the_hype() -> None:
    report = estimate_carrying_capacity(
        current_scale=0.3, tam_evidence=0.9,
        ceilings={"attention": 0.35},
    )
    assert report.binding_constraint == "attention"
    assert any("made of attention" in r for r in report.rationale)


def test_ceiling_below_scale_means_saturated_not_impossible() -> None:
    report = estimate_carrying_capacity(
        current_scale=0.5, ceilings={"adoption": 0.3},
    )
    assert report.k_proxy == pytest.approx(0.5)  # floored at scale
    assert report.ceiling_utilization == pytest.approx(1.0)
    assert report.saturation_state == "saturated"


def test_decomposed_k_flows_through_lifecycle_output() -> None:
    section = golden_section()
    section["capacity"]["ceilings"] = {"regulatory": 0.45}
    report = assess_edge_lifecycle(section)
    assert report.capacity["binding_constraint"] == "regulatory"
    assert report.capacity["ceilings"] == {"regulatory": 0.45}
    json.dumps(report.to_dict())


# --- Safe belief gap -----------------------------------------------------------
def test_wide_gap_dies_under_low_evidence_quality() -> None:
    section = golden_section()
    section["arbitrage"]["uncertainty_band"] = 0.1
    section["arbitrage"]["evidence_quality"] = 0.3
    report = assess_edge_lifecycle(section)
    # Raw gap 0.30 survives nothing: safe gap (0.30-0.10)*0.3 = 0.06.
    assert report.arbitrage["gap"] == pytest.approx(0.3)
    assert report.arbitrage["safe_gap"] == pytest.approx(0.06)
    assert report.verdict != "live_underpriced_acceleration"


def test_fresh_independent_evidence_preserves_the_gap() -> None:
    section = golden_section()
    section["arbitrage"]["uncertainty_band"] = 0.05
    section["arbitrage"]["evidence_quality"] = 0.9
    report = assess_edge_lifecycle(section)
    assert report.arbitrage["safe_gap"] > 0.1
    assert report.verdict == "live_underpriced_acceleration"


def test_price_already_moved_closes_the_gap() -> None:
    from src.strategy.edge_lifecycle import detect_arbitrage_gap

    fresh = detect_arbitrage_gap(
        reality_score=0.8, priced_belief=0.5,
        convergence_catalyst="earnings", convergence_probability=0.6,
    )
    moved = detect_arbitrage_gap(
        reality_score=0.8, priced_belief=0.5,
        convergence_catalyst="earnings", convergence_probability=0.6,
        price_already_moved=0.9,
    )
    assert moved.safe_gap < fresh.safe_gap
    assert fresh.safe_gap == pytest.approx(fresh.gap)  # no inputs, no change


def test_heat_only_gap_is_flagged_unsupported() -> None:
    from src.strategy.edge_lifecycle import detect_arbitrage_gap

    report = detect_arbitrage_gap(
        reality_score=0.8, priced_belief=0.5,
        convergence_catalyst="earnings", convergence_probability=0.6,
        uncertainty_band=0.2, evidence_quality=0.15,
    )
    assert report.gap > 0.1
    assert report.safe_gap <= 0.02
    assert report.gap_unsupported
    assert any("heat, not edge" in r for r in report.rationale)


def test_lifecycle_report_is_fully_serializable() -> None:
    payload = copy.deepcopy(STRONG_PAYLOAD)
    payload["lifecycle"] = golden_section()
    out = evaluate_candidate_payload(payload)
    assert json.dumps(out["lifecycle"])
    assert out["lifecycle"]["advisory_status"] == "ADVISORY_ONLY"
