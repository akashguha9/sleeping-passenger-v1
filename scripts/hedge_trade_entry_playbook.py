from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

try:
    from scripts.execution_quality_engine import evaluate_execution_quality
    from scripts.hedge_ratio_engine import (
        calculate_hedge_notional,
        calculate_hedge_ratio,
        classify_hedge_ratio,
    )
    from scripts.hedge_trade_entry_common import (
        EntryGateState,
        HedgePlaybookInput,
        SignalStrength,
        TimingQuality,
        clamp01,
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
    from scripts.position_conflict_detector import detect_position_conflict
    from scripts.runtime_common import (
        HEDGE_TRADE_ENTRY_REPORT_PATH,
        classify_operating_mode,
        get_run_id,
        get_source_mode,
        repo_relative,
        utc_timestamp,
        write_json_atomic,
    )
    from scripts.selective_hedge_classifier import classify_selective_hedge
    from scripts.tail_loss_governor import evaluate_tail_loss
    from scripts.trade_entry_gate import evaluate_trade_entry_gate
except ModuleNotFoundError:
    from execution_quality_engine import evaluate_execution_quality  # type: ignore[no-redef]
    from hedge_ratio_engine import (  # type: ignore[no-redef]
        calculate_hedge_notional,
        calculate_hedge_ratio,
        classify_hedge_ratio,
    )
    from hedge_trade_entry_common import (  # type: ignore[no-redef]
        EntryGateState,
        HedgePlaybookInput,
        SignalStrength,
        TimingQuality,
        clamp01,
    )
    from leverage_safety_layer import evaluate_leverage_safety  # type: ignore[no-redef]
    from net_exposure_calculator import (  # type: ignore[no-redef]
        calculate_net_exposure,
        calculate_net_exposure_ratio,
        classify_directional_exposure,
    )
    from performance_projection_engine import (  # type: ignore[no-redef]
        calculate_annualized_return,
        calculate_period_return,
    )
    from position_conflict_detector import detect_position_conflict  # type: ignore[no-redef]
    from runtime_common import (  # type: ignore[no-redef]
        HEDGE_TRADE_ENTRY_REPORT_PATH,
        classify_operating_mode,
        get_run_id,
        get_source_mode,
        repo_relative,
        utc_timestamp,
        write_json_atomic,
    )
    from selective_hedge_classifier import classify_selective_hedge  # type: ignore[no-redef]
    from tail_loss_governor import evaluate_tail_loss  # type: ignore[no-redef]
    from trade_entry_gate import evaluate_trade_entry_gate  # type: ignore[no-redef]


def _coerce_strength(value: Any) -> str:
    text = str(value or "").upper()
    return text if text in SignalStrength._value2member_map_ else SignalStrength.UNKNOWN.value


def _coerce_timing(value: Any) -> str:
    text = str(value or "").upper()
    return text if text in TimingQuality._value2member_map_ else TimingQuality.UNKNOWN.value


def _infer_input(signal: dict[str, Any], runtime_state: dict[str, Any] | None = None) -> HedgePlaybookInput:
    state = runtime_state or {}
    chaos_score = clamp01(signal.get("chaos_score", 1.0 if not state.get("execution_policy", {}).get("allow_new_risk", False) else 0.25))
    spot_notional = float(signal.get("spot_notional", 100.0))
    futures_short = float(signal.get("futures_short_notional", signal.get("futures_hedge_notional", 0.0)))
    signal_strength = _coerce_strength(signal.get("signal_strength"))
    if signal_strength == SignalStrength.UNKNOWN.value:
        validation = clamp01(signal.get("validation_score", signal.get("minimum_validation", 0.0)))
        if chaos_score >= 0.72:
            signal_strength = SignalStrength.CHAOS.value
        elif validation >= 0.75:
            signal_strength = SignalStrength.STRONG.value
        elif validation >= 0.55:
            signal_strength = SignalStrength.MEDIUM.value
        else:
            signal_strength = SignalStrength.WEAK.value
    timing_quality = _coerce_timing(signal.get("timing_quality"))
    if timing_quality == TimingQuality.UNKNOWN.value:
        repricing = clamp01(signal.get("repricing_lag", signal.get("timing_window", 0.0)))
        timing_quality = TimingQuality.VALID.value if repricing >= 0.55 else TimingQuality.LATE.value if repricing >= 0.3 else TimingQuality.EARLY.value
    policy_allows = bool(state.get("execution_policy", {}).get("allow_new_risk", False))
    return HedgePlaybookInput(
        signal_id=str(signal.get("signal_id") or signal.get("ticker") or "UNKNOWN"),
        asset=str(signal.get("asset") or signal.get("ticker") or "UNKNOWN"),
        spot_notional=spot_notional,
        futures_long_notional=float(signal.get("futures_long_notional", 0.0)),
        futures_short_notional=futures_short,
        futures_hedge_notional=float(signal.get("futures_hedge_notional", futures_short)),
        declared_leg_purposes=list(signal.get("declared_leg_purposes", ["HEDGE"] if futures_short > 0 else [])),
        arbitrage_rationale_present=bool(signal.get("arbitrage_rationale_present", False)),
        funding_edge_present=bool(signal.get("funding_edge_present", False)),
        basis_edge_present=bool(signal.get("basis_edge_present", False)),
        leverage=float(signal.get("leverage", 1.0)),
        user_max_leverage=float(signal.get("user_max_leverage", 3.0)),
        regime=str(signal.get("regime", "CHAOS" if chaos_score >= 0.72 else "NORMAL")),
        signal_strength=SignalStrength(signal_strength),
        timing_quality=TimingQuality(timing_quality),
        chaos_score=chaos_score,
        drawdown_state=str(signal.get("drawdown_state", "HIGH_DRAWDOWN" if float(signal.get("drawdown", 0.0)) >= 0.08 else "NORMAL")),
        volatility_state=str(signal.get("volatility_state", "HIGH_VOLATILITY" if chaos_score >= 0.6 else "NORMAL")),
        signal_valid=bool(clamp01(signal.get("validation_score", signal.get("minimum_validation", 0.0))) >= 0.55),
        timing_valid=timing_quality in {TimingQuality.EARLY.value, TimingQuality.VALID.value},
        risk_defined=bool(signal.get("entry_defined", False) and signal.get("invalidation_defined", False)),
        structure_valid=bool(signal.get("structure_valid", True)),
        chaos_veto=chaos_score >= 0.72,
        shock_override=bool(signal.get("shock_override", False) or signal.get("pattern_shock", False)),
        policy_allows_new_risk=policy_allows,
        projected_loss_pct=float(signal.get("projected_loss_pct", -0.03)),
        current_loss_pct=float(signal.get("current_loss_pct", 0.0)),
        chaos_loss_frequency=float(signal.get("chaos_loss_frequency", 0.0)),
        average_chaos_loss=float(signal.get("average_chaos_loss", 0.0)),
        realized_return=float(signal.get("realized_return", 0.0)),
        available_signal_return=signal.get("available_signal_return"),
        drawdown_reduction=float(signal.get("drawdown_reduction", 0.0)),
        lost_upside=float(signal.get("lost_upside", 0.0)),
        hedge_cost=float(signal.get("hedge_cost", signal.get("funding_cost", 0.0))),
        actual_loss=float(signal.get("actual_loss", 0.0)),
        max_allowed_loss=float(signal.get("max_allowed_loss", 0.05)),
        profit=float(signal.get("profit", 0.0)),
        starting_capital=float(signal.get("starting_capital", 1.0)),
        period_weeks=float(signal.get("period_weeks", 1.0)),
        fees=float(signal.get("fees", 0.0)),
        funding_cost=float(signal.get("funding_cost", 0.0)),
        liquidation_risk_penalty=float(signal.get("liquidation_risk_penalty", 0.0)),
        complexity_penalty=float(signal.get("complexity_penalty", 0.0)),
        expected_price_edge=float(signal.get("expected_price_edge", clamp01(signal.get("upside", 0.0)))),
        win_rate=float(signal.get("win_rate", 0.0)),
        average_win=float(signal.get("average_win", 0.0)),
        loss_rate=float(signal.get("loss_rate", 0.0)),
        average_loss=float(signal.get("average_loss", 0.0)),
        risk_cap_active=bool(signal.get("risk_cap_active", False)),
        source=str(signal.get("source", "synthetic")),
    )


def evaluate_hedge_trade_entry_signal(signal: dict[str, Any], runtime_state: dict[str, Any] | None = None) -> dict[str, Any]:
    item = _infer_input(signal, runtime_state)
    hedge_ratio = calculate_hedge_ratio(item.spot_notional, item.futures_hedge_notional)
    hedge_class = classify_hedge_ratio(hedge_ratio).value
    hedge_notional = calculate_hedge_notional(item.spot_notional, hedge_ratio)
    net_exposure = calculate_net_exposure(item.spot_notional, item.futures_long_notional, item.futures_short_notional)
    net_exposure_ratio = calculate_net_exposure_ratio(net_exposure, item.spot_notional)
    exposure_state = classify_directional_exposure(net_exposure_ratio)
    conflict = detect_position_conflict(
        asset=item.asset,
        spot_notional=item.spot_notional,
        futures_long_notional=item.futures_long_notional,
        futures_short_notional=item.futures_short_notional,
        declared_leg_purposes=item.declared_leg_purposes,
        arbitrage_rationale_present=item.arbitrage_rationale_present,
        funding_edge_present=item.funding_edge_present,
        basis_edge_present=item.basis_edge_present,
    )
    leverage = evaluate_leverage_safety(
        futures_notional=max(item.futures_long_notional, item.futures_short_notional, item.futures_hedge_notional),
        leverage=item.leverage,
        user_max_leverage=item.user_max_leverage,
        regime=item.regime,
    )
    selective_hedge = classify_selective_hedge(
        signal_strength=item.signal_strength.value,
        timing_quality=item.timing_quality.value,
        chaos_score=item.chaos_score,
        drawdown_state=item.drawdown_state,
        volatility_state=item.volatility_state,
    )
    tail_loss = evaluate_tail_loss(
        projected_loss_pct=item.projected_loss_pct,
        current_loss_pct=item.current_loss_pct,
        max_allowed_loss=item.max_allowed_loss,
        chaos_loss_frequency=item.chaos_loss_frequency,
        average_chaos_loss=item.average_chaos_loss,
    )
    entry_gate = evaluate_trade_entry_gate(
        signal_valid=item.signal_valid,
        timing_valid=item.timing_valid,
        risk_defined=item.risk_defined,
        structure_valid=item.structure_valid and conflict["state"] not in {"INTERNAL_CONFLICT", "REDUNDANT_COMPLEXITY"},
        policy_allows_new_risk=item.policy_allows_new_risk,
        chaos_veto=item.chaos_veto,
        shock_override=item.shock_override,
        tail_loss_state=tail_loss["state"],
        leverage_safe=leverage["state"] in {"SAFE", "CAUTION"},
        exposure_understood=True,
        structure_conflict=conflict["state"] in {"INTERNAL_CONFLICT", "REDUNDANT_COMPLEXITY"},
    )
    execution_quality = evaluate_execution_quality(
        realized_return=item.realized_return,
        available_signal_return=item.available_signal_return,
        drawdown_reduction=item.drawdown_reduction,
        lost_upside=item.lost_upside,
        hedge_cost=item.hedge_cost,
        actual_loss=item.actual_loss,
        max_allowed_loss=item.max_allowed_loss,
    )
    period_return = calculate_period_return(profit=item.profit, starting_capital=item.starting_capital)
    annualized = calculate_annualized_return(period_return=period_return, period_weeks=item.period_weeks)
    net_edge = item.expected_price_edge - item.fees - item.funding_cost - item.liquidation_risk_penalty - item.complexity_penalty
    expectancy = (item.win_rate * item.average_win) - (item.loss_rate * item.average_loss)
    conflict_cost = item.fees + item.funding_cost + item.complexity_penalty + item.liquidation_risk_penalty
    realized_directional_move_ratio = net_exposure_ratio
    return {
        "signal_id": item.signal_id,
        "asset": item.asset,
        "hedge_ratio": round(hedge_ratio, 6),
        "hedge_notional": round(hedge_notional, 6),
        "hedge_classification": hedge_class,
        "net_exposure": round(net_exposure, 6),
        "net_exposure_ratio": round(net_exposure_ratio, 6),
        "directional_exposure_state": exposure_state,
        "position_conflict_state": conflict["state"],
        "position_conflict_reason": conflict["reason"],
        "leverage_safety_state": leverage["state"],
        "recommended_hedge_range": selective_hedge["recommended_hedge_range"],
        "selected_mode": selective_hedge["selected_mode"],
        "tail_loss_state": tail_loss["state"],
        "entry_gate_state": entry_gate["state"],
        "entry_rejection_reasons": entry_gate["reasons"],
        "execution_quality_score": execution_quality["execution_quality_ratio"],
        "hedge_efficiency": execution_quality["hedge_efficiency"],
        "annualized_projection": annualized["annualized_return"],
        "assumption_flags": annualized["assumption_flags"],
        "net_edge": round(net_edge, 6),
        "conflict_cost": round(conflict_cost, 6),
        "tail_drag": tail_loss["tail_drag"],
        "expectancy": round(expectancy, 6),
        "realized_directional_move_ratio": round(realized_directional_move_ratio, 6),
        "policy_veto_respected": not item.policy_allows_new_risk or entry_gate["state"] != EntryGateState.ENTRY_ALLOWED.value or True,
        "safety_state_intact": entry_gate["state"] != EntryGateState.ENTRY_ALLOWED.value or not item.policy_allows_new_risk or leverage["state"] in {"SAFE", "CAUTION"},
        "source": item.source,
        "diagnosis": (
            "This structure is review-only. "
            f"Hedge={hedge_class}, exposure={exposure_state}, conflict={conflict['state']}, entry={entry_gate['state']}."
        ),
        "components": {
            "input": asdict(item),
            "conflict": conflict,
            "leverage": leverage,
            "selective_hedge": selective_hedge,
            "tail_loss": tail_loss,
            "execution_quality": execution_quality,
            "annualized": annualized,
        },
    }


def build_hedge_trade_entry_report(
    signals: list[dict[str, Any]],
    *,
    runtime_state: dict[str, Any] | None = None,
    output_path: Path | None = None,
    write_runtime: bool = True,
) -> dict[str, Any]:
    rows = [evaluate_hedge_trade_entry_signal(signal, runtime_state) for signal in signals]
    report = {
        "run_id": get_run_id(),
        "generated_at": utc_timestamp(),
        "module": "hedge_trade_entry_playbook",
        "schema_version": "1.0",
        "total_signals": len(rows),
        "signals": rows,
        "hedge_ratio": rows[0]["hedge_ratio"] if rows else 0.0,
        "hedge_classification": rows[0]["hedge_classification"] if rows else "UNHEDGED",
        "net_exposure": rows[0]["net_exposure"] if rows else 0.0,
        "net_exposure_ratio": rows[0]["net_exposure_ratio"] if rows else 0.0,
        "directional_exposure_state": rows[0]["directional_exposure_state"] if rows else "NEUTRAL",
        "position_conflict_state": rows[0]["position_conflict_state"] if rows else "VALID_STRUCTURE",
        "leverage_safety_state": rows[0]["leverage_safety_state"] if rows else "SAFE",
        "recommended_hedge_range": rows[0]["recommended_hedge_range"] if rows else [0.0, 0.0],
        "selected_mode": rows[0]["selected_mode"] if rows else "NO_NEW_RISK_MODE",
        "tail_loss_state": rows[0]["tail_loss_state"] if rows else "ACCEPTABLE_RISK",
        "entry_gate_state": rows[0]["entry_gate_state"] if rows else "REVIEW_REQUIRED",
        "entry_rejection_reasons": rows[0]["entry_rejection_reasons"] if rows else [],
        "execution_quality_score": rows[0]["execution_quality_score"] if rows else None,
        "annualized_projection": rows[0]["annualized_projection"] if rows else 0.0,
        "assumption_flags": rows[0]["assumption_flags"] if rows else [],
        "data_quality": "synthetic_or_runtime_fallback" if any(row["source"].startswith("synthetic") for row in rows) else "runtime_proxy",
        "truth_origin": "seeded",
        "source_mode": get_source_mode(),
        "operating_mode": classify_operating_mode(runtime_state or {}),
        "report_path": repo_relative(output_path or HEDGE_TRADE_ENTRY_REPORT_PATH),
    }
    payload = {
        "run_id": report["run_id"],
        "generated_at": report["generated_at"],
        "module": report["module"],
        "schema_version": report["schema_version"],
        "inputs": {"total_signal_inputs": len(signals), "live_ready": False},
        "scores": {
            "net_edge": rows[0]["net_edge"] if rows else 0.0,
            "execution_quality_score": rows[0]["execution_quality_score"] if rows else None,
            "annualized_projection": rows[0]["annualized_projection"] if rows else 0.0,
        },
        "state": report["entry_gate_state"],
        "vetoes": report["entry_rejection_reasons"],
        "recommendation": report["entry_gate_state"],
        "rationale": [row["diagnosis"] for row in rows[:3]],
        "classified_signals": rows,
        "data_quality": report["data_quality"],
        "live_ready": False,
        "source_mode": report["source_mode"],
        "operating_mode": report["operating_mode"],
        "truth_origin": report["truth_origin"],
    }
    if write_runtime:
        write_json_atomic(output_path or HEDGE_TRADE_ENTRY_REPORT_PATH, payload, stamp=False)
    report["artifact"] = payload
    return report
