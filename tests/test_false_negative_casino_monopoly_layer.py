from __future__ import annotations

from scripts.false_negative_casino_monopoly_layer import (
    build_false_negative_casino_monopoly_report,
    compute_bluff_truth_estimator,
    compute_bull_state,
    compute_decision_quality_splitter,
    compute_double_blind_guard,
    compute_false_break,
    compute_false_negative_risk,
    compute_jail_mode,
    compute_joker_shock,
    compute_monopoly_cluster,
    compute_number_theory_recurrence,
    compute_reentry_state,
    compute_role_capability_fit,
    compute_structural_stabilizer,
    compute_table_context,
)
from scripts.pipeline_health_report import build_pipeline_health_report


def test_longstaff_style_low_visible_output_becomes_glue_asset() -> None:
    report = compute_structural_stabilizer(
        {
            "coverage": 0.88,
            "availability": 0.86,
            "continuity": 0.92,
            "low_error_rate": 0.90,
            "friction_reduction": 0.95,
            "visible_output": 0.24,
        }
    )
    assert report["structural_stabilizer_state"] == "GLUE_ASSET"
    assert report["structural_stabilizer_score"] >= 0.88


def test_joelinton_style_role_misfit_promotes_alternate_role() -> None:
    report = compute_role_capability_fit(
        {
            "coverage": 0.82,
            "continuity": 0.86,
            "friction_reduction": 0.84,
            "validation": 0.42,
            "execution": 0.38,
            "follow_through": 0.30,
            "discipline": 0.80,
            "truth": 0.72,
            "stability": 0.78,
            "novelty": 0.18,
            "asymmetry": 0.25,
            "timing": 0.22,
            "attention": 0.20,
            "rule_awareness": 0.76,
            "current_role": "WATCHLIST",
        }
    )
    assert report["current_role_fit_state"] in {"MISCAST", "SEVERE_MISCAST"}
    assert report["best_role"] == "STABILIZER"
    assert report["best_role_fit_score"] > report["role_capability_fit_score"]


def test_rejected_signal_with_hidden_structural_value_requires_recheck() -> None:
    report = compute_false_negative_risk(
        {
            "role_misfit": 0.62,
            "context_misfit": 0.54,
            "metric_blindness": 0.60,
            "structural_value_unmeasured": 0.74,
            "asymmetric_upside": 0.58,
        }
    )
    assert report["false_negative_state"] in {"RECHECK_REQUIRED", "LIKELY_FALSE_NEGATIVE"}


def test_high_confidence_low_evidence_becomes_dangerous_confidence() -> None:
    report = compute_double_blind_guard(
        {"confidence": 0.9, "evidence_quality": 0.2, "misperception": 0.8}
    )
    assert report["double_blind_state"] == "DANGEROUS_CONFIDENCE"


def test_good_process_bad_outcome_kept_separate() -> None:
    report = compute_decision_quality_splitter(
        {"decision_quality_score": 0.82, "outcome_score": 0.21}
    )
    assert report["decision_quality_state"] == "GOOD_PROCESS_BAD_OUTCOME"


def test_dangerous_table_triggers_no_play_table() -> None:
    report = compute_table_context(
        {
            "volatility": 0.95,
            "liquidity": 0.25,
            "crowding": 0.88,
            "participant_quality": 0.22,
            "deception_risk": 0.91,
            "regime_stability": 0.14,
            "chaos_level": 0.92,
            "policy_restriction": 0.8,
            "prior_false_break_count": 3,
        }
    )
    assert report["table_context_state"] == "NO_PLAY_TABLE"


def test_clustered_assets_score_higher_than_isolated_assets() -> None:
    isolated = compute_monopoly_cluster(
        {
            "asset_count": 1,
            "synergy": 0.35,
            "control": 0.35,
            "persistence": 0.35,
            "cashflow_potential": 0.35,
            "validation": 0.35,
            "durability": 0.35,
            "execution_survivability": 0.35,
        }
    )
    clustered = compute_monopoly_cluster(
        {
            "asset_count": 4,
            "synergy": 0.82,
            "control": 0.76,
            "persistence": 0.80,
            "cashflow_potential": 0.78,
            "validation": 0.78,
            "durability": 0.80,
            "execution_survivability": 0.74,
        }
    )
    assert clustered["asset_cluster_score"] > isolated["asset_cluster_score"]


def test_chaos_triggers_jail_mode() -> None:
    report = compute_jail_mode(
        {
            "chaos": 0.92,
            "overexposure": 0.2,
            "edge_compression": 0.3,
            "model_uncertainty": 0.2,
            "policy_restriction": False,
            "high_false_break_risk": False,
            "dangerous_table": False,
            "dangerous_confidence": False,
            "hard_veto": False,
            "existing_cashflow": 0.5,
            "movement_risk": 0.9,
        }
    )
    assert report["jail_mode_active"] is True
    assert report["jail_mode_state"] == "FORCED_RESTRAINT"


def test_jail_does_not_jump_directly_to_deploy() -> None:
    report = compute_reentry_state(
        {
            "state_before": "JAIL",
            "jail_mode_active": False,
            "policy_clear": True,
            "signal_strength": 0.95,
            "stability": 0.92,
            "probe_success": 0.95,
            "follow_through": 0.94,
            "chaos": 0.05,
            "deception_risk": 0.05,
            "false_break_risk": 0.05,
        }
    )
    assert report["reentry_state"] == "CONFIRMATION_REQUIRED"
    assert report["reentry_state_after"] == "CONFIRM"


def test_first_breakout_without_persistence_becomes_false_break_risk() -> None:
    report = compute_false_break(
        {
            "persistence": 0.08,
            "follow_through": 0.12,
            "stability": 0.18,
            "participation_quality": 0.35,
            "contradiction_resistance": 0.22,
            "initial_signal_strength": 0.74,
            "deception_risk": 0.61,
            "chaos": 0.48,
        }
    )
    assert report["false_break_state"] == "FALSE_BREAK_RISK"


def test_high_aggression_with_weak_foundation_looks_like_bluff() -> None:
    report = compute_bluff_truth_estimator(
        {
            "aggression": 0.92,
            "foundation": 0.15,
            "follow_through": 0.18,
            "incentive_to_mislead": 0.8,
            "information_asymmetry": 0.75,
            "declared_observed_gap": 0.7,
            "observed_true_gap_estimate": 0.64,
        }
    )
    assert report["truth_state"] in {"POSSIBLE_BLUFF", "LIKELY_BLUFF"}


def test_joker_shock_forces_model_reset_or_islero() -> None:
    shock = compute_joker_shock(
        {
            "surprise": 1.0,
            "impact": 1.0,
            "rule_change": 1.0,
            "joker_event_detected": True,
        }
    )
    bull = compute_bull_state(
        {
            "policy_veto": False,
            "chaos": 0.1,
            "joker_event_detected": shock["joker_event_detected"],
            "jail_mode_active": False,
            "validation": 0.8,
            "durability": 0.8,
            "execution_survivability": 0.8,
            "momentum": 0.3,
            "novelty": 0.4,
            "policy_clear": True,
            "actionable": False,
            "previous_bull_state": "MURCIELAGO",
        }
    )
    assert shock["shock_state"] in {"JOKER_EVENT", "MODEL_RESET_REQUIRED"}
    assert bull["bull_state"] == "ISLERO"


def test_chaos_forces_diablo_and_outranks_huracan() -> None:
    bull = compute_bull_state(
        {
            "policy_veto": False,
            "chaos": 0.92,
            "joker_event_detected": False,
            "jail_mode_active": False,
            "validation": 0.92,
            "durability": 0.92,
            "execution_survivability": 0.92,
            "momentum": 0.95,
            "novelty": 0.55,
            "policy_clear": True,
            "actionable": True,
            "previous_bull_state": "UNKNOWN",
        }
    )
    assert bull["bull_state"] == "DIABLO"


def test_policy_veto_outranks_every_bull_state() -> None:
    bull = compute_bull_state(
        {
            "policy_veto": True,
            "chaos": 0.1,
            "joker_event_detected": False,
            "jail_mode_active": False,
            "validation": 0.95,
            "durability": 0.95,
            "execution_survivability": 0.95,
            "momentum": 0.95,
            "novelty": 0.1,
            "policy_clear": False,
            "actionable": True,
            "previous_bull_state": "UNKNOWN",
        }
    )
    assert bull["bull_state"] == "JAIL"
    assert bull["policy_veto_respected"] is True


def test_recurrence_insufficient_data_for_small_samples() -> None:
    report = compute_number_theory_recurrence({"intervals": [60, 60, 60]})
    assert report["cycle_state"] == "INSUFFICIENT_DATA"


def test_strong_repeated_intervals_produce_strong_recurrence() -> None:
    report = compute_number_theory_recurrence({"intervals": [60, 60, 60, 60, 60, 60]})
    assert report["cycle_state"] == "STRONG_RECURRENCE"
    assert report["recurrence_score"] >= 0.95


def test_no_recurrence_does_not_falsely_promote_signal() -> None:
    report = compute_number_theory_recurrence({"intervals": [61, 113, 47, 89, 131]})
    assert report["cycle_state"] in {"NO_RECURRENCE", "WEAK_RECURRENCE"}
    assert report["recurrence_score"] < 0.55


def test_pipeline_health_report_surfaces_new_layer_and_keeps_policy_veto_absolute() -> None:
    report = build_pipeline_health_report(write_runtime=False)
    assert "false_negative_casino_monopoly_layer" in report
    assert "structural_stabilizer_score" in report
    assert "bull_state" in report
    assert report["policy_veto_outranks_layer"] is True
    assert report["safety_state_intact"] is True
    assert report["can_deploy_capital"] is False
