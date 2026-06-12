"""Counterfactual wind tunnel proofs: the model doubts itself.

Perturbation grading, causal gate attribution (necessary / sufficient /
redundant / passenger / fragile), regime probes, anti-gaming exposure,
gate-utility classification, determinism, and pipeline contract.
"""

from __future__ import annotations

import copy

import pytest

from src.simulator.pipeline import evaluate_candidate_payload
from src.simulator.wind_tunnel import (
    CohortStats,
    GateExperimentReport,
    run_gate_experiment,
)
from src.strategy.counterfactual_wind_tunnel import (
    classify_gate_utility,
    run_counterfactual_audit,
)
from tests.test_self_feed import _bars, crowded_payload
from tests.test_simulator_cherry_pick_pipeline import STRONG_PAYLOAD


def fatal_payload() -> dict:
    payload = copy.deepcopy(STRONG_PAYLOAD)
    payload["opponent"] = {
        "weaknesses": {"customer_concentration": 0.9},
        "attack_probability": 0.8, "cost_to_exploit": 0.1,
        "adaptation": {"signal_strength": 0.8, "repricing_observed": 0.1},
    }
    return payload


@pytest.fixture(scope="module")
def crowded_audit():
    return run_counterfactual_audit(crowded_payload())


@pytest.fixture(scope="module")
def strong_audit():
    return run_counterfactual_audit(copy.deepcopy(STRONG_PAYLOAD))


@pytest.fixture(scope="module")
def fatal_audit():
    return run_counterfactual_audit(fatal_payload())


def _perturbation(report, name):
    return next(p for p in report.perturbations if p.name == name)


# --- Attribution: necessary / redundant / passenger / fragile -----------------
def test_necessary_driver_removal_disables_gate(crowded_audit) -> None:
    # The crowded fixture's exhaustion cap is a conjunction near the
    # threshold: ablating ANY of the four drivers un-fires the gate.
    assert crowded_audit.gate_fired
    assert set(crowded_audit.necessary_drivers) == {
        "theme_crowding", "valuation_heat", "narrative_saturation",
        "signal_weakness",
    }
    entry = next(
        a for a in crowded_audit.attribution
        if a.input_name == "theme_crowding"
    )
    assert entry.classification == "NECESSARY_DRIVER"
    assert entry.gate_after_ablation == "silent"


def test_redundant_support_does_not_change_gate(fatal_audit) -> None:
    # A fatal weak side fires regardless of crowding: the theme inputs
    # move the OAI but never the verdict — redundant support.
    assert fatal_audit.gate_fired
    assert "theme_crowding" in fatal_audit.redundant_supports
    entry = next(
        a for a in fatal_audit.attribution
        if a.input_name == "theme_crowding"
    )
    assert entry.gate_after_ablation == "fired"


def test_passenger_signal_is_named(crowded_audit) -> None:
    # Risk factors are present in the payload and the explanation, but
    # ablating them moves neither the OAI nor the exhaustion gate.
    assert crowded_audit.passenger_signals == ["weak_side_severity"]


def test_single_point_gate_flagged_fragile(fatal_audit) -> None:
    assert fatal_audit.necessary_drivers == ["weak_side_severity"]
    assert fatal_audit.sufficient_drivers == ["weak_side_severity"]
    assert fatal_audit.fragile_inputs == ["weak_side_severity"]
    assert fatal_audit.fragility_count == 1
    assert "FRAGILE_SINGLE_POINT" in fatal_audit.warnings
    # The fragility honestly costs robustness: 14/14 matched minus the
    # 0.1 single-point penalty.
    assert fatal_audit.matched_count == fatal_audit.graded_count == 14
    assert fatal_audit.robustness_score == pytest.approx(0.9)


def test_attribution_skipped_when_gate_silent(strong_audit) -> None:
    assert not strong_audit.gate_fired
    assert strong_audit.attribution == []
    assert strong_audit.necessary_drivers == []
    assert any("attribution not applicable" in r
               for r in strong_audit.rationale)


# --- Perturbation grading -----------------------------------------------------
def test_full_robustness_on_crowded_fixture(crowded_audit) -> None:
    # The docs' worked example: every graded counterfactual matched.
    assert crowded_audit.graded_count == 14
    assert crowded_audit.matched_count == 14
    assert crowded_audit.robustness_score == pytest.approx(1.0)
    assert crowded_audit.gate_margin == pytest.approx(0.154, abs=1e-3)
    assert "GATE_MARGIN_THIN" in crowded_audit.warnings


def test_optimistic_override_is_challenged_and_does_not_rescue(
    crowded_audit, fatal_audit,
) -> None:
    for report in (crowded_audit, fatal_audit):
        probe = _perturbation(report, "optimistic_opponent_override")
        assert probe.matched is True
        assert "OPPONENT_OVERRIDE_CHALLENGED" in probe.observed_codes
        assert probe.improved_verdict is False
    assert "ANTI_GAMING_BREACH" not in crowded_audit.warnings
    assert "ANTI_GAMING_BREACH" not in fatal_audit.warnings
    assert crowded_audit.overconfidence_penalty == 0.0


def test_conservative_override_passes_unchallenged(strong_audit) -> None:
    probe = _perturbation(strong_audit, "conservative_opponent_override")
    assert probe.matched is True  # NOT_BETTER held
    assert "OPPONENT_OVERRIDE_CHALLENGED" not in probe.observed_codes
    assert probe.observed_gate == "fired"  # caution fired the cap


def test_benign_regime_avoids_hard_cap(crowded_audit) -> None:
    probe = _perturbation(crowded_audit, "benign_regime")
    assert probe.matched is True
    assert probe.observed_gate == "silent"
    assert "EDGE_EXHAUSTED" not in probe.observed_codes


def test_hostile_regime_triggers_cap(strong_audit) -> None:
    probe = _perturbation(strong_audit, "hostile_regime")
    assert probe.matched is True
    assert probe.observed_gate == "fired"
    assert "EDGE_EXHAUSTED" in probe.observed_codes


def test_noisy_regime_warns_without_fake_certainty(strong_audit) -> None:
    probe = _perturbation(strong_audit, "noisy_regime")
    assert probe.matched is True
    assert probe.observed_gate == "silent"
    assert "SELF_FEED_LOW_COVERAGE" in probe.observed_codes


def test_missing_engines_warn_but_caller_fatal_cap_stands(
    fatal_audit,
) -> None:
    # With engines dark, exhaustion cannot be measured — but a fatal
    # weak side from the caller's own judged weaknesses needs no engine.
    probe = _perturbation(fatal_audit, "missing_engine_fallback")
    assert probe.matched is True
    assert "EDGE_EXHAUSTED" not in probe.observed_codes
    assert "FATAL_WEAK_SIDE" in probe.observed_codes


def test_delayed_signals_never_read_better(crowded_audit) -> None:
    probe = _perturbation(crowded_audit, "delay_signals")
    assert probe.matched is True
    assert probe.improved_verdict is False


# --- Anti-gaming surface: exposed, not denied -----------------------------------
def test_gaming_surface_is_published(crowded_audit) -> None:
    # Suppressing crowding/heat/narrative or inflating signals DOES
    # improve the verdict — the audit cannot police the world outside
    # the payload, so it publishes exactly which fields are gameable.
    assert set(crowded_audit.gameable_inputs) == {
        "ablate_theme_crowding", "ablate_valuation_heat",
        "inflate_signals", "suppress_narrative",
    }
    for name in crowded_audit.gameable_inputs:
        assert (
            f"VERDICT_SENSITIVE_TO_CALLER_INPUT:{name}"
            in crowded_audit.warnings
        )
    # Gameability raises false-negative risk: 0.1 + 0.05 x 4.
    assert crowded_audit.false_negative_risk == pytest.approx(0.3)


def test_clean_payload_has_no_gameable_inputs(strong_audit) -> None:
    assert strong_audit.gameable_inputs == []
    assert strong_audit.false_negative_risk == pytest.approx(0.1)
    assert strong_audit.false_positive_risk == pytest.approx(0.1)


def test_tier_warnings_always_present(strong_audit) -> None:
    assert "SYNTHETIC_REPLAY_TIER" in strong_audit.warnings
    assert "LOW_REAL_WORLD_CALIBRATION" in strong_audit.warnings
    assert strong_audit.advisory_status == "ADVISORY_ONLY"


# --- Determinism and pipeline contract ------------------------------------------
def test_audit_is_deterministic() -> None:
    first = run_counterfactual_audit(crowded_payload()).to_dict()
    second = run_counterfactual_audit(crowded_payload()).to_dict()
    assert first == second


def test_pipeline_contract_with_and_without_flag() -> None:
    plain = evaluate_candidate_payload(crowded_payload())
    assert plain["counterfactual_wind_tunnel"] is None
    for key in ("decision", "advisory_action", "opponent", "telemetry",
                "unified_verdict"):
        assert key in plain  # old contract intact

    audited = evaluate_candidate_payload(
        {**crowded_payload(), "counterfactual_audit": True}
    )
    report = audited["counterfactual_wind_tunnel"]
    assert report["robustness_score"] == pytest.approx(1.0)
    assert report["gate_fired"] is True
    assert report["advisory_status"] == "ADVISORY_ONLY"
    # The audit changed the analysis, never the verdict.
    assert (
        audited["decision"]["final_state"]
        == plain["decision"]["final_state"]
    )


# --- Gate utility classification ---------------------------------------------------
def _experiment(**overrides) -> GateExperimentReport:
    base = dict(
        ticker="T", price_provenance="SYNTHETIC", decision_count=4,
        divergent_count=1,
        capped_cohort=CohortStats(
            count=1, win_rate=0.0, mean_forward_return=-0.08
        ),
        undiverged_cohort=CohortStats(
            count=3, win_rate=0.67, mean_forward_return=0.03
        ),
        capped_return_disadvantage=0.11,
        gates_helping=True,
    )
    base.update(overrides)
    return GateExperimentReport(**base)


def test_gate_utility_helpful_from_real_replay() -> None:
    def builder(ticker: str, visible: list[dict]) -> dict:
        payload = (
            copy.deepcopy(STRONG_PAYLOAD)
            if len(visible) % 2 == 0
            else crowded_payload()
        )
        payload["ticker"] = ticker
        return payload

    report = run_gate_experiment(
        ticker="GRIDCO", bars=_bars(), price_provenance="SYNTHETIC",
        horizon_days=5, every_n_bars=5, payload_builder=builder,
    )
    assert classify_gate_utility(report) == "helpful"


def test_gate_utility_insufficient_when_gate_never_fires() -> None:
    report = _experiment(
        divergent_count=0,
        capped_cohort=CohortStats(
            count=0, win_rate=None, mean_forward_return=None
        ),
        capped_return_disadvantage=None,
        gates_helping=None,
    )
    assert classify_gate_utility(report) == "insufficient_evidence"


def test_gate_utility_harmful_when_cap_points_at_winners() -> None:
    report = _experiment(
        capped_cohort=CohortStats(
            count=1, win_rate=1.0, mean_forward_return=0.06
        ),
        undiverged_cohort=CohortStats(
            count=3, win_rate=0.33, mean_forward_return=-0.01
        ),
        capped_return_disadvantage=-0.07,
        gates_helping=False,
    )
    assert classify_gate_utility(report) == "harmful"


def test_gate_utility_over_conservative_when_capping_half_the_winners(
) -> None:
    report = _experiment(
        divergent_count=3,
        capped_cohort=CohortStats(
            count=3, win_rate=0.67, mean_forward_return=0.02
        ),
        undiverged_cohort=CohortStats(
            count=1, win_rate=0.0, mean_forward_return=-0.04
        ),
        capped_return_disadvantage=-0.06,
        gates_helping=False,
    )
    assert classify_gate_utility(report) == "over_conservative"


def test_gate_utility_regime_dependent_on_mixed_capped_cohort() -> None:
    report = _experiment(
        divergent_count=1,
        decision_count=8,
        capped_cohort=CohortStats(
            count=2, win_rate=0.5, mean_forward_return=0.001
        ),
        capped_return_disadvantage=0.002,
    )
    assert classify_gate_utility(report) == "regime_dependent"
