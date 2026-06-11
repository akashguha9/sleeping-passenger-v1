"""Cherry-pick decision engine and full pipeline integration tests.

Doctrine under test: no score is naked, crash risk caps action, the user is
part of the risk model, no fire extinguisher no trade, same signal /
different circuit / different rule, and ADVISORY_ONLY everywhere.
"""

from __future__ import annotations

import copy
import json

from src.simulator.pipeline import evaluate_candidate_payload

STRONG_PAYLOAD: dict = {
    "ticker": "GRIDCO",
    "theme": "ai_grid_buildout",
    "opportunity_quality": 0.9,
    "hard_evidence_score": 0.85,
    "confirmation_level": 0.8,
    "predicted_probability": 0.65,
    "prediction_market": {
        "market_name": "AI grid bill passes 2026",
        "probability_before": 0.27,
        "probability_after": 0.54,
        "velocity": 0.8,
        "market_importance": 0.9,
        "market_liquidity": 0.7,
        "cross_source_confirmation": 0.8,
        "affected_themes": ["grid equipment", "transformers"],
    },
    "narrative": {
        "narrative": "AI datacenter grid strain",
        "mention_count": 40,
        "origin_count": 14,
        "independent_origin_count": 12,
        "source_quality": 0.8,
        "narrative_velocity": 0.4,
        "narrative_acceleration": 0.2,
    },
    "theme_assessment": {
        "policy_fit": 0.8,
        "macro_fit": 0.7,
        "sector_momentum": 0.6,
        "liquidity_support": 0.7,
        "risk_appetite": 0.6,
        "valuation_heat": 0.25,
        "crowding": 0.3,
        "regulatory_friction": 0.2,
    },
    "exposure": {
        "revenue_exposure": 0.7,
        "margin_sensitivity": 0.5,
        "backlog_linkage": 0.8,
        "customer_linkage": 0.5,
        "geographic_fit": 0.6,
        "policy_fit": 0.7,
        "supply_chain_position": 0.6,
    },
    "circuit": {"market_cap_usd": 5_000_000_000},
    "signals": [
        {
            "signal_type": "backlog",
            "raw_strength": 85,
            "signal_age_hours": 100,
            "source_quality": 0.9,
            "confirmation_multiplier": 1.1,
        },
        {
            "signal_type": "earnings_beat",
            "raw_strength": 75,
            "signal_age_hours": 48,
            "source_quality": 0.8,
        },
    ],
    "inflection": {
        "delta_narrative_velocity": 0.5,
        "delta_source_diversity": 0.4,
        "delta_volume_quality": 0.4,
        "delta_estimate_revision": 0.4,
        "delta_filing_evidence": 0.5,
        "delta_contradiction_pressure": 0.1,
    },
    "aero": {
        "evidence": {
            "filing_evidence": 0.85,
            "cash_flow_quality": 0.75,
            "backlog_evidence": 0.9,
            "insider_alignment": 0.6,
            "primary_source_confirmation": 0.8,
        },
        "noise_level": 0.2,
        "contradiction_level": 0.1,
        "duplication_level": 0.15,
        "ambiguity_level": 0.15,
        "promotional_bias": 0.1,
        "stock_specific_thrust": 0.6,
        "hidden_fundamental_improvement": 0.7,
        "catalyst_proximity_days": 20,
        "catalyst_confirmed": True,
        "regime_shift_level": 0.1,
        "data_quality": 0.9,
        "bull_force": 0.7,
        "bear_force": 0.3,
    },
    "risk_factors": {
        "high_valuation": 0.25,
        "rising_rates": 0.3,
        "low_volume": 0.15,
    },
    "triple_blind": {
        "blinded_metrics": {
            "growth_quality": 0.7,
            "margin_trend": 0.6,
            "balance_sheet_strength": 0.7,
            "valuation_discount": 0.5,
            "evidence_strength": 0.8,
        },
        "user_thesis": (
            "Backlog growth and policy catalyst with valuation support; "
            "key risk is regulatory delay."
        ),
    },
    "meal_box": {
        "thesis": "Grid equipment backlog inflecting on AI datacenter demand",
        "evidence": "Backlog up 40% YoY in latest 10-Q filings",
        "catalyst": "Policy vote and Q3 earnings within 30 days",
        "invalidation": "Exit if backlog growth drops below 10% or bill fails",
    },
    "driver": {
        "license_level": "pro_am",
        "thesis_logging_quality": 0.9,
        "invalidation_compliance": 0.9,
        "position_sizing_discipline": 0.85,
        "confirmation_patience": 0.8,
        "replay_audit_completion": 0.8,
        "calibration_honesty": 0.9,
    },
}


def _evaluate(mutations: dict | None = None) -> dict:
    payload = copy.deepcopy(STRONG_PAYLOAD)
    for dotted, value in (mutations or {}).items():
        target = payload
        keys = dotted.split(".")
        for key in keys[:-1]:
            target = target.setdefault(key, {})
        target[keys[-1]] = value
    return evaluate_candidate_payload(payload)


def test_final_state_is_not_a_naked_score() -> None:
    decision = _evaluate()["decision"]
    # The decision must carry a full breakdown, never just buy/no-buy.
    for key in (
        "final_state", "final_candidate_score", "decision_reason",
        "signal_grip", "crash_risk", "crash_density", "downforce", "drag",
        "aero_efficiency", "dirty_air", "meal_box_status", "driver_permission",
        "score_components", "gate_results", "circuit", "exposure_class",
    ):
        assert key in decision, f"missing {key}"
    assert decision["decision_reason"]
    assert decision["score_components"]
    assert decision["gate_results"]


def test_strong_candidate_reaches_an_actionable_review_state() -> None:
    out = _evaluate()
    decision = out["decision"]
    assert decision["final_state"] in (
        "active_watch", "buy_candidate", "high_conviction_candidate", "watchlist",
    )
    assert decision["final_candidate_score"] > 40
    assert decision["hard_conviction_ok"] is True


def test_high_crash_risk_caps_promotion_despite_high_opportunity() -> None:
    # Case study 4: opportunity high, crash density high -> watchlist at best.
    out = _evaluate(
        {
            "risk_factors": {
                "high_valuation": 0.9,
                "weak_fcf": 0.85,
                "rising_rates": 0.85,
                "insider_selling": 0.8,
            }
        }
    )
    decision = out["decision"]
    assert decision["gate_results"]["crash_gate"] is False
    assert decision["final_state"] in ("reject", "archive", "watchlist")
    assert "CRASH_GATE_BLOCKED" in decision["reason_codes"]


def test_bad_driver_caps_good_stock() -> None:
    # Case study 5: same stock, dangerous driver -> reduced permission.
    out = _evaluate(
        {
            "driver.violations": [
                {"type": "revenge_trading", "days_since": 1},
                {"type": "oversizing_under_crash_risk", "days_since": 2},
                {"type": "no_thesis_no_helmet", "days_since": 3},
            ]
        }
    )
    decision = out["decision"]
    clean = _evaluate()["decision"]
    assert decision["driver_permission"] < 1.0
    assert decision["final_candidate_score"] < clean["final_candidate_score"]
    assert "DRIVER_PERMISSION_REDUCED" in decision["reason_codes"]


def test_black_flagged_driver_interrupts_everything() -> None:
    out = _evaluate({"driver.revenge_trading_flags": 3})
    assert out["decision"]["final_state"] == "black_flag"


def test_missing_fire_extinguisher_blocks_buy_candidate() -> None:
    out = _evaluate({"meal_box.invalidation": None})
    decision = out["decision"]
    assert decision["meal_box_status"]["complete"] is False
    assert decision["final_state"] not in (
        "buy_candidate", "high_conviction_candidate",
    )
    assert "NO_FIRE_EXTINGUISHER_NO_TRADE" in decision["meal_box_status"]["reason_codes"]


def test_stale_soft_signals_cannot_reach_high_conviction() -> None:
    out = _evaluate(
        {
            "signals": [
                {
                    "signal_type": "viral_article",
                    "raw_strength": 95,
                    "signal_age_hours": 400,
                }
            ],
            "hard_evidence_score": 0.9,
        }
    )
    decision = out["decision"]
    assert decision["hard_conviction_ok"] is False
    assert decision["final_state"] not in ("high_conviction_candidate",)


def test_same_candidate_harder_circuit_stricter_rule() -> None:
    mid = _evaluate()["decision"]
    micro = _evaluate({"circuit.market_cap_usd": 50_000_000})["decision"]
    assert micro["circuit"] == "micro_cap"
    # Micro-cap demands a pro_driver license; this pro_am driver fails it.
    assert micro["license_ok_for_circuit"] is False
    assert mid["license_ok_for_circuit"] is True
    ladder_states = [
        "reject", "archive", "watchlist", "active_watch",
        "buy_candidate", "high_conviction_candidate",
    ]
    assert ladder_states.index(micro["final_state"]) <= ladder_states.index(
        mid["final_state"]
    )


def test_advisory_only_language_everywhere() -> None:
    out = _evaluate()
    assert "ADVISORY_ONLY" in out["advisory_note"]
    assert "ADVISORY_ONLY" in out["decision"]["decision_reason"]
    assert out["telemetry"]["advisory_status"] == "ADVISORY_ONLY"
    assert "Telemetry is truth." in out["doctrine"]


def test_no_candidate_promoted_without_telemetry() -> None:
    out = _evaluate()
    telemetry = out["telemetry"]
    for key in (
        "decision_time", "score_at_decision", "signal_grip_at_decision",
        "crash_risk_at_decision", "aero_metrics_at_decision",
        "driver_score_at_decision", "meal_box_status", "final_state",
        "decision_reason", "expected_time_window_days",
        "actual_outcome_placeholder", "calibration_status",
    ):
        assert key in telemetry, f"missing telemetry field {key}"
    assert telemetry["calibration_status"] == "pending"


def test_empty_payload_dies_on_the_ladder() -> None:
    out = evaluate_candidate_payload({})
    assert out["decision"]["final_state"] == "reject"


def test_full_output_is_json_serializable() -> None:
    serialized = json.dumps(_evaluate())
    assert "GRIDCO" in serialized
