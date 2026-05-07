from datetime import datetime, timezone

from scripts.signal_surface_engine import (
    BullSurfaceState,
    CureGateStatus,
    DamageClass,
    FinishHonestyFlag,
    RepairMode,
    SignalSurfaceEngine,
    SignalSurfaceInput,
    SurfaceDecision,
    SurfaceEngineConfig,
    build_signal_surface_report,
    clamp01,
    choose_repair_mode,
    classify_damage,
    compute_action_permission,
    compute_adhesion_score,
    compute_boundary_blending_score,
    compute_cure_gate,
    compute_finish_honesty_flag,
    compute_presentation_clarity_score,
    compute_residual_smoothness,
    compute_structural_correction,
    compute_substrate_integrity,
    compute_validation_protection_score,
    generate_recommended_next_steps,
    summarize_surface_report,
    weighted_geometric_score,
)


def make_input(**overrides: object) -> SignalSurfaceInput:
    payload = {
        "signal_id": "SIG-1",
        "timestamp": datetime(2026, 5, 7, tzinfo=timezone.utc),
        "source_count": 3,
        "source_reliability_score": 0.82,
        "raw_signal_strength": 0.78,
        "raw_noise_score": 0.12,
        "contradiction_score": 0.08,
        "volatility_score": 0.18,
        "liquidity_risk_score": 0.12,
        "latency_risk_score": 0.10,
        "narrative_clarity_score": 0.80,
        "data_completeness_score": 0.82,
        "schema_readiness_score": 0.78,
        "metadata_completeness_score": 0.76,
        "context_compatibility_score": 0.79,
        "execution_readiness_score": 0.35,
        "policy_veto": False,
        "chaos_veto": False,
        "heat_risk_score": 0.10,
        "time_since_major_change_minutes": 360.0,
        "stress_test_before_score": 0.70,
        "stress_test_after_score": 0.72,
        "momentum_score": 0.30,
        "notes": [],
    }
    payload.update(overrides)
    return SignalSurfaceInput(**payload)


def test_clamp01() -> None:
    assert clamp01(-1.0) == 0.0
    assert clamp01(0.5) == 0.5
    assert clamp01(2.0) == 1.0


def test_weighted_geometric_score_bounds() -> None:
    score = weighted_geometric_score({"a": 0.9, "b": 0.8}, {"a": 1.0, "b": 1.0})
    assert 0.0 <= score <= 1.0


def test_damage_classification_intact() -> None:
    assert classify_damage(make_input(), SurfaceEngineConfig()) == DamageClass.INTACT


def test_damage_classification_contaminated() -> None:
    report = classify_damage(make_input(raw_noise_score=0.9), SurfaceEngineConfig())
    assert report == DamageClass.CONTAMINATED


def test_damage_classification_contradicted() -> None:
    assert classify_damage(make_input(contradiction_score=0.85), SurfaceEngineConfig()) == DamageClass.CONTRADICTED


def test_repair_mode_restore() -> None:
    signal_input = make_input()
    integrity = compute_substrate_integrity(signal_input)
    assert choose_repair_mode(DamageClass.INTACT, integrity, signal_input, SurfaceEngineConfig()) == RepairMode.RESTORE


def test_repair_mode_rebuild() -> None:
    signal_input = make_input(source_reliability_score=0.2, data_completeness_score=0.2, raw_noise_score=0.7)
    integrity = compute_substrate_integrity(signal_input)
    assert choose_repair_mode(DamageClass.STRUCTURAL_DISTORTION, integrity, signal_input, SurfaceEngineConfig()) == RepairMode.REBUILD


def test_repair_mode_quarantine_on_policy_veto() -> None:
    signal_input = make_input(policy_veto=True)
    assert choose_repair_mode(DamageClass.CONTAMINATED, 0.9, signal_input, SurfaceEngineConfig()) == RepairMode.QUARANTINE


def test_substrate_integrity_score_bounds() -> None:
    score = compute_substrate_integrity(make_input())
    assert 0.0 <= score <= 1.0


def test_structural_correction_damage_multiplier() -> None:
    clean = compute_structural_correction(make_input(), DamageClass.INTACT)
    broken = compute_structural_correction(make_input(), DamageClass.STRUCTURAL_FAILURE)
    assert clean > broken


def test_residual_smoothness_penalizes_noise() -> None:
    low_noise = compute_residual_smoothness(make_input(raw_noise_score=0.1), 0.8)
    high_noise = compute_residual_smoothness(make_input(raw_noise_score=0.8), 0.8)
    assert low_noise > high_noise


def test_adhesion_score_uses_schema_and_context() -> None:
    low = compute_adhesion_score(make_input(schema_readiness_score=0.2, context_compatibility_score=0.2))
    high = compute_adhesion_score(make_input(schema_readiness_score=0.9, context_compatibility_score=0.9))
    assert high > low


def test_validation_protection_zero_on_chaos() -> None:
    assert compute_validation_protection_score(make_input(chaos_veto=True)) == 0.0


def test_boundary_blending_penalizes_interface_mismatch() -> None:
    good, _ = compute_boundary_blending_score(
        {
            "preparation": 0.9,
            "validation_protection": 0.9,
            "narrative_fit": 0.9,
            "substrate_integrity": 0.9,
            "adhesion": 0.9,
        }
    )
    bad, _ = compute_boundary_blending_score(
        {
            "preparation": 0.9,
            "validation_protection": 0.9,
            "narrative_fit": 0.9,
            "substrate_integrity": 0.9,
            "adhesion": 0.2,
        }
    )
    assert good > bad


def test_cure_gate_curing_before_threshold() -> None:
    status, score = compute_cure_gate(make_input(time_since_major_change_minutes=90), SurfaceEngineConfig())
    assert status == CureGateStatus.CURING
    assert score < 1.0


def test_cure_gate_stable_after_threshold() -> None:
    status, score = compute_cure_gate(make_input(time_since_major_change_minutes=300), SurfaceEngineConfig())
    assert status == CureGateStatus.STABLE
    assert score == 1.0


def test_cure_gate_shock_reset_on_contradiction() -> None:
    status, score = compute_cure_gate(make_input(contradiction_score=0.85), SurfaceEngineConfig())
    assert status == CureGateStatus.SHOCK_RESET
    assert score == 0.0


def test_presentation_capped_when_core_integrity_weak() -> None:
    score = compute_presentation_clarity_score(make_input(narrative_clarity_score=1.0), 0.7, 0.3)
    assert score <= 0.5


def test_finish_honesty_over_polished() -> None:
    flag = compute_finish_honesty_flag(0.90, 0.60, 0.85, 0.75, SurfaceEngineConfig())
    assert flag == FinishHonestyFlag.OVER_POLISHED


def test_action_permission_false_on_unstable_cure() -> None:
    engine = SignalSurfaceEngine()
    report = engine.evaluate(make_input(time_since_major_change_minutes=30))
    assert report.action_permission is False


def test_action_permission_false_on_low_validation() -> None:
    engine = SignalSurfaceEngine()
    report = engine.evaluate(make_input(source_reliability_score=0.3, contradiction_score=0.6))
    assert report.action_permission is False


def test_action_permission_true_for_clean_validated_signal() -> None:
    engine = SignalSurfaceEngine()
    report = engine.evaluate(make_input(execution_readiness_score=0.5, momentum_score=0.5))
    assert report.action_permission is True


def test_bull_mapping_diablo_on_chaos() -> None:
    report = SignalSurfaceEngine().evaluate(make_input(chaos_veto=True))
    assert report.bull_surface_state == BullSurfaceState.DIABLO_CHAOS_SURFACE_VETO


def test_bull_mapping_islero_on_shock() -> None:
    report = SignalSurfaceEngine().evaluate(make_input(contradiction_score=0.85))
    assert report.bull_surface_state == BullSurfaceState.ISLERO_SHOCK_RECLASSIFICATION


def test_bull_mapping_miura_for_raw_unvalidated_signal() -> None:
    report = SignalSurfaceEngine().evaluate(make_input(raw_signal_strength=0.9, contradiction_score=0.3, data_completeness_score=0.4, source_reliability_score=0.45))
    assert report.bull_surface_state == BullSurfaceState.MIURA_RAW_DENT


def test_bull_mapping_murcielago_for_repair_under_stress() -> None:
    report = SignalSurfaceEngine().evaluate(make_input(raw_noise_score=0.35, volatility_score=0.45))
    assert report.bull_surface_state == BullSurfaceState.MURCIELAGO_DURABILITY_REPAIR


def test_bull_mapping_aventador_for_validated_surface() -> None:
    report = SignalSurfaceEngine().evaluate(make_input(execution_readiness_score=0.4, momentum_score=0.2))
    assert report.bull_surface_state == BullSurfaceState.AVENTADOR_VALIDATED_SURFACE


def test_bull_mapping_gallardo_for_execution_ready() -> None:
    report = SignalSurfaceEngine().evaluate(make_input(execution_readiness_score=0.8))
    assert report.bull_surface_state == BullSurfaceState.GALLARDO_EXECUTION_FINISH


def test_huracan_cannot_bypass_veto() -> None:
    report = SignalSurfaceEngine().evaluate(make_input(momentum_score=0.95, raw_signal_strength=0.95, policy_veto=True))
    assert report.bull_surface_state != BullSurfaceState.HURACAN_FAST_TRACK_SURFACE
    assert report.action_permission is False


def test_report_contains_formula_trace() -> None:
    report = SignalSurfaceEngine().evaluate(make_input())
    assert "final_capped_score" in report.formula_trace
    assert "boundary_visibility" in report.formula_trace


def test_report_contains_recommended_next_steps() -> None:
    report = SignalSurfaceEngine().evaluate(make_input())
    assert report.recommended_next_steps


def test_final_score_capped_by_output_quality_ceiling() -> None:
    config = SurfaceEngineConfig(allowed_process_alpha=0.01)
    report = SignalSurfaceEngine(config).evaluate(make_input())
    assert report.final_capped_score <= report.output_quality_ceiling + config.allowed_process_alpha + 1e-9


def test_wax_cannot_fix_bad_repair() -> None:
    report = SignalSurfaceEngine().evaluate(
        make_input(
            source_reliability_score=0.2,
            data_completeness_score=0.2,
            raw_noise_score=0.7,
            narrative_clarity_score=1.0,
            metadata_completeness_score=1.0,
            context_compatibility_score=1.0,
            schema_readiness_score=1.0,
        )
    )
    assert report.presentation_clarity_score <= 0.5


def test_shape_first_finish_last_principle() -> None:
    report = SignalSurfaceEngine().evaluate(make_input(source_reliability_score=0.25, data_completeness_score=0.25, narrative_clarity_score=0.95))
    assert report.final_capped_score <= report.output_quality_ceiling + SurfaceEngineConfig().allowed_process_alpha


def test_boundary_visibility_drives_seamlessness() -> None:
    smooth = SignalSurfaceEngine().evaluate(make_input(schema_readiness_score=0.9, metadata_completeness_score=0.9, context_compatibility_score=0.9))
    rough = SignalSurfaceEngine().evaluate(make_input(schema_readiness_score=0.2, metadata_completeness_score=0.2, context_compatibility_score=0.2))
    assert smooth.boundary_blending_score > rough.boundary_blending_score


def test_summary_function_outputs_decision_blockers() -> None:
    report = SignalSurfaceEngine().evaluate(make_input(policy_veto=True))
    summary = summarize_surface_report(report)
    assert "blockers=" in summary
    assert "POLICY_VETO" in summary


def test_damage_classification_unknown() -> None:
    assert classify_damage(make_input(source_count=0), SurfaceEngineConfig()) in {DamageClass.UNKNOWN, DamageClass.STRUCTURAL_FAILURE}


def test_finish_honesty_masking_structural_weakness() -> None:
    flag = compute_finish_honesty_flag(0.7, 0.3, 0.7, 0.6, SurfaceEngineConfig())
    assert flag == FinishHonestyFlag.MASKING_STRUCTURAL_WEAKNESS


def test_compute_action_permission_direct_false_for_presentation_not_allowed() -> None:
    engine = SignalSurfaceEngine()
    report = engine.evaluate(make_input(source_reliability_score=0.3, data_completeness_score=0.3, narrative_clarity_score=0.9))
    assert report.action_permission is False


def test_surface_report_builder_contains_runtime_keys() -> None:
    report = build_signal_surface_report(
        [
            {
                "ticker": "RTX",
                "signal_strength_score": 0.8,
                "truth_probability": 0.75,
                "execution_readiness_score": 0.2,
            }
        ],
        runtime_state={"policy_state": "RESTRICTED", "truth_origin": "seeded"},
        write_runtime=False,
    )
    assert "report_path" in report
    assert "per_signal_reports" in report
    assert report["policy_state"] == "RESTRICTED"

