from __future__ import annotations

from scripts.execution_quality_engine import evaluate_execution_quality
from scripts.hedge_ratio_engine import (
    calculate_hedge_ratio,
    classify_hedge_ratio,
)
from scripts.hedge_trade_entry_common import HedgeClass
from scripts.hedge_trade_entry_playbook import (
    build_hedge_trade_entry_report,
    evaluate_hedge_trade_entry_signal,
)
from scripts.leverage_safety_layer import evaluate_leverage_safety
from scripts.net_exposure_calculator import (
    calculate_net_exposure,
    calculate_net_exposure_ratio,
    classify_directional_exposure,
)
from scripts.performance_projection_engine import (
    calculate_annualized_return,
    calculate_period_return,
)
from scripts.pipeline_health_report import build_pipeline_health_report
from scripts.position_conflict_detector import detect_position_conflict
from scripts.selective_hedge_classifier import classify_selective_hedge
from scripts.tail_loss_governor import evaluate_tail_loss
from scripts.trade_entry_gate import evaluate_trade_entry_gate


def test_hedge_ratio_classifications() -> None:
    assert calculate_hedge_ratio(100, 0) == 0.0
    assert classify_hedge_ratio(calculate_hedge_ratio(100, 0)) == HedgeClass.UNHEDGED
    assert classify_hedge_ratio(calculate_hedge_ratio(100, 20)) == HedgeClass.LIGHT_HEDGE
    assert classify_hedge_ratio(calculate_hedge_ratio(100, 50)) == HedgeClass.MODERATE_HEDGE
    assert classify_hedge_ratio(calculate_hedge_ratio(100, 100)) == HedgeClass.FULL_HEDGE
    assert classify_hedge_ratio(calculate_hedge_ratio(100, 150)) == HedgeClass.OVER_HEDGED


def test_hedge_ratio_invalid_spot_fails_cleanly() -> None:
    try:
        calculate_hedge_ratio(0, 10)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_net_exposure_cases() -> None:
    net = calculate_net_exposure(100, 0, 50)
    ratio = calculate_net_exposure_ratio(net, 100)
    assert net == 50
    assert ratio == 0.5
    assert classify_directional_exposure(ratio) == "NET_LONG"
    assert calculate_net_exposure(100, 0, 100) == 0
    assert classify_directional_exposure(calculate_net_exposure_ratio(0, 100)) == "NEUTRAL"
    assert calculate_net_exposure(100, 0, 150) == -50
    assert classify_directional_exposure(calculate_net_exposure_ratio(-50, 100)) == "NET_SHORT"
    assert calculate_net_exposure(100, 50, 50) == 100
    assert calculate_net_exposure(100, 100, 100) == 100


def test_position_conflict_detection() -> None:
    internal = detect_position_conflict(
        asset="BTC",
        spot_notional=0,
        futures_long_notional=100,
        futures_short_notional=100,
        declared_leg_purposes=[],
        arbitrage_rationale_present=False,
        funding_edge_present=False,
        basis_edge_present=False,
    )
    assert internal["state"] == "INTERNAL_CONFLICT"
    hedge = detect_position_conflict(
        asset="BTC",
        spot_notional=100,
        futures_long_notional=0,
        futures_short_notional=50,
        declared_leg_purposes=["hedge"],
        arbitrage_rationale_present=False,
        funding_edge_present=False,
        basis_edge_present=False,
    )
    assert hedge["state"] == "VALID_HEDGE"
    redundant = detect_position_conflict(
        asset="BTC",
        spot_notional=100,
        futures_long_notional=100,
        futures_short_notional=100,
        declared_leg_purposes=[],
        arbitrage_rationale_present=False,
        funding_edge_present=False,
        basis_edge_present=False,
    )
    assert redundant["state"] == "REDUNDANT_COMPLEXITY"
    review = detect_position_conflict(
        asset="BTC",
        spot_notional=0,
        futures_long_notional=100,
        futures_short_notional=100,
        declared_leg_purposes=[],
        arbitrage_rationale_present=True,
        funding_edge_present=False,
        basis_edge_present=False,
    )
    assert review["state"] == "STRUCTURE_REVIEW_READY"


def test_leverage_safety_states() -> None:
    assert evaluate_leverage_safety(futures_notional=100, leverage=2, user_max_leverage=3, regime="NORMAL")["state"] == "SAFE"
    assert evaluate_leverage_safety(futures_notional=100, leverage=3, user_max_leverage=3, regime="NORMAL")["state"] in {"SAFE", "CAUTION"}
    assert evaluate_leverage_safety(futures_notional=100, leverage=4, user_max_leverage=4, regime="NORMAL")["state"] in {"UNSAFE", "REJECTED", "CAUTION"}
    assert evaluate_leverage_safety(futures_notional=100, leverage=4, user_max_leverage=4, regime="CHAOS")["state"] == "REJECTED"
    assert evaluate_leverage_safety(futures_notional=100, leverage=1, user_max_leverage=4, regime="SHOCK")["state"] == "REJECTED"


def test_selective_hedge_ranges() -> None:
    strong = classify_selective_hedge(signal_strength="STRONG", timing_quality="VALID", chaos_score=0.1, drawdown_state="NORMAL", volatility_state="NORMAL")
    assert strong["recommended_hedge_range"] == [0.0, 0.2]
    medium = classify_selective_hedge(signal_strength="MEDIUM", timing_quality="VALID", chaos_score=0.2, drawdown_state="NORMAL", volatility_state="NORMAL")
    assert medium["recommended_hedge_range"] == [0.3, 0.5]
    weak = classify_selective_hedge(signal_strength="WEAK", timing_quality="VALID", chaos_score=0.2, drawdown_state="NORMAL", volatility_state="NORMAL")
    assert weak["recommended_hedge_range"] == [0.5, 0.7]
    chaos = classify_selective_hedge(signal_strength="CHAOS", timing_quality="VALID", chaos_score=0.9, drawdown_state="NORMAL", volatility_state="NORMAL")
    assert chaos["no_trade"] is True
    late = classify_selective_hedge(signal_strength="MEDIUM", timing_quality="LATE", chaos_score=0.2, drawdown_state="NORMAL", volatility_state="NORMAL")
    assert late["recommended_hedge_range"][0] >= 0.4


def test_tail_loss_governor_states() -> None:
    assert evaluate_tail_loss(projected_loss_pct=-0.03, current_loss_pct=-0.01)["state"] == "ACCEPTABLE_RISK"
    assert evaluate_tail_loss(projected_loss_pct=-0.055, current_loss_pct=-0.02)["state"] in {"HOLD_WITH_ALERT", "EXIT_REQUIRED"}
    assert evaluate_tail_loss(projected_loss_pct=-0.085, current_loss_pct=-0.02)["state"] == "CHAOS_LOSS_ZONE"
    assert evaluate_tail_loss(projected_loss_pct=-0.10, current_loss_pct=-0.03)["state"] == "EXIT_REQUIRED"


def test_trade_entry_gate_states() -> None:
    assert evaluate_trade_entry_gate(
        signal_valid=True,
        timing_valid=True,
        risk_defined=True,
        structure_valid=True,
        policy_allows_new_risk=True,
        chaos_veto=False,
        shock_override=False,
        tail_loss_state="ACCEPTABLE_RISK",
        leverage_safe=True,
        exposure_understood=True,
        structure_conflict=False,
    )["state"] == "ENTRY_ALLOWED"
    assert evaluate_trade_entry_gate(
        signal_valid=True,
        timing_valid=True,
        risk_defined=True,
        structure_valid=True,
        policy_allows_new_risk=True,
        chaos_veto=True,
        shock_override=False,
        tail_loss_state="ACCEPTABLE_RISK",
        leverage_safe=True,
        exposure_understood=True,
        structure_conflict=False,
    )["state"] == "NO_NEW_RISK"
    assert evaluate_trade_entry_gate(
        signal_valid=True,
        timing_valid=True,
        risk_defined=True,
        structure_valid=True,
        policy_allows_new_risk=True,
        chaos_veto=False,
        shock_override=True,
        tail_loss_state="ACCEPTABLE_RISK",
        leverage_safe=True,
        exposure_understood=True,
        structure_conflict=False,
    )["state"] == "ENTRY_REJECTED"
    assert evaluate_trade_entry_gate(
        signal_valid=True,
        timing_valid=True,
        risk_defined=False,
        structure_valid=True,
        policy_allows_new_risk=True,
        chaos_veto=False,
        shock_override=False,
        tail_loss_state="ACCEPTABLE_RISK",
        leverage_safe=True,
        exposure_understood=True,
        structure_conflict=False,
    )["state"] == "REVIEW_REQUIRED"


def test_execution_quality_metrics() -> None:
    assert evaluate_execution_quality(
        realized_return=0.04,
        available_signal_return=0.08,
        drawdown_reduction=0.03,
        lost_upside=0.01,
        hedge_cost=0.0,
        actual_loss=0.01,
        max_allowed_loss=0.05,
    )["execution_quality_ratio"] == 0.5
    assert evaluate_execution_quality(
        realized_return=0.08,
        available_signal_return=0.08,
        drawdown_reduction=0.03,
        lost_upside=0.01,
        hedge_cost=0.0,
        actual_loss=0.01,
        max_allowed_loss=0.05,
    )["execution_quality_ratio"] == 1.0
    assert evaluate_execution_quality(
        realized_return=0.10,
        available_signal_return=0.08,
        drawdown_reduction=0.03,
        lost_upside=0.01,
        hedge_cost=0.0,
        actual_loss=0.01,
        max_allowed_loss=0.05,
    )["execution_quality_ratio"] > 1.0
    assert evaluate_execution_quality(
        realized_return=0.10,
        available_signal_return=0.0,
        drawdown_reduction=0.03,
        lost_upside=0.01,
        hedge_cost=0.0,
        actual_loss=0.01,
        max_allowed_loss=0.05,
    )["execution_quality_ratio"] is None


def test_performance_projection_values() -> None:
    period = calculate_period_return(profit=21, starting_capital=3100)
    assert round(period, 5) == 0.00677
    annualized = calculate_annualized_return(period_return=period, period_weeks=3)
    assert 0.12 <= annualized["annualized_return"] <= 0.13
    assert "projection_only" in annualized["assumption_flags"]


def test_sample_valid_structure_output() -> None:
    report = evaluate_hedge_trade_entry_signal(
        {
            "signal_id": "BTC1",
            "asset": "BTC",
            "spot_notional": 100,
            "futures_short_notional": 50,
            "signal_strength": "MEDIUM",
            "timing_quality": "VALID",
            "validation_score": 0.7,
            "minimum_validation": 0.7,
            "entry_defined": True,
            "invalidation_defined": True,
            "structure_valid": True,
            "risk_cap_active": True,
            "source": "synthetic",
        },
        runtime_state={"execution_policy": {"allow_new_risk": True}},
    )
    assert report["hedge_ratio"] == 0.5
    assert report["hedge_classification"] == "MODERATE_HEDGE"
    assert report["net_exposure"] == 50.0
    assert report["net_exposure_ratio"] == 0.5
    assert report["directional_exposure_state"] == "NET_LONG"
    assert report["position_conflict_state"] == "VALID_HEDGE"
    assert report["entry_gate_state"] == "ENTRY_ALLOWED"


def test_bad_structure_rejected() -> None:
    report = evaluate_hedge_trade_entry_signal(
        {
            "signal_id": "BTC2",
            "asset": "BTC",
            "spot_notional": 100,
            "futures_long_notional": 100,
            "futures_short_notional": 100,
            "validation_score": 0.8,
            "minimum_validation": 0.8,
            "entry_defined": True,
            "invalidation_defined": True,
            "risk_cap_active": True,
            "source": "synthetic",
        },
        runtime_state={"execution_policy": {"allow_new_risk": True}},
    )
    assert report["net_exposure"] == 100.0
    assert report["position_conflict_state"] in {"REDUNDANT_COMPLEXITY", "INTERNAL_CONFLICT"}
    assert report["entry_gate_state"] == "ENTRY_REJECTED"
    assert any("structure conflict" in reason.lower() or "same-asset" in report["position_conflict_reason"].lower() for reason in report["entry_rejection_reasons"] + [report["position_conflict_reason"]])


def test_runtime_report_contains_required_fields() -> None:
    report = build_hedge_trade_entry_report([], runtime_state={}, write_runtime=False)
    assert report["report_path"].endswith("hedge_trade_entry_report.json")
    assert "hedge_ratio" in report
    assert report["artifact"]["run_id"]


def test_pipeline_health_report_includes_hedge_fields() -> None:
    report = build_pipeline_health_report(write_runtime=False)
    assert "hedge_trade_entry_state" in report
    assert "hedge_ratio" in report
    assert "entry_gate_state" in report
