from __future__ import annotations

from scripts.latent_signal_release_bull_layer import (
    BullSignalState,
    ReleaseTriggerInput,
    SignalReleaseAtom,
    build_latent_signal_release_bull_report,
    classify_bull_state,
    compute_false_conviction_risk,
    compute_opportunity_half_life,
    compute_signal_zeta,
    load_thresholds,
)
from scripts.pipeline_health_report import build_pipeline_health_report


def _base_payload() -> ReleaseTriggerInput:
    return ReleaseTriggerInput(
        signals=[
            SignalReleaseAtom(signal=0.95, weight=0.5, persistence=0.95, source_quality=0.95),
            SignalReleaseAtom(signal=0.9, weight=0.3, persistence=0.9, source_quality=0.9),
            SignalReleaseAtom(signal=0.9, weight=0.2, persistence=0.9, source_quality=0.9),
        ],
        event_proximity=0.8,
        narrative_acceleration=0.8,
        price_move_intensity=0.75,
        prediction_market_delta=0.7,
        source_burst=0.75,
        confidence=0.85,
        persistence=0.85,
        noise=0.2,
        initial_edge=0.9,
        decay_rate=0.4,
        elapsed_time=0.5,
        validation_time=0.65,
        minimum_validation=0.7,
        peak_alignment=0.8,
        time_decay=0.2,
        execution_delay_penalty=0.1,
        source_diversity=0.85,
        counter_signal_resistance=0.8,
        metadata_clarity=0.8,
        echo_chamber_penalty=0.1,
        source_independence=0.8,
        theme_distance=0.8,
        validation_depth=0.85,
        circular_citation_penalty=0.05,
        same_narrative_origin_penalty=0.05,
        cluster_density=0.2,
        volatility_delta=0.2,
        news_intensity=0.3,
        liquidity_stress=0.2,
        event_surprise=0.5,
        spread_expansion=0.2,
        theme_similarity=0.85,
        counter_signal_survival=0.85,
        stress_survival=0.85,
        plan_clarity=0.85,
        risk_control=0.85,
        invalidation_clarity=0.85,
        exit_discipline=0.85,
        review_discipline=0.85,
        execution_survivability=0.85,
        policy_permission=1.0,
        policy_veto=False,
        chaos_veto=False,
        irreversible_event_shock=False,
        momentum=0.7,
        risk_cap_active=True,
        execution_plan_complete=True,
        entry_defined=True,
        sizing_defined=True,
        exit_defined=True,
        review_defined=True,
        previous_state=BullSignalState.MIURA.value,
    )


def test_signal_zeta_calculation_improves_with_diversity_and_persistence() -> None:
    low = compute_signal_zeta(0.7, 0.7, 0.2, 0.2, 0.1, 0.1, 0.1)
    high = compute_signal_zeta(0.7, 0.7, 0.9, 0.9, 0.1, 0.1, 0.1)
    assert high > low


def test_false_conviction_risk_calculation_rises_with_dense_dependent_cluster() -> None:
    low = compute_false_conviction_risk(0.2, 0.9)
    high = compute_false_conviction_risk(0.9, 0.2)
    assert high > low


def test_collapse_analysis_cannot_execute() -> None:
    payload = _base_payload()
    payload.execution_plan_complete = False
    payload.entry_defined = False
    payload.sizing_defined = False
    payload.exit_defined = False
    payload.review_defined = False
    thresholds = load_thresholds()
    result = classify_bull_state(payload, thresholds)
    assert result.state in {
        BullSignalState.COLLAPSE_ANALYSIS.value,
        BullSignalState.MURCIELAGO.value,
        BullSignalState.AVENTADOR.value,
    }
    assert result.scores["execution_ready"] is False


def test_miura_cannot_jump_directly_to_gallardo() -> None:
    payload = _base_payload()
    payload.execution_plan_complete = False
    payload.previous_state = BullSignalState.MIURA.value
    result = classify_bull_state(payload, load_thresholds())
    assert result.state != BullSignalState.GALLARDO.value


def test_collapse_analysis_cannot_jump_directly_to_gallardo() -> None:
    payload = _base_payload()
    payload.previous_state = BullSignalState.COLLAPSE_ANALYSIS.value
    payload.execution_plan_complete = False
    result = classify_bull_state(payload, load_thresholds())
    assert result.state != BullSignalState.GALLARDO.value


def test_aventador_promotion_fails_under_policy_veto() -> None:
    payload = _base_payload()
    payload.policy_veto = True
    result = classify_bull_state(payload, load_thresholds())
    assert result.state == BullSignalState.DIABLO.value


def test_aventador_promotion_fails_under_chaos_veto() -> None:
    payload = _base_payload()
    payload.chaos_veto = True
    result = classify_bull_state(payload, load_thresholds())
    assert result.state == BullSignalState.DIABLO.value


def test_huracan_cannot_bypass_aventador() -> None:
    payload = _base_payload()
    payload.momentum = 0.95
    payload.minimum_validation = 0.8
    payload.execution_plan_complete = False
    payload.entry_defined = False
    payload.sizing_defined = False
    payload.exit_defined = False
    payload.review_defined = False
    result = classify_bull_state(payload, load_thresholds())
    assert result.state == BullSignalState.HURACAN.value
    assert result.scores["execution_ready"] is False


def test_diablo_veto_blocks_new_risk() -> None:
    payload = _base_payload()
    payload.chaos_veto = True
    result = classify_bull_state(payload, load_thresholds())
    assert result.recommendation == "BLOCKED_BY_DIABLO"


def test_islero_shock_forces_reclassification() -> None:
    payload = _base_payload()
    payload.irreversible_event_shock = True
    result = classify_bull_state(payload, load_thresholds())
    assert result.state == BullSignalState.ISLERO.value


def test_opportunity_half_life_flags_transient_opportunities() -> None:
    short = compute_opportunity_half_life(0.9, 2.0, 1.0)
    long = compute_opportunity_half_life(0.9, 0.2, 0.1)
    assert short < long


def test_high_cluster_density_low_independence_increases_false_conviction() -> None:
    assert compute_false_conviction_risk(0.95, 0.2) > 0.9


def test_stable_normal_does_not_imply_stable_under_stress() -> None:
    payload = _base_payload()
    payload.stress_survival = 0.2
    result = classify_bull_state(payload, load_thresholds())
    assert result.scores["durability_score"] < load_thresholds()["theta_durability"]


def test_all_runtime_subreports_include_run_id() -> None:
    report = build_latent_signal_release_bull_report(
        runtime_state={},
        signal_refinery_report={},
        attention_proxy_report={},
        perception_control_report={},
        structural_admission_report={},
        write_runtime=False,
    )
    for subreport in report["subreports"].values():
        assert subreport["run_id"]


def test_pipeline_health_report_includes_latent_layer() -> None:
    report = build_pipeline_health_report(write_runtime=False)
    assert "latent_signal_release_bull_state" in report
    assert "latent_bull_state" in report
    assert "recommended_next_action" in report
