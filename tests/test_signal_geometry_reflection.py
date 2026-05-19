"""Tests for scripts/signal_geometry_reflection.py — advisory-only layer.

The geometry reflection layer is a deterministic diagnostic. These
tests prove the safety contract is preserved, that missing data
degrades to WAIT / INSUFFICIENT_DATA rather than BUY, that high
chaos / Mobius inversion lower confidence and add vetoes, that India
leverage is capped (not default), that ROW is spot-only, and that the
module never claims canonical truth for JSONL.
"""
from __future__ import annotations

import pytest

from scripts.signal_geometry_reflection import (
    ADVISORY_RECOMMENDATIONS,
    INDIA_LEVERAGE_CEILING,
    NOISE_CLASSES,
    ROW_LEVERAGE_CEILING,
    SAFETY_STAMPS,
    build_signal_cell,
    build_signal_geometry_diagnostics,
    classify_chaos_attractor,
    classify_decision_partition,
    classify_duplicate_stale_pre_veto,
    classify_mobius_inversion,
    classify_noise_taxonomy,
    classify_thermodynamic_exposure,
    compute_constrained_first_priority,
    compute_field_diagnostics,
    compute_invariant_ratio,
    compute_phase_alignment_state,
    compute_regime_composition,
    compute_risk_route,
    compute_signal_derivatives,
    detect_hidden_macro_driver,
    extract_narrative_features,
    monte_carlo_survival_stub,
    summarize_leverage_policy,
    summarize_moltbook_recursive_state,
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
    """Every public sub-component is safety-stamped on every input."""
    sig = inputs if not isinstance(inputs, list) else (inputs[0] if inputs else {})
    cluster = inputs if isinstance(inputs, list) else [inputs] if isinstance(inputs, dict) else []
    _assert_safety(build_signal_cell(sig))
    _assert_safety(classify_duplicate_stale_pre_veto(sig))
    _assert_safety(extract_narrative_features(sig))
    _assert_safety(classify_decision_partition(sig))
    _assert_safety(compute_risk_route(sig))
    _assert_safety(compute_constrained_first_priority(sig))
    _assert_safety(compute_invariant_ratio(sig))
    _assert_safety(compute_signal_derivatives(0.5))
    _assert_safety(compute_phase_alignment_state(sig))
    _assert_safety(compute_regime_composition(cluster))
    _assert_safety(monte_carlo_survival_stub(sig))
    _assert_safety(compute_field_diagnostics(cluster))
    _assert_safety(classify_thermodynamic_exposure(sig, cluster))
    _assert_safety(detect_hidden_macro_driver(cluster))
    _assert_safety(summarize_moltbook_recursive_state(sig))
    _assert_safety(classify_noise_taxonomy(sig))
    _assert_safety(classify_chaos_attractor(sig))
    _assert_safety(classify_mobius_inversion(sig))
    _assert_safety(summarize_leverage_policy(sig))


def test_orchestrator_safety_on_empty():
    payload = build_signal_geometry_diagnostics([])
    _assert_safety(payload)
    assert payload["recommendation"] in ADVISORY_RECOMMENDATIONS
    assert payload["signal_count"] == 0


def test_orchestrator_safety_on_none():
    payload = build_signal_geometry_diagnostics(None)
    _assert_safety(payload)
    assert payload["recommendation"] in ADVISORY_RECOMMENDATIONS


# ---------------------------------------------------------------------------
# Broker / execution language must be absent from every output.
# ---------------------------------------------------------------------------


# The canonical safety stamps include `broker_order_id: NONE` as a deliberate
# record-keeping denial (see docs/ADVISORY_ONLY_SAFETY_MODEL.md), so the
# substring `broker_order` legitimately appears as a *field name*. We forbid
# only the *active* phrasings that would imply execution.
FORBIDDEN_TOKENS = (
    "place_order", "execute_trade", "trade_now", "auto_trade",
    "broker_connected", "ai_approved", "permission_granted",
    "authorized_to_trade", "order_ready", "place order", "execute trade",
)


def _flatten(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _flatten(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _flatten(v)
    else:
        yield str(obj)


def test_no_execution_language_in_geometry_outputs():
    payload = build_signal_geometry_diagnostics([
        {"ticker": "AAPL", "narrative_intensity": 0.7, "freshness_score": 0.7,
         "source_reliability": 0.8, "market_confirmation": 0.5}
    ])
    blob = "\n".join(_flatten(payload)).lower()
    for token in FORBIDDEN_TOKENS:
        assert token not in blob, f"forbidden token {token!r} present in payload"


def test_orchestrator_never_recommends_execution():
    cluster = [
        {"source_name": "Reuters", "narrative_intensity": 0.6,
         "freshness_score": 0.9, "source_reliability": 0.9,
         "market_confirmation": 0.8, "evidence_strength": 0.8,
         "liquidity_score": 0.9, "invalidation_strength": 0.8,
         "chaos_score": 0.1, "contradiction_score": 0.05},
    ]
    payload = build_signal_geometry_diagnostics(cluster)
    # The strongest positive label allowed is review_candidate.
    assert payload["recommendation"] in {
        "review_candidate", "watch", "observe", "review_later",
        "decay_archive", "human_review_only", "wait_insufficient_data",
    }
    assert "buy" not in payload["recommendation"].lower()
    assert "sell" not in payload["recommendation"].lower()
    assert "execute" not in payload["recommendation"].lower()


# ---------------------------------------------------------------------------
# Missing data must degrade to WAIT / INSUFFICIENT_DATA, never BUY.
# ---------------------------------------------------------------------------


def test_missing_data_does_not_produce_strong_recommendation():
    payload = build_signal_geometry_diagnostics([{"ticker": "XYZ"}])
    rec = payload["recommendation"]
    assert rec in {"watch", "observe", "decay_archive",
                    "wait_insufficient_data", "review_later"}
    assert rec != "review_candidate"


def test_risk_route_missing_data_penalty_propagates():
    res = compute_risk_route({})
    assert res["missing_data_penalty"] >= 0.5
    assert res["advisory_decision"] == "wait_insufficient_data"


def test_monte_carlo_insufficient_data_path():
    res = monte_carlo_survival_stub({})
    assert res["method"] == "insufficient_data"
    assert res["risk_of_ruin_flag"] is False
    assert res["simulated_survival_probability"] is None


# ---------------------------------------------------------------------------
# High curl / chaos / Mobius adds vetoes and downgrades.
# ---------------------------------------------------------------------------


def test_high_mobius_inversion_increases_risk_and_downgrades():
    payload = build_signal_geometry_diagnostics([{
        "source_name": "grok", "source_family": "ai_report",
        "direction": 1, "narrative_intensity": 0.9,
        "crowding_score": 0.85, "ai_consensus_score": 0.85,
        "fragility_score": 0.8, "market_confirmation": 0.2,
        "freshness_score": 0.6, "source_reliability": 0.6,
        "evidence_strength": 0.5, "liquidity_score": 0.4,
        "chaos_score": 0.4, "contradiction_score": 0.2,
        "invalidation_strength": 0.4,
    }])
    diag = payload["signal_geometry_diagnostics"]["mobius_inversion"]
    assert diag["mobius_inversion_risk"] >= 0.5
    assert any("mobius" in v.lower() for v in payload["vetoes"])
    assert payload["recommendation"] in {
        "decay_archive", "watch", "wait_insufficient_data",
        "human_review_only",
    }
    assert payload["recommendation"] != "review_candidate"


def test_chaos_attractor_flag_triggers_veto():
    payload = build_signal_geometry_diagnostics([{
        "ticker": "AAPL", "chaos_score": 0.9, "sensitivity_score": 0.9,
        "freshness_score": 0.8, "source_reliability": 0.8,
        "evidence_strength": 0.6, "market_confirmation": 0.5,
        "liquidity_score": 0.5, "invalidation_strength": 0.5,
        "contradiction_score": 0.3, "narrative_intensity": 0.5,
    }])
    assert any("chaos_attractor" in v for v in payload["vetoes"])
    assert payload["recommendation"] != "review_candidate"


def test_high_curl_field_blocks_promotion():
    cluster = [
        {"direction": 1, "intensity": 0.5, "contradiction_score": 0.7,
         "narrative_intensity": 0.5, "market_confirmation": 0.3},
        {"direction": -1, "intensity": 0.5, "contradiction_score": 0.7,
         "narrative_intensity": 0.5, "market_confirmation": 0.3},
        {"direction": 1, "intensity": 0.5, "contradiction_score": 0.7,
         "narrative_intensity": 0.5, "market_confirmation": 0.3},
        {"direction": -1, "intensity": 0.5, "contradiction_score": 0.7,
         "narrative_intensity": 0.5, "market_confirmation": 0.3},
    ]
    payload = build_signal_geometry_diagnostics(cluster)
    diag = payload["signal_geometry_diagnostics"]["field_diagnostics"]
    assert diag["curl_score"] >= 0.5
    assert any("curl" in v.lower() for v in payload["vetoes"])


# ---------------------------------------------------------------------------
# AI echo / stale duplicate lowers confidence.
# ---------------------------------------------------------------------------


def test_ai_echo_noise_lowers_confidence():
    noise = classify_noise_taxonomy({
        "source_family": "ai_report",
        "echo_risk_score": 0.7,
        "repetition_ratio": 0.6,
    })
    assert "ai_echo_noise" in noise["noise_classes_present"]
    assert noise["dominant_noise_class"] in NOISE_CLASSES


def test_duplicate_pre_veto_probably_seen_flagged():
    sig = {"event_id": "EVT1", "headline": "Tesla rallies",
            "source_name": "grok"}
    pre = classify_duplicate_stale_pre_veto(sig)
    fp = pre["signal_fingerprint"]
    pre2 = classify_duplicate_stale_pre_veto(sig, seen_fingerprints={fp})
    assert pre2["duplicate_stale_verdict"] == "probably_seen"
    assert pre2["verification_required"] is True
    assert pre2["canonical_source"] == "sqlite"


def test_orchestrator_probable_duplicate_adds_veto():
    sig = {"event_id": "EVT2", "headline": "AAPL earnings",
            "source_name": "grok",
            "narrative_intensity": 0.7, "freshness_score": 0.8,
            "source_reliability": 0.8, "market_confirmation": 0.6,
            "evidence_strength": 0.6, "liquidity_score": 0.6,
            "invalidation_strength": 0.6, "contradiction_score": 0.1,
            "chaos_score": 0.2}
    fp = classify_duplicate_stale_pre_veto(sig)["signal_fingerprint"]
    payload = build_signal_geometry_diagnostics([sig], seen_fingerprints={fp})
    assert "probable_duplicate" in payload["vetoes"]
    assert payload["recommendation"] != "review_candidate"


# ---------------------------------------------------------------------------
# India leverage rules: capped at 4x, NOT a default.
# ---------------------------------------------------------------------------


def test_india_leverage_within_ceiling_is_within_policy():
    policy = summarize_leverage_policy({"jurisdiction": "IN", "leverage": 3.5})
    assert policy["india_market"] is True
    assert policy["spot_only"] is False
    assert policy["leverage_ceiling"] == INDIA_LEVERAGE_CEILING
    assert policy["leverage_within_policy"] is True
    assert policy["leverage_veto"] is False


def test_india_leverage_above_ceiling_is_vetoed():
    policy = summarize_leverage_policy({"jurisdiction": "IN", "leverage": 5.0})
    assert policy["india_market"] is True
    assert policy["leverage_within_policy"] is False
    assert policy["leverage_veto"] is True
    assert policy["leverage_policy_reason"] == "leverage_exceeds_ceiling"


def test_india_leverage_is_not_default():
    # A bare signal without an explicit leverage value defaults to 1.0
    # — NOT to the 4x ceiling.
    policy = summarize_leverage_policy({"jurisdiction": "IN"})
    assert policy["leverage_requested"] == 1.0
    assert policy["leverage_capped"] == 1.0
    assert policy["leverage_is_default"] is False  # india != row-default flag
    # The is_default field signals whether the *spot-only default* applies;
    # for IN we mark it False so the operator must opt into leverage.


# ---------------------------------------------------------------------------
# Rest-of-world is spot-only.
# ---------------------------------------------------------------------------


def test_row_is_spot_only():
    policy = summarize_leverage_policy({"jurisdiction": "US", "leverage": 2.0})
    assert policy["india_market"] is False
    assert policy["spot_only"] is True
    assert policy["leverage_ceiling"] == ROW_LEVERAGE_CEILING
    assert policy["leverage_within_policy"] is False
    assert policy["leverage_veto"] is True
    assert policy["leverage_policy_reason"] in {"row_spot_only", "leverage_exceeds_ceiling"}


def test_row_default_leverage_one_is_within_policy():
    policy = summarize_leverage_policy({"jurisdiction": "US"})
    assert policy["leverage_requested"] == 1.0
    assert policy["leverage_within_policy"] is True
    assert policy["leverage_veto"] is False


@pytest.mark.parametrize("jurisdiction", ["US", "UK", "EU", "JP", "DE", "SG"])
def test_row_jurisdictions_are_spot_only(jurisdiction):
    policy = summarize_leverage_policy(
        {"jurisdiction": jurisdiction, "leverage": 2.5}
    )
    assert policy["spot_only"] is True
    assert policy["leverage_veto"] is True


# ---------------------------------------------------------------------------
# JSONL is not canonical.
# ---------------------------------------------------------------------------


def test_pre_veto_declares_sqlite_canonical():
    pre = classify_duplicate_stale_pre_veto({"event_id": "X"})
    assert pre["canonical_source"] == "sqlite"
    assert pre["verification_required"] is True


def test_orchestrator_marks_jsonl_as_audit_only():
    payload = build_signal_geometry_diagnostics([{"ticker": "X"}])
    assert payload["canonical_truth_source"] == "sqlite"
    assert payload["jsonl_role"] == "audit_fallback_only"


# ---------------------------------------------------------------------------
# Spatial index sanity.
# ---------------------------------------------------------------------------


def test_signal_cell_carries_index_fields():
    cell = build_signal_cell({
        "source_type": "news", "jurisdiction": "in",
        "geography": "IN", "sector": "Tech",
        "asset_tags": ["INFY"], "event_type": "earnings",
        "narrative_cluster": "india_tech_q1",
        "freshness_score": 0.9, "chaos_score": 0.2,
    })
    assert cell["jurisdiction"] == "IN"
    assert cell["geography"] == "IN"
    assert cell["sector"] == "tech"
    assert cell["asset_tags"] == ["INFY"]
    assert cell["freshness_state"] == "fresh"
    assert "in|in|tech" in cell["cell_key"].lower()


# ---------------------------------------------------------------------------
# Decision partition.
# ---------------------------------------------------------------------------


def test_decision_partition_macro():
    res = classify_decision_partition({"headline": "Fed cuts rates",
                                          "event_type": "macro"})
    assert res["decision_partition"] == "macro"


def test_decision_partition_ai_report():
    res = classify_decision_partition({"source_name": "grok",
                                          "event_type": "ai_report"})
    assert res["decision_partition"] == "ai_report"


def test_decision_partition_unclassified():
    res = classify_decision_partition({"headline": "random words"})
    assert res["decision_partition"] == "unclassified"


# ---------------------------------------------------------------------------
# Derivative engine.
# ---------------------------------------------------------------------------


def test_derivatives_history_completeness_scales():
    none_history = compute_signal_derivatives(0.5)
    assert none_history["history_completeness"] == pytest.approx(0.33, abs=1e-2)
    one_back = compute_signal_derivatives(0.5, score_t_minus_1=0.4)
    assert one_back["history_completeness"] == pytest.approx(0.66, abs=1e-2)
    assert one_back["momentum"] == pytest.approx(0.1, abs=1e-4)
    full = compute_signal_derivatives(0.5, score_t_minus_1=0.4, score_t_minus_2=0.2)
    assert full["history_completeness"] == 1.0
    assert full["curvature"] is not None


# ---------------------------------------------------------------------------
# Recursive Moltbook engine never auto-applies.
# ---------------------------------------------------------------------------


def test_moltbook_recursive_state_never_auto_applies():
    state = summarize_moltbook_recursive_state({
        "validated_events_count": 25,
        "moltbook_feedback_value": 0.6,
        "correction_applied": False,
    })
    assert state["not_auto_applied_without_human_review"] is True
    assert state["recursive_weight_adjustment_candidate"] > 0
    assert state["learning_radius"] > 0


def test_moltbook_recursive_state_small_sample_no_adjustment():
    state = summarize_moltbook_recursive_state({
        "validated_events_count": 2,
        "moltbook_feedback_value": 0.6,
    })
    assert state["recursive_weight_adjustment_candidate"] == 0.0


# ---------------------------------------------------------------------------
# Monte Carlo stub is honest about not being real.
# ---------------------------------------------------------------------------


def test_monte_carlo_stub_marks_itself_as_diagnostic():
    res = monte_carlo_survival_stub({
        "evidence_strength": 0.6, "chaos_score": 0.2, "leverage": 2.0,
    })
    assert res["is_real_monte_carlo"] is False
    assert res["method"] in {"deterministic_diagnostic_stub", "insufficient_data"}


# ---------------------------------------------------------------------------
# Phase alignment states.
# ---------------------------------------------------------------------------


def test_phase_aligned_confirming():
    res = compute_phase_alignment_state({
        "narrative_intensity": 0.7, "market_confirmation": 0.7,
    })
    assert res["phase_alignment_state"] == "aligned_confirming"


def test_phase_dangerous_desync():
    res = compute_phase_alignment_state({
        "narrative_intensity": 0.9, "market_confirmation": 0.05,
    })
    assert res["phase_alignment_state"] in {
        "dangerous_desync", "narrative_leads_capital",
    }


# ---------------------------------------------------------------------------
# Regime composition.
# ---------------------------------------------------------------------------


def test_regime_composition_durable_dominant():
    cluster = [
        {"source_reliability": 0.9, "freshness_score": 0.8,
         "contradiction_score": 0.1, "chaos_score": 0.1}
        for _ in range(5)
    ]
    regime = compute_regime_composition(cluster)
    assert regime["regime_state"] == "durable_dominant"
    assert regime["percent_durable"] >= 0.5


def test_regime_composition_stale_dominant():
    cluster = [
        {"freshness_score": 0.05, "freshness_state": "stale"}
        for _ in range(4)
    ]
    regime = compute_regime_composition(cluster)
    assert regime["regime_state"] == "stale_dominant"


# ---------------------------------------------------------------------------
# Hidden macro driver detector.
# ---------------------------------------------------------------------------


def test_hidden_macro_driver_detects_shared_sector():
    cluster = [
        {"ticker": "AAPL", "sector": "tech", "direction": 1,
         "jurisdiction": "US"},
        {"ticker": "MSFT", "sector": "tech", "direction": 1,
         "jurisdiction": "US"},
        {"ticker": "GOOGL", "sector": "tech", "direction": 1,
         "jurisdiction": "US"},
    ]
    driver = detect_hidden_macro_driver(cluster)
    assert driver["inferred_macro_driver"] is not None
    assert driver["driver_confidence"] > 0


# ---------------------------------------------------------------------------
# Thermodynamic exposure.
# ---------------------------------------------------------------------------


def test_thermodynamic_adiabatic_when_heat_no_confirmation():
    mode = classify_thermodynamic_exposure(
        {"portfolio_heat": 0.8, "exposure_volume": 0.2},
        [{"market_confirmation": 0.05, "chaos_score": 0.4}],
    )
    assert mode["thermo_mode"] == "adiabatic"
    assert mode["heat_dissipation_state"] == "trapped_dangerous"
