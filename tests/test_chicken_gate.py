"""Chicken Gate — freshness + asymmetry + node-evidence gate regression tests.

Covers the eight required behaviours:
1. High raw score with SPOILED freshness is BUY_BLOCKED.
2. "Due to bounce" thesis with NODE_CHANGE_EVIDENCE=NONE is BUY_BLOCKED.
3. IAP >= 8 hard-blocks even with a high raw score.
4. NET_EDGE <= 0 hard-blocks.
5. Thesis not touching the load-bearing node caps at BUY_LIMITED.
6. Good fresh thesis with node evidence and positive net edge is BUY_ALLOWED.
7. Final score never exceeds raw merit (demote-only invariant).
8. Missing optional evidence degrades to INSUFFICIENT_EVIDENCE / neutral
   demotion without crashing.

Plus: crowding_detector/LALO wiring into IAP, fail-closed enum handling,
value-extraction ledger arithmetic, and the advisory safety stamp.
"""
from __future__ import annotations

import copy

from scripts import chicken_gate as cg


def golden_thesis() -> dict:
    """A genuinely good, fresh, node-backed thesis (the BUY_ALLOWED path)."""
    return copy.deepcopy(cg.DEMO_THESIS)


# ---------------------------------------------------------------------------
# 1. Hard flags override high raw scores
# ---------------------------------------------------------------------------


def test_high_raw_score_with_spoiled_freshness_is_blocked():
    thesis = golden_thesis()
    thesis["asset_lineage"] = "NARRATIVE"  # 7-day half-life
    thesis["thesis_age_days"] = 60.0       # ~8.6 half-lives -> spoiled
    result = cg.evaluate_chicken_gate(thesis)
    assert result["RAW_TRADE_SCORE"] >= 9.0  # raw merit is high...
    assert result["FRESHNESS_STATE"] == "SPOILED"
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_BLOCKED  # ...and it dies
    assert "FRESHNESS_SPOILED" in result["HARD_FLAG_TRIGGERED"]
    assert result["BUY_BLOCKED_REASON"]


def test_due_to_bounce_without_node_change_evidence_is_blocked():
    thesis = golden_thesis()
    thesis["thesis_text"] = "It has fallen too much and is due to bounce."
    thesis["node_change_evidence"] = "NONE"
    result = cg.evaluate_chicken_gate(thesis)
    assert result["GAMBLERS_FALLACY_FLAG"] is True
    assert result["NODE_CHANGE_EVIDENCE"] == "NONE"
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_BLOCKED
    assert "GAMBLERS_FALLACY_NO_NODE_CHANGE_EVIDENCE" in result["HARD_FLAG_TRIGGERED"]


def test_reversal_thesis_with_causal_node_change_is_not_fallacy_blocked():
    thesis = golden_thesis()
    thesis["thesis_text"] = "Oversold on forced fund redemptions now completed."
    thesis["node_change_evidence"] = "FLOW_CHANGE"
    result = cg.evaluate_chicken_gate(thesis)
    assert result["GAMBLERS_FALLACY_FLAG"] is True  # language still reversal-shaped
    assert "GAMBLERS_FALLACY" not in result["HARD_FLAG_TRIGGERED"]
    assert result["FINAL_ACTION_GATE"] != cg.GATE_BUY_BLOCKED


def test_invalid_node_change_evidence_fails_closed_to_none():
    thesis = golden_thesis()
    thesis["thesis_text"] = "This has to recover soon."
    thesis["node_change_evidence"] = "VIBES"  # not in the enum
    result = cg.evaluate_chicken_gate(thesis)
    assert result["NODE_CHANGE_EVIDENCE"] == "NONE"
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_BLOCKED


def test_iap_gte_8_blocks_even_with_high_raw_score():
    thesis = golden_thesis()
    thesis["information_access_premium"] = 8.5
    result = cg.evaluate_chicken_gate(thesis)
    assert result["RAW_TRADE_SCORE"] >= 9.0
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_BLOCKED
    assert "INFORMATION_ACCESS_PREMIUM_GTE_8" in result["HARD_FLAG_TRIGGERED"]


def test_non_positive_net_edge_blocks():
    thesis = golden_thesis()
    thesis["model_probability"] = 0.50
    thesis["market_implied_probability"] = 0.50
    thesis["friction_leakage_estimate"] = 0.01
    result = cg.evaluate_chicken_gate(thesis)
    assert result["NET_EDGE"] <= 0.0
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_BLOCKED
    assert "NET_EDGE_NON_POSITIVE" in result["HARD_FLAG_TRIGGERED"]


def test_spoilage_risk_true_blocks():
    thesis = golden_thesis()
    thesis["spoilage_risk"] = True
    result = cg.evaluate_chicken_gate(thesis)
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_BLOCKED
    assert "SPOILAGE_RISK" in result["HARD_FLAG_TRIGGERED"]


def test_low_process_integrity_blocks():
    thesis = golden_thesis()
    thesis["process_integrity_score"] = 2.0
    result = cg.evaluate_chicken_gate(thesis)
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_BLOCKED
    assert "PROCESS_INTEGRITY_BELOW_3" in result["HARD_FLAG_TRIGGERED"]


def test_fake_label_high_premium_low_authenticity_blocks():
    thesis = golden_thesis()
    thesis["label_authenticity_score"] = 0.15
    thesis["label_premium"] = 8.0
    result = cg.evaluate_chicken_gate(thesis)
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_BLOCKED
    assert "FAKE_LABEL" in result["HARD_FLAG_TRIGGERED"]


# ---------------------------------------------------------------------------
# 2. Load-bearing node cap
# ---------------------------------------------------------------------------


def test_thesis_not_touching_node_caps_at_buy_limited():
    thesis = golden_thesis()
    thesis["thesis_touches_node"] = False
    result = cg.evaluate_chicken_gate(thesis)
    # Score alone would have cleared BUY_ALLOWED (golden path >= 8.0)...
    assert result["OPERATOR_FIT_ADJ_SCORE"] >= 8.0
    # ...but the node cap demotes it.
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_LIMITED
    assert result["GATE_CAPS_APPLIED"] == [
        "THESIS_DOES_NOT_PROVABLY_TOUCH_LOAD_BEARING_NODE"
    ]


def test_unproven_node_touch_fails_closed_to_cap():
    thesis = golden_thesis()
    del thesis["thesis_touches_node"]
    result = cg.evaluate_chicken_gate(thesis)
    assert result["THESIS_TOUCHES_NODE"] is None
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_LIMITED


# ---------------------------------------------------------------------------
# 3. The golden path can pass
# ---------------------------------------------------------------------------


def test_good_fresh_node_backed_positive_edge_thesis_is_buy_allowed():
    result = cg.evaluate_chicken_gate(golden_thesis())
    assert result["FRESHNESS_STATE"] == "FRESH"
    assert result["NET_EDGE"] > 0
    assert result["HARD_FLAG_TRIGGERED"] == "NONE"
    assert result["OPERATOR_FIT_ADJ_SCORE"] >= 8.0
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_ALLOWED
    assert result["BUY_ALLOWED_REASON"]


# ---------------------------------------------------------------------------
# 4. Demote-only invariant: final <= raw, always
# ---------------------------------------------------------------------------


def test_final_never_exceeds_raw_merit_across_thesis_spectrum():
    variants = [
        golden_thesis(),
        {},  # nothing at all
        {"operator_fit_score": 10.0, "information_access_premium": 0.0,
         "channel_premium_score": 0.0, "thesis_age_days": 0.0,
         "frozen_long_term": True},  # every multiplier at its maximum
        {"house_edge_score": 10.0, "input_quality_score": 10.0,
         "process_integrity_score": 10.0, "load_bearing_node_score": 10.0,
         "label_authenticity_score": 1.0, "residual_bone_value_score": 1.0,
         "operator_fit_score": 10.0, "thesis_age_days": 0.0},
        {"thesis_age_days": 500.0, "asset_lineage": "NARRATIVE"},
        {"information_access_premium": 9.9, "operator_fit_score": 0.0},
    ]
    for thesis in variants:
        result = cg.evaluate_chicken_gate(thesis)
        assert result["OPERATOR_FIT_ADJ_SCORE"] <= result["RAW_TRADE_SCORE"] + 1e-9
        assert result["ASYMMETRY_ADJ_SCORE"] <= result["FRESHNESS_ADJ_SCORE"] + 1e-9
        assert result["FRESHNESS_ADJ_SCORE"] <= result["RAW_TRADE_SCORE"] + 1e-9
        assert result["invariant_final_leq_raw"] is True


def test_frozen_long_term_confirms_but_never_inflates():
    thesis = golden_thesis()
    thesis["frozen_long_term"] = True
    result = cg.evaluate_chicken_gate(thesis)
    assert result["FRESHNESS_STATE"] == "FROZEN"
    assert result["FRESHNESS_ADJ_SCORE"] == result["RAW_TRADE_SCORE"]  # x1.0 exactly


# ---------------------------------------------------------------------------
# 5. Missing evidence: degrade, never crash, never reward
# ---------------------------------------------------------------------------


def test_empty_thesis_degrades_to_insufficient_evidence_without_crash():
    result = cg.evaluate_chicken_gate({})
    assert result["FRESHNESS_STATE"] == "INSUFFICIENT_EVIDENCE"
    assert result["LOAD_BEARING_NODE"] == "INSUFFICIENT_EVIDENCE"
    assert result["NET_EDGE"] is None  # not computable, no false block
    assert result["evidence_notes"]  # every gap is named
    # Neutral demotion: unknown age is mildly stale, never fresh.
    assert result["FRESHNESS_ADJ_SCORE"] < result["RAW_TRADE_SCORE"]
    # Unknown node touch fails closed to the cap.
    assert result["FINAL_ACTION_GATE"] in (
        cg.GATE_BUY_LIMITED, cg.GATE_WATCHLIST, cg.GATE_BUY_BLOCKED
    )


def test_garbage_inputs_do_not_crash():
    result = cg.evaluate_chicken_gate({
        "house_edge_score": "banana",
        "thesis_first_signal_date": "not-a-date",
        "information_access_premium": float("nan"),
        "thesis_touches_node": "yes",  # not a bool -> unproven
        "model_probability": None,
    })
    assert result["FINAL_ACTION_GATE"] in (
        cg.GATE_BUY_ALLOWED, cg.GATE_BUY_LIMITED, cg.GATE_WATCHLIST, cg.GATE_BUY_BLOCKED
    )
    assert result["THESIS_TOUCHES_NODE"] is None


# ---------------------------------------------------------------------------
# 6. Reuse wiring: crowding_detector + late_adoption_lockout feed IAP
# ---------------------------------------------------------------------------


def test_crowding_trap_derives_iap_hard_block():
    thesis = golden_thesis()
    del thesis["information_access_premium"]
    thesis["crowding"] = {
        "light_score": 0.9,
        "temporal_position": 0.85,
        "crowding_state": "CROWDED",
        "cross_source_confirmation_score": 0.9,
        "novelty_score": 0.1,
    }
    result = cg.evaluate_chicken_gate(thesis)
    assert result["INFORMATION_ACCESS_PREMIUM"] >= 8.0
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_BLOCKED
    assert "INFORMATION_ACCESS_PREMIUM_GTE_8" in result["HARD_FLAG_TRIGGERED"]


def test_lalo_locked_out_derives_iap_hard_block():
    thesis = golden_thesis()
    del thesis["information_access_premium"]
    thesis["lalo_score"] = 0.89  # CVX Day 80: peak parrot territory
    result = cg.evaluate_chicken_gate(thesis)
    assert result["INFORMATION_ACCESS_PREMIUM"] >= 8.0
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_BLOCKED


def test_multiple_iap_sources_take_the_worst():
    thesis = golden_thesis()
    thesis["information_access_premium"] = 1.0
    thesis["lalo_score"] = 0.6  # worse than the explicit 1.0
    result = cg.evaluate_chicken_gate(thesis)
    assert result["INFORMATION_ACCESS_PREMIUM"] == 6.0


# ---------------------------------------------------------------------------
# 7. Value-extraction ledger: raw - final decomposes exactly, extractors named
# ---------------------------------------------------------------------------


def test_value_extraction_ledger_sums_to_raw_minus_final():
    thesis = golden_thesis()
    thesis["thesis_age_days"] = 30.0
    thesis["information_access_premium"] = 5.0
    thesis["channel_premium_score"] = 7.0
    thesis["operator_fit_score"] = 4.0
    result = cg.evaluate_chicken_gate(thesis)
    eaten = sum(row["points_eaten"] for row in result["value_extraction_ledger"])
    expected = result["RAW_TRADE_SCORE"] - result["OPERATOR_FIT_ADJ_SCORE"]
    assert abs(eaten - expected) < 0.005  # rounding tolerance
    extractors = {row["extractor"] for row in result["value_extraction_ledger"]}
    assert extractors == {
        "TIME_AND_EARLIER_HOLDERS",
        "EARLIER_INFORMED_PARTICIPANTS",
        "PACKAGING_CHANNEL_MARKUP",
        "PORTFOLIO_OVERLAP",
    }


# ---------------------------------------------------------------------------
# 8. Advisory contract + trade card
# ---------------------------------------------------------------------------


def test_safety_stamp_is_canonical_and_locked():
    result = cg.evaluate_chicken_gate(golden_thesis())
    stamp = result["safety"]
    assert stamp["advisory_status"] == "ADVISORY_ONLY"
    assert stamp["execution_gate"] == "LOCKED"
    assert stamp["can_execute"] is False
    assert stamp["broker_api_called"] is False
    assert result["human"]["human_final_decision_required"] is True
    assert result["SCORING_PROFILE_VERSION"] == cg.SCORING_PROFILE_VERSION


def test_trade_card_renders_decision_and_ledger():
    result = cg.evaluate_chicken_gate(golden_thesis())
    card = cg.render_trade_card(result)
    assert "CHICKEN GATE TRADE CARD" in card
    assert "who ate the value before it reached you" in card
    assert "FINAL ACTION: BUY_ALLOWED" in card
    assert "ADVISORY_ONLY" in card


def test_cli_demo_smoke(capsys):
    assert cg.main(["--demo"]) == 0
    out = capsys.readouterr().out
    assert "FINAL ACTION:" in out
