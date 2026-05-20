"""Tests for scripts/complex_systems_diagnostics.py — advisory-only doctrine.

The complex-systems doctrine layer is a deterministic diagnostic. These
tests prove the safety contract is preserved on every output, that signal
half-life decays / reinforces / erodes as specified, that source
independence distinguishes echo from independent confirmation, that
narrative cascade and winner's-curse rise with crowding, that the phase
classifier and chaos detector return ``insufficient_data`` on missing
inputs, that the ant-mill loop blocks promotion, that the queueing gate
trips on overload, that the Rawlsian sizer keeps India leverage capped
(not default) and ROW spot-only, that broken-windows discipline tracks
unrepaired losses, that the voting aggregator discounts echo consensus,
and — critically — that the final trade-quality decomposition never
becomes a broker order and that missing data degrades to
WAIT / REVIEW / INSUFFICIENT_DATA rather than a buy.
"""
from __future__ import annotations

import json

import pytest

from scripts.complex_systems_diagnostics import (
    ADVISORY_BIASES,
    CHAOS_STATES,
    INDIA_LEVERAGE_CEILING,
    PHASE_TRANSITION_STATES,
    ROW_LEVERAGE_CEILING,
    SAFETY_STAMPS,
    SIZE_BANDS,
    aggregate_model_votes,
    build_complex_systems_diagnostics,
    classify_chaos_regime,
    classify_phase_transition,
    compute_broken_windows_discipline,
    compute_queueing_attention_gate,
    compute_rawlsian_survival_sizing,
    compute_signal_half_life,
    compute_source_independence,
    compute_winner_curse_risk,
    decompose_trade_quality,
    detect_ant_mill,
    detect_firebreak_support,
    detect_keystone_node,
    detect_narrative_cascade,
    map_narrative_diffusion,
    map_sector_flocking,
)


# ---------------------------------------------------------------------------
# Safety invariants — every output must carry the canonical stamps.
# ---------------------------------------------------------------------------


def _assert_safety(payload: dict) -> None:
    assert isinstance(payload, dict), payload
    safety = payload.get("safety") or {}
    assert safety["advisory_status"] == "ADVISORY_ONLY"
    assert safety["execution_gate"] == "LOCKED"
    assert safety["broker_api_called"] is False
    assert safety["ai_execution_count"] == 0
    assert safety["execution_permission"] is False
    assert safety["can_execute"] is False
    assert safety["broker_order_id"] == "NONE"
    assert safety["human_review_required"] is True


def test_safety_stamps_constants():
    assert SAFETY_STAMPS["advisory_status"] == "ADVISORY_ONLY"
    assert SAFETY_STAMPS["execution_gate"] == "LOCKED"
    assert SAFETY_STAMPS["broker_api_called"] is False
    assert SAFETY_STAMPS["ai_execution_count"] == 0
    assert SAFETY_STAMPS["execution_permission"] is False
    assert SAFETY_STAMPS["can_execute"] is False
    assert SAFETY_STAMPS["broker_order_id"] == "NONE"
    assert SAFETY_STAMPS["human_review_required"] is True


@pytest.mark.parametrize("inputs", [
    None, {}, {"foo": "bar"}, [], [{}], {"ticker": "AAPL"},
])
def test_every_subcomponent_returns_safety_stamped_dict(inputs):
    sig = inputs if not isinstance(inputs, list) else (inputs[0] if inputs else {})
    cluster = inputs if isinstance(inputs, list) else [inputs] if isinstance(inputs, dict) else []
    _assert_safety(compute_signal_half_life(sig))
    _assert_safety(compute_source_independence(cluster))
    _assert_safety(detect_narrative_cascade(sig))
    _assert_safety(compute_winner_curse_risk(sig))
    _assert_safety(classify_phase_transition(sig))
    _assert_safety(detect_ant_mill(sig))
    _assert_safety(compute_queueing_attention_gate(sig))
    _assert_safety(compute_rawlsian_survival_sizing(sig))
    _assert_safety(compute_broken_windows_discipline(sig))
    _assert_safety(map_sector_flocking(cluster))
    _assert_safety(detect_keystone_node(sig, cluster=cluster))
    _assert_safety(detect_firebreak_support(sig))
    _assert_safety(aggregate_model_votes(cluster))
    _assert_safety(map_narrative_diffusion(cluster))
    _assert_safety(classify_chaos_regime(sig))
    _assert_safety(decompose_trade_quality({}, {}))
    _assert_safety(build_complex_systems_diagnostics(cluster))


def test_orchestrator_safety_on_empty_and_none():
    for payload in (build_complex_systems_diagnostics([]),
                    build_complex_systems_diagnostics(None)):
        _assert_safety(payload)
        assert payload["advisory_decision_bias"] in ADVISORY_BIASES
        assert payload["complex_systems_diagnostics"]["ai_execution_count"] == 0
        assert payload["complex_systems_diagnostics"]["advisory_only"] is True


# ---------------------------------------------------------------------------
# No broker / execution language may leak into any output.
# ---------------------------------------------------------------------------


def test_no_execution_language_anywhere():
    cluster = [
        {"model": "grok", "direction": 1, "intensity": 0.7, "freshness_score": 0.9,
         "age_hours": 2, "initial_strength": 0.8, "catalyst": "fed cut",
         "citation": "url", "model_agreement": 0.95, "price_momentum": 0.8,
         "evidence_strength": 0.7, "liquidity_confirmation": 0.7,
         "risk_reward": 0.8, "narrative_durability": 0.7, "learning_value": 0.6,
         "confidence": 0.9},
        {"model": "gemini", "direction": 1, "catalyst": "fed cut2",
         "citation": "url2", "confidence": 0.8},
    ]
    blob = json.dumps(build_complex_systems_diagnostics(cluster)).lower()
    # `broker_order_id: NONE` is the only allowed broker-prefixed field.
    blob_no_field = blob.replace('"broker_order_id": "none"', "")
    for forbidden in ("buy", "sell", "execute order", "place order",
                      "broker_api_called\": true", "submit order"):
        assert forbidden not in blob_no_field, forbidden


# ---------------------------------------------------------------------------
# 1-3. Signal half-life: decay, reinforcement, contradiction.
# ---------------------------------------------------------------------------


def test_half_life_decays_stale_signals():
    fresh = compute_signal_half_life(
        {"initial_strength": 0.8, "age_hours": 1, "half_life_hours": 48}
    )
    stale = compute_signal_half_life(
        {"initial_strength": 0.8, "age_hours": 200, "half_life_hours": 48}
    )
    assert fresh["live_signal_score"] > stale["live_signal_score"]
    assert stale["half_life_bucket"] == "expired"
    assert stale["stale_signal_flag"] is True
    assert fresh["half_life_bucket"] == "fresh"


def test_fresh_reinforcement_improves_live_score():
    base = compute_signal_half_life(
        {"initial_strength": 0.6, "age_hours": 24, "half_life_hours": 48}
    )
    reinforced = compute_signal_half_life(
        {"initial_strength": 0.6, "age_hours": 24, "half_life_hours": 48,
         "reinforcement_count": 3}
    )
    assert reinforced["live_signal_score"] > base["live_signal_score"]
    assert reinforced["reinforcement"] > 0


def test_contradiction_lowers_live_score():
    base = compute_signal_half_life(
        {"initial_strength": 0.7, "age_hours": 10, "half_life_hours": 48}
    )
    contradicted = compute_signal_half_life(
        {"initial_strength": 0.7, "age_hours": 10, "half_life_hours": 48,
         "contradiction_score": 0.5}
    )
    assert contradicted["live_signal_score"] < base["live_signal_score"]


def test_half_life_insufficient_data():
    out = compute_signal_half_life({})
    assert out["live_signal_score"] is None
    assert out["half_life_bucket"] == "insufficient_data"


# ---------------------------------------------------------------------------
# 2. Source independence: 5 repeated vs 5 independent catalysts.
# ---------------------------------------------------------------------------


def test_source_independence_echo_vs_independent():
    echo = [
        {"model": f"m{i}", "catalyst": "same public story", "citation": "u"}
        for i in range(5)
    ]
    independent = [
        {"model": f"m{i}", "catalyst": f"distinct catalyst {i}", "citation": "u"}
        for i in range(5)
    ]
    echo_out = compute_source_independence(echo)
    indep_out = compute_source_independence(independent)
    assert echo_out["unique_catalyst_count"] == 1
    assert indep_out["unique_catalyst_count"] == 5
    assert indep_out["independence_score"] > echo_out["independence_score"]
    assert echo_out["echo_chamber_risk"] > indep_out["echo_chamber_risk"]


def test_missing_citations_downgrade_independence():
    cited = [{"model": f"m{i}", "catalyst": f"c{i}", "citation": "u"}
             for i in range(4)]
    uncited = [{"model": f"m{i}", "catalyst": f"c{i}"} for i in range(4)]
    assert (compute_source_independence(cited)["independence_score"]
            > compute_source_independence(uncited)["independence_score"])


# ---------------------------------------------------------------------------
# 3. Narrative cascade rises with agreement+momentum, downgrades on low novelty.
# ---------------------------------------------------------------------------


def test_cascade_rises_with_agreement_and_momentum():
    low = detect_narrative_cascade(
        {"model_agreement": 0.2, "price_momentum": 0.2, "source_novelty": 0.8}
    )
    high = detect_narrative_cascade(
        {"model_agreement": 0.9, "price_momentum": 0.85, "volume_spike": 0.7,
         "source_novelty": 0.8}
    )
    assert high["cascade_score"] > low["cascade_score"]
    assert high["cascade_state"] in {"self_reinforcing", "crowded_cascade"}


def test_cascade_low_novelty_classified_crowded():
    crowded = detect_narrative_cascade(
        {"model_agreement": 0.95, "price_momentum": 0.9, "volume_spike": 0.8,
         "source_novelty": 0.1}
    )
    assert crowded["cascade_state"] == "crowded_cascade"


def test_cascade_insufficient_data():
    out = detect_narrative_cascade({})
    assert out["cascade_state"] == "insufficient_data"


# ---------------------------------------------------------------------------
# 4. Winner's curse rises with crowding / unanimity / late entry.
# ---------------------------------------------------------------------------


def test_winner_curse_rises_with_crowding():
    calm = compute_winner_curse_risk(
        {"model_unanimity": 0.1, "recent_return": 0.1, "narrative_saturation": 0.1}
    )
    crowded = compute_winner_curse_risk(
        {"model_unanimity": 0.95, "recent_return": 0.9,
         "narrative_saturation": 0.9, "late_entry": True}
    )
    assert crowded["winner_curse_risk"] > calm["winner_curse_risk"]
    assert crowded["late_entry_warning"] is True
    assert crowded["entry_quality_adjustment"] <= 0


# ---------------------------------------------------------------------------
# 5. Phase classifier insufficient_data on missing inputs.
# ---------------------------------------------------------------------------


def test_phase_insufficient_data():
    assert classify_phase_transition({})["phase_transition_state"] == "insufficient_data"
    assert classify_phase_transition(
        {"attention_growth": 0.5}
    )["phase_transition_state"] == "insufficient_data"


def test_phase_states_are_valid():
    out = classify_phase_transition(
        {"attention_growth": 0.7, "flow_confirmation": 0.7,
         "price_acceleration": 0.5, "contradiction_score": 0.1}
    )
    assert out["phase_transition_state"] in PHASE_TRANSITION_STATES
    assert out["phase_transition_state"] == "confirmed"


# ---------------------------------------------------------------------------
# 6. Ant mill blocks promotion when agreement high but independence low.
# ---------------------------------------------------------------------------


def test_ant_mill_blocks_high_agreement_low_independence():
    out = detect_ant_mill(
        {"model_agreement": 0.9}, independence_score=0.2
    )
    assert out["forced_contradiction_required"] is True
    assert out["promotion_block_reason"] == (
        "high_agreement_low_independence_requires_contradiction_search"
    )


def test_ant_mill_clears_when_independent():
    out = detect_ant_mill(
        {"model_agreement": 0.9, "contradiction_search_strength": 0.9,
         "invalidation_clarity": 0.9}, independence_score=0.9
    )
    assert out["promotion_block_reason"] is None


# ---------------------------------------------------------------------------
# 7. Queueing gate flags overload when intake exceeds capacity.
# ---------------------------------------------------------------------------


def test_queue_gate_normal_vs_overloaded():
    normal = compute_queueing_attention_gate(
        {"live_signal_count": 1, "operator_capacity": 10}
    )
    overloaded = compute_queueing_attention_gate(
        {"open_reconciliation_items": 8, "live_signal_count": 6,
         "unreconciled_manual_trades": 4, "moltbook_pending_review": 2,
         "operator_capacity": 10}
    )
    assert normal["intake_state"] == "normal"
    assert overloaded["queue_rho"] > 1.0
    assert overloaded["intake_state"] == "intake_freeze_recommended"
    assert overloaded["no_new_risk_flag"] is True


def test_queue_gate_defaults_capacity():
    out = compute_queueing_attention_gate({"live_signal_count": 2})
    assert out["capacity_was_defaulted"] is True


# ---------------------------------------------------------------------------
# 8. Rawlsian sizer: India capped not default, ROW spot-only, uncertainty cuts.
# ---------------------------------------------------------------------------


def test_rawlsian_india_leverage_capped_not_default():
    out = compute_rawlsian_survival_sizing(
        {"jurisdiction": "INDIA", "evidence_strength": 0.8}
    )
    assert out["leverage_ceiling"] == INDIA_LEVERAGE_CEILING
    assert out["leverage_allowed_boolean"] is True
    assert out["leverage_is_default"] is False
    assert "CEILING" in out["leverage_warning"]


def test_rawlsian_row_spot_only():
    out = compute_rawlsian_survival_sizing(
        {"jurisdiction": "US", "evidence_strength": 0.8}
    )
    assert out["leverage_ceiling"] == ROW_LEVERAGE_CEILING
    assert out["leverage_allowed_boolean"] is False
    assert out["spot_only"] is True


def test_rawlsian_uncertainty_reduces_size():
    certain = compute_rawlsian_survival_sizing(
        {"jurisdiction": "US", "uncertainty": 0.05},
        operator_load=0.0, crowding=0.0, moltbook_repair_state=1.0,
    )
    uncertain = compute_rawlsian_survival_sizing(
        {"jurisdiction": "US", "uncertainty": 0.95},
        operator_load=0.0, crowding=0.0, moltbook_repair_state=1.0,
    )
    assert (certain["survival_quality_score"]
            > uncertain["survival_quality_score"])
    assert SIZE_BANDS.index(certain["suggested_size_band"]) >= \
        SIZE_BANDS.index(uncertain["suggested_size_band"])


# ---------------------------------------------------------------------------
# 9 & 12. Broken windows: flag unrepaired losses; repair lowers decay.
# ---------------------------------------------------------------------------


def test_broken_windows_flags_unrepaired_losses():
    out = compute_broken_windows_discipline(
        {"closed_losses_without_moltbook": 2}
    )
    assert out["unrepaired_loss_count"] == 2
    assert out["moltbook_repair_complete_boolean"] is False
    assert out["promotion_block_if_unrepaired"] is True
    assert out["discipline_decay_score"] > 0


def test_moltbook_repaired_lowers_discipline_decay():
    unrepaired = compute_broken_windows_discipline(
        {"closed_losses_without_moltbook": 3}
    )
    repaired = compute_broken_windows_discipline(
        {"closed_losses_without_moltbook": 0, "unreviewed_moltbook_items": 0}
    )
    assert repaired["discipline_decay_score"] < unrepaired["discipline_decay_score"]
    assert repaired["moltbook_repair_complete_boolean"] is True


# ---------------------------------------------------------------------------
# 13. Voting aggregator adjusts naive consensus by independence + contradiction.
# ---------------------------------------------------------------------------


def test_voting_discounts_echo_consensus():
    echo = [
        {"model": f"m{i}", "direction": 1, "confidence": 0.8,
         "catalyst": "one story"} for i in range(5)
    ]
    out = aggregate_model_votes(echo)
    assert out["naive_consensus"] == 1.0
    assert out["independence_adjusted_consensus"] < out["naive_consensus"]
    assert out["aggregation_warning"] == (
        "naive_consensus_is_echo_not_independent_confirmation"
    )


def test_voting_contradiction_penalty():
    votes = [
        {"model": "a", "direction": 1, "confidence": 0.9, "catalyst": "x",
         "contradiction_score": 0.6},
        {"model": "b", "direction": 1, "confidence": 0.9, "catalyst": "y",
         "contradiction_score": 0.6},
    ]
    out = aggregate_model_votes(votes, independence_score=1.0)
    assert out["contradiction_penalty"] >= 0.4
    assert out["independence_adjusted_consensus"] < out["naive_consensus"]


# ---------------------------------------------------------------------------
# 10 & 11 & 14 & 15. Flocking, keystone, diffusion, chaos.
# ---------------------------------------------------------------------------


def test_flocking_isolated_vs_leader_follower():
    isolated = map_sector_flocking([{"sector": "energy", "ticker": "XOM"}])
    assert isolated["flocking_state"] == "isolated"
    flock = map_sector_flocking([
        {"sector": "tech", "ticker": "NVDA", "intensity": 0.9, "direction": 1},
        {"sector": "tech", "ticker": "AMD", "intensity": 0.5, "direction": 1},
    ])
    assert flock["flocking_state"] in {"leader_follower", "weak_cluster"}
    if flock["flocking_state"] == "leader_follower":
        assert flock["leader_hint"] == "NVDA"


def test_chaos_insufficient_and_nonlinear():
    assert classify_chaos_regime({})["chaos_state"] == "insufficient_data"
    nonlinear = classify_chaos_regime({"curl_score": 0.8, "volatility": 0.7})
    assert nonlinear["chaos_state"] == "nonlinear"
    assert nonlinear["max_safe_forecast_horizon"] < 48.0
    assert nonlinear["chaos_state"] in CHAOS_STATES


def test_diffusion_second_order_candidates():
    out = map_narrative_diffusion([
        {"sector": "ai", "ticker": "NVDA", "related_tickers": ["SMCI", "VRT"]},
        {"sector": "power", "ticker": "VST"},
    ])
    assert "SMCI" in out["second_order_candidates"]
    assert out["diffusion_state"] in {"spreading", "sector_wide", "contained"}


# ---------------------------------------------------------------------------
# 16. Final trade quality: never an order; missing data degrades safely.
# ---------------------------------------------------------------------------


def test_trade_quality_never_an_order():
    out = decompose_trade_quality(
        {"signal_strength": 0.9, "source_independence": 0.9, "freshness": 0.9,
         "narrative_durability": 0.9, "risk_reward": 0.9, "learning_value": 0.9},
        {"noise": 0.05, "crowding": 0.05, "chaos": 0.05, "contradiction": 0.05,
         "invalidation_ambiguity": 0.05, "operator_load": 0.05},
        confidence=1.0,
    )
    assert out["advisory_bias"] in ADVISORY_BIASES
    assert out["advisory_bias"] != "buy"
    blob = json.dumps(out).lower().replace('"broker_order_id": "none"', "")
    assert "buy" not in blob and "sell" not in blob


def test_trade_quality_hard_block_caps_at_review():
    out = decompose_trade_quality(
        {"signal_strength": 0.95, "source_independence": 0.95, "freshness": 0.95,
         "narrative_durability": 0.95, "risk_reward": 0.95, "learning_value": 0.95},
        {"noise": 0.01, "crowding": 0.01, "chaos": 0.01, "contradiction": 0.01,
         "invalidation_ambiguity": 0.01, "operator_load": 0.01},
        confidence=1.0, hard_block=True,
    )
    assert out["advisory_bias"] in {"review", "wait"}
    assert out["advisory_bias"] != "probe_candidate"


def test_missing_data_degrades_to_wait_or_insufficient_not_buy():
    out = decompose_trade_quality({}, {}, confidence=0.1)
    assert out["advisory_bias"] == "insufficient_data"
    # Orchestrator with no data must never produce a probe/buy bias.
    payload = build_complex_systems_diagnostics([{"ticker": "AAPL"}])
    assert payload["advisory_decision_bias"] in {
        "insufficient_data", "wait", "avoid", "watchlist", "review"
    }
    assert payload["advisory_decision_bias"] != "probe_candidate"


# ---------------------------------------------------------------------------
# Orchestrator integration: hard blocks propagate; high-quality reaches probe.
# ---------------------------------------------------------------------------


def test_orchestrator_hard_block_from_unrepaired_loss():
    cluster = [{"model": "grok", "direction": 1, "intensity": 0.8,
                "freshness_score": 0.9, "age_hours": 2, "initial_strength": 0.8,
                "catalyst": "c", "citation": "u", "risk_reward": 0.8,
                "evidence_strength": 0.8}]
    payload = build_complex_systems_diagnostics(
        cluster, moltbook_state={"closed_losses_without_moltbook": 2}
    )
    assert "moltbook_repair_incomplete" in payload["hard_blocks"]
    assert payload["advisory_decision_bias"] in {"review", "wait", "watchlist",
                                                 "avoid", "insufficient_data"}


def test_orchestrator_doctrine_string_present():
    payload = build_complex_systems_diagnostics([])
    assert payload["doctrine"] == "Survive first. Learn second. Scale later."
    assert payload["canonical_truth_source"] == "sqlite"
    assert payload["jsonl_role"] == "audit_fallback_only"
