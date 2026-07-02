"""Chicken Gate v1.1 — hardened gate regression tests.

Covers hard blocks, cap rules, negation-aware gambler guard, IAP evidence
confidence, raw-input validation haircuts, holdings-based operator fit,
catalyst expiry, ledger conservation, the demote-only invariant chain
(FINAL <= RAW_VALIDATED <= RAW), and the advisory safety stamp.
"""
from __future__ import annotations

import copy
import pathlib
from datetime import datetime, timedelta, timezone

from scripts import chicken_gate as cg

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_NOW = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)


def golden_thesis() -> dict:
    """Fully-evidenced, fresh, early, node-backed thesis (BUY_ALLOWED path)."""
    return copy.deepcopy(cg.DEMO_THESIS)


# ---------------------------------------------------------------------------
# Hard flags override high (validated) raw scores
# ---------------------------------------------------------------------------


def test_high_raw_score_with_spoiled_freshness_is_blocked():
    thesis = golden_thesis()
    thesis["asset_lineage"] = "NARRATIVE"  # 7-day half-life
    thesis["thesis_age_days"] = 60.0
    result = cg.evaluate_chicken_gate(thesis)
    assert result["RAW_VALIDATED_SCORE"] >= 9.0
    assert result["FRESHNESS_STATE"] == "SPOILED"
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_BLOCKED
    assert "FRESHNESS_SPOILED" in result["HARD_FLAG_TRIGGERED"]


def test_hard_blocks_override_high_validated_raw():
    thesis = golden_thesis()
    thesis["spoilage_risk"] = True
    result = cg.evaluate_chicken_gate(thesis)
    assert result["RAW_VALIDATED_SCORE"] >= 9.0
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_BLOCKED
    assert "SPOILAGE_RISK" in result["HARD_FLAG_TRIGGERED"]


def test_low_process_integrity_blocks():
    thesis = golden_thesis()
    thesis["process_integrity_score"] = 2.0
    result = cg.evaluate_chicken_gate(thesis)
    assert "PROCESS_INTEGRITY_BELOW_3" in result["HARD_FLAG_TRIGGERED"]
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_BLOCKED


def test_fake_label_high_premium_low_authenticity_blocks():
    thesis = golden_thesis()
    thesis["label_authenticity_score"] = 0.15
    thesis["label_premium"] = 8.0
    result = cg.evaluate_chicken_gate(thesis)
    assert "FAKE_LABEL" in result["HARD_FLAG_TRIGGERED"]
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_BLOCKED


def test_net_edge_non_positive_blocks():
    thesis = golden_thesis()
    thesis["model_probability"] = 0.50
    thesis["market_implied_probability"] = 0.50
    thesis["friction_leakage_estimate"] = 0.01
    result = cg.evaluate_chicken_gate(thesis)
    assert result["NET_EDGE"] <= 0.0
    assert "NET_EDGE_NON_POSITIVE" in result["HARD_FLAG_TRIGGERED"]
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_BLOCKED


# ---------------------------------------------------------------------------
# Gambler's-fallacy guard: negation-aware
# ---------------------------------------------------------------------------


def test_gambler_negation_not_flagged():
    for text in (
        "This is not an oversold bounce thesis.",
        "Avoiding gambler's fallacy: price has fallen but I need node change.",
        "Not buying just because it has fallen too much.",
        "The thesis is not that it is due to bounce.",
        "We reject the oversold argument; the driver is a contract award.",
    ):
        thesis = golden_thesis()
        thesis["thesis_text"] = text
        thesis["node_change_evidence"] = "NONE"
        result = cg.evaluate_chicken_gate(thesis)
        assert result["GAMBLERS_FALLACY_FLAG"] is False, text
        assert "GAMBLERS_FALLACY" not in result["HARD_FLAG_TRIGGERED"], text


def test_gambler_plain_due_to_bounce_blocks():
    for text in (
        "It has fallen too much and should recover.",
        "This is oversold, due to bounce.",
        "It cannot go lower from here.",
        "After three losses this one should win.",
    ):
        thesis = golden_thesis()
        thesis["thesis_text"] = text
        thesis["node_change_evidence"] = "NONE"
        result = cg.evaluate_chicken_gate(thesis)
        assert result["GAMBLERS_FALLACY_FLAG"] is True, text
        assert "GAMBLERS_FALLACY_NO_NODE_CHANGE_EVIDENCE" in result["HARD_FLAG_TRIGGERED"]
        assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_BLOCKED, text


def test_invalid_node_change_evidence_fails_closed():
    thesis = golden_thesis()
    thesis["thesis_text"] = "This has to recover soon."
    thesis["node_change_evidence"] = "VIBES"
    result = cg.evaluate_chicken_gate(thesis)
    assert result["NODE_CHANGE_EVIDENCE"] == "NONE"
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_BLOCKED


def test_reversal_with_valid_node_change_warns_not_blocks():
    thesis = golden_thesis()
    thesis["thesis_text"] = "Oversold on forced fund redemptions now completed."
    thesis["node_change_evidence"] = "FLOW_CHANGE"
    result = cg.evaluate_chicken_gate(thesis)
    assert result["GAMBLERS_FALLACY_FLAG"] is True
    assert "REVERSAL_REQUIRES_NODE_CONFIRMATION" in result["WARNINGS"]
    assert "GAMBLERS_FALLACY" not in result["HARD_FLAG_TRIGGERED"]
    assert result["FINAL_ACTION_GATE"] != cg.GATE_BUY_BLOCKED


def test_negated_phrases_reported_for_audit():
    detection = cg.detect_reversal_language(
        "This is not an oversold bounce thesis."
    )
    assert detection["reversal_detected"] is False
    assert "oversold" in detection["negated_phrases"]


# ---------------------------------------------------------------------------
# IAP: silence is suspicious, not safe
# ---------------------------------------------------------------------------


def test_iap_missing_evidence_applies_conservative_penalty():
    thesis = golden_thesis()
    del thesis["information_access_premium"]
    del thesis["publicity_saturation_score"]
    del thesis["price_move_since_signal_pct"]
    result = cg.evaluate_chicken_gate(thesis)
    # Only the channel slot remains -> confidence 0.25 -> floor 5 + 3*0.75.
    assert result["IAP_CONFIDENCE"] == 0.25
    assert result["IAP_EFFECTIVE"] >= 7.0
    assert "INSUFFICIENT_EVIDENCE_CROWDING" in result["EVIDENCE_NOTES"]
    assert "INSUFFICIENT_EVIDENCE_LATE_ADOPTION" in result["EVIDENCE_NOTES"]
    assert (
        "INSUFFICIENT_EVIDENCE_PRICE_MOVE_SINCE_SIGNAL" in result["EVIDENCE_NOTES"]
    )
    assert result["FINAL_ACTION_GATE"] != cg.GATE_BUY_ALLOWED


def test_iap_total_silence_hard_blocks():
    result = cg.evaluate_chicken_gate({})
    assert result["IAP_CONFIDENCE"] == 0.0
    assert result["IAP_EFFECTIVE"] >= 8.0
    assert "INFORMATION_ACCESS_PREMIUM_GTE_8" in result["HARD_FLAG_TRIGGERED"]
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_BLOCKED


def test_iap_full_evidence_low_score_does_not_block():
    result = cg.evaluate_chicken_gate(golden_thesis())
    assert result["IAP_CONFIDENCE"] == 1.0
    assert result["IAP_EFFECTIVE"] == result["INFORMATION_ACCESS_PREMIUM"]
    assert result["IAP_EFFECTIVE"] < 2.0
    assert "INFORMATION_ACCESS_PREMIUM_GTE_8" not in result["HARD_FLAG_TRIGGERED"]


def test_iap_high_score_hard_blocks():
    thesis = golden_thesis()
    thesis["information_access_premium"] = 8.5
    result = cg.evaluate_chicken_gate(thesis)
    assert "INFORMATION_ACCESS_PREMIUM_GTE_8" in result["HARD_FLAG_TRIGGERED"]
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_BLOCKED


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
    assert result["IAP_EFFECTIVE"] >= 8.0
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_BLOCKED


def test_lalo_locked_out_derives_iap_hard_block():
    thesis = golden_thesis()
    del thesis["information_access_premium"]
    thesis["lalo_score"] = 0.89  # CVX Day 80: peak parrot territory
    result = cg.evaluate_chicken_gate(thesis)
    assert result["IAP_EFFECTIVE"] >= 8.0
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_BLOCKED


def test_multiple_iap_sources_take_the_worst():
    thesis = golden_thesis()
    thesis["lalo_score"] = 0.6  # worse than the explicit 1.0
    result = cg.evaluate_chicken_gate(thesis)
    assert result["INFORMATION_ACCESS_PREMIUM"] == 6.0
    assert result["IAP_EFFECTIVE"] == 6.0  # full evidence -> no floor


# ---------------------------------------------------------------------------
# Raw-input validation: confidence haircuts
# ---------------------------------------------------------------------------


def test_raw_score_confidence_haircut():
    thesis = golden_thesis()
    for key in list(thesis):
        if key.endswith("_confidence"):
            thesis[key] = 0.0
    result = cg.evaluate_chicken_gate(thesis)
    # C_i = 0 -> every component halved -> validated = raw / 2.
    assert abs(result["RAW_VALIDATED_SCORE"] - result["RAW_TRADE_SCORE"] / 2) < 0.01
    assert result["RAW_INFLATION_LEAKAGE"] > 4.0


def test_raw_validated_never_exceeds_raw():
    variants = [
        golden_thesis(),
        {},
        {"house_edge_score": 10.0},  # score without confidence -> 0.5 default
        {"house_edge_score": 10.0, "house_edge_confidence": 1.0},
    ]
    for thesis in variants:
        result = cg.evaluate_chicken_gate(thesis)
        assert result["RAW_VALIDATED_SCORE"] <= result["RAW_TRADE_SCORE"] + 1e-9


def test_missing_raw_evidence_cannot_buy_allowed():
    thesis = golden_thesis()
    for key in (
        "house_edge_score", "house_edge_confidence",
        "input_quality_score", "input_quality_confidence",
        "process_integrity_score", "process_integrity_confidence",
        "load_bearing_node_score", "load_bearing_node_evidence_confidence",
        "label_authenticity_score", "label_authenticity_confidence",
        "residual_bone_value_score", "residual_bone_value_confidence",
    ):
        thesis.pop(key, None)
    result = cg.evaluate_chicken_gate(thesis)
    # Neutral scores at zero confidence: merit collapses; gate cannot open.
    assert result["RAW_VALIDATED_SCORE"] < 3.0
    assert result["FINAL_ACTION_GATE"] != cg.GATE_BUY_ALLOWED


def test_missing_confidence_defaults_to_half_trust():
    thesis = golden_thesis()
    del thesis["house_edge_confidence"]
    result = cg.evaluate_chicken_gate(thesis)
    assert any("house_edge_confidence" in n for n in result["EVIDENCE_NOTES"])
    # 9.5 * (0.5 + 0.5*0.5) = 7.125 vs 9.5 -> leakage 0.25 * 9.5 * 0.25 weight
    assert result["RAW_INFLATION_LEAKAGE"] > 0.5


# ---------------------------------------------------------------------------
# Operator fit: holdings-computed, degradable
# ---------------------------------------------------------------------------


def test_operator_fit_missing_holdings_degrades_not_crashes():
    thesis = golden_thesis()
    del thesis["operator_fit_score"]
    result = cg.evaluate_chicken_gate(thesis)
    assert result["OPERATOR_FIT_SCORE"] == 5.0
    assert result["OPERATOR_FIT_CONFIDENCE"] == 0.90
    assert "INSUFFICIENT_EVIDENCE_HOLDINGS" in result["EVIDENCE_NOTES"]
    assert result["FINAL_ACTION_GATE"] != cg.GATE_BUY_ALLOWED


def test_operator_fit_high_overlap_caps_buy_limited():
    thesis = golden_thesis()
    del thesis["operator_fit_score"]
    thesis["ticker"] = "XOM"
    thesis["sector"] = "ENERGY"
    holdings = [
        {"ticker": "NYSE:XOM", "sector": "ENERGY", "quantity": 1, "entry_price": 100},
        {"ticker": "NYSE:CVX", "sector": "ENERGY", "quantity": 1, "entry_price": 100},
    ]
    result = cg.evaluate_chicken_gate(thesis, holdings=holdings)
    assert result["OPERATOR_FIT_SCORE"] < 4.0
    assert result["OPERATOR_FIT_PENALTIES"]["same_ticker_penalty"] == 6.0
    assert any(
        c["rule"] == "OPERATOR_FIT_BELOW_4" for c in result["CAP_RULES_TRIGGERED"]
    )
    assert cg._GATE_RANK[result["FINAL_ACTION_GATE"]] <= cg._GATE_RANK[cg.GATE_BUY_LIMITED]


def test_operator_fit_low_overlap_improves_fit():
    thesis = golden_thesis()
    del thesis["operator_fit_score"]
    thesis["ticker"] = "NEWCO"
    thesis["sector"] = "HEALTHCARE"
    holdings = [
        {"ticker": "ANET", "sector": "TECH", "quantity": 1, "entry_price": 100},
        {"ticker": "XOM", "sector": "ENERGY", "quantity": 1, "entry_price": 100},
        {"ticker": "RHM", "sector": "DEFENCE_SECTOR", "quantity": 1, "entry_price": 100},
        {"ticker": "TLT", "sector": "BONDS", "quantity": 1, "entry_price": 100},
    ]
    result = cg.evaluate_chicken_gate(thesis, holdings=holdings)
    assert result["OPERATOR_FIT_SCORE"] > 8.0
    assert result["OPERATOR_FIT_SOURCE"].startswith("holdings")


def test_operator_fit_reads_canonical_holdings_file_when_opted_in():
    holdings = cg.load_verified_holdings()
    if holdings is None:  # file absent in this checkout: loader degrades to None
        assert cg.load_verified_holdings("Z:/definitely/absent.json") is None
        return
    assert isinstance(holdings, list) and holdings
    computed = cg.compute_operator_fit_from_holdings(
        holdings, candidate_ticker="NOVEL_TICKER"
    )
    assert 0.0 <= computed["OPERATOR_FIT_SCORE"] <= 10.0


# ---------------------------------------------------------------------------
# Freshness v1.1: half-life math, FROZEN, catalyst expiry, date haircut
# ---------------------------------------------------------------------------


def test_half_life_one_period_halves_freshness():
    thesis = golden_thesis()
    thesis["thesis_age_days"] = 45.0  # DEFENCE half-life = 45d
    result = cg.evaluate_chicken_gate(thesis)
    assert abs(result["FRESHNESS_MULTIPLIER"] - 0.5) < 0.01
    assert result["FRESHNESS_STATE"] == "AGING"


def test_half_life_two_periods_spoils():
    thesis = golden_thesis()
    thesis["thesis_age_days"] = 90.0  # two half-lives -> 0.25 -> SPOILED
    result = cg.evaluate_chicken_gate(thesis)
    assert abs(result["FRESHNESS_MULTIPLIER"] - 0.25) < 0.01
    assert result["FRESHNESS_STATE"] == "SPOILED"
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_BLOCKED


def test_frozen_never_inflates():
    thesis = golden_thesis()
    thesis["frozen_long_term"] = True
    thesis["frozen_justification"] = "5-year structural compounding holding"
    result = cg.evaluate_chicken_gate(thesis)
    assert result["FRESHNESS_STATE"] == "FROZEN"
    assert result["FRESHNESS_MULTIPLIER"] == 1.0
    assert result["FRESHNESS_ADJ_SCORE"] == result["RAW_VALIDATED_SCORE"]
    assert result["FINAL_SCORE"] <= result["RAW_VALIDATED_SCORE"] + 1e-9


def test_frozen_without_justification_is_ignored():
    thesis = golden_thesis()
    thesis["frozen_long_term"] = True  # no justification supplied
    result = cg.evaluate_chicken_gate(thesis)
    assert result["FRESHNESS_STATE"] != "FROZEN"
    assert any("frozen_long_term ignored" in n for n in result["EVIDENCE_NOTES"])


def test_missing_first_signal_date_haircut():
    thesis = golden_thesis()
    del thesis["thesis_age_days"]
    result = cg.evaluate_chicken_gate(thesis)
    assert result["FRESHNESS_STATE"] == "INSUFFICIENT_EVIDENCE"
    assert result["FRESHNESS_MULTIPLIER"] == 0.85
    assert "INSUFFICIENT_EVIDENCE_FIRST_SIGNAL_DATE" in result["EVIDENCE_NOTES"]
    assert result["FINAL_ACTION_GATE"] != cg.GATE_BUY_ALLOWED


def test_past_catalyst_spoils_or_blocks():
    thesis = golden_thesis()
    thesis["catalyst_date"] = (_NOW - timedelta(days=10)).isoformat()
    result = cg.evaluate_chicken_gate(thesis, now=_NOW)
    assert result["FRESHNESS_STATE"] == "SPOILED"
    assert "FRESHNESS_SPOILED" in result["HARD_FLAG_TRIGGERED"]
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_BLOCKED


def test_past_catalyst_within_grace_degrades_to_near_expiry():
    thesis = golden_thesis()
    thesis["catalyst_date"] = (_NOW - timedelta(days=2)).isoformat()
    result = cg.evaluate_chicken_gate(thesis, now=_NOW)
    assert result["FRESHNESS_STATE"] == "NEAR_EXPIRY"
    assert result["FRESHNESS_MULTIPLIER"] <= 0.45
    assert "FRESHNESS_SPOILED" not in result["HARD_FLAG_TRIGGERED"]


def test_known_catalyst_outcome_does_not_expire():
    thesis = golden_thesis()
    thesis["catalyst_date"] = (_NOW - timedelta(days=10)).isoformat()
    thesis["catalyst_outcome_known"] = True
    result = cg.evaluate_chicken_gate(thesis, now=_NOW)
    assert result["FRESHNESS_STATE"] == "FRESH"


def test_catalyst_text_durability_derives_half_life():
    snack = cg.derive_half_life_from_catalyst_text("meme squeeze rally hype")
    assert snack["half_life_class"] == "SNACK"
    assert snack["half_life_days"] == 3.0
    durable = cg.derive_half_life_from_catalyst_text(
        "framework contract award with guidance raise and backlog growth"
    )
    assert durable["half_life_class"] == "DURABLE"
    assert cg.derive_half_life_from_catalyst_text("") is None


# ---------------------------------------------------------------------------
# Node + channel + net-edge caps
# ---------------------------------------------------------------------------


def test_thesis_not_touching_node_caps_at_buy_limited():
    thesis = golden_thesis()
    thesis["thesis_touches_node"] = False
    result = cg.evaluate_chicken_gate(thesis)
    assert result["FINAL_SCORE"] >= 8.0  # score alone would clear ALLOWED
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_LIMITED


def test_missing_node_caps_and_notes():
    thesis = golden_thesis()
    del thesis["load_bearing_node"]
    result = cg.evaluate_chicken_gate(thesis)
    assert result["LOAD_BEARING_NODE"] == "INSUFFICIENT_EVIDENCE"
    assert "INSUFFICIENT_EVIDENCE_LOAD_BEARING_NODE" in result["EVIDENCE_NOTES"]
    assert cg._GATE_RANK[result["FINAL_ACTION_GATE"]] <= cg._GATE_RANK[cg.GATE_BUY_LIMITED]


def test_channel_premium_high_unverified_caps_watchlist():
    thesis = golden_thesis()
    thesis["channel_premium_score"] = 9.0
    thesis["raw_evidence_independently_verified"] = False
    result = cg.evaluate_chicken_gate(thesis)
    assert any(
        c["rule"] == "CHANNEL_PREMIUM_GTE_8_UNVERIFIED"
        for c in result["CAP_RULES_TRIGGERED"]
    )
    assert cg._GATE_RANK[result["FINAL_ACTION_GATE"]] <= cg._GATE_RANK[cg.GATE_WATCHLIST]


def test_net_edge_insufficient_evidence_caps_buy_limited():
    thesis = golden_thesis()
    del thesis["model_probability"]
    result = cg.evaluate_chicken_gate(thesis)
    assert result["NET_EDGE"] is None
    assert result["NET_EDGE_STATUS"] == "INSUFFICIENT_EVIDENCE"
    assert any(
        c["rule"] == "NET_EDGE_INSUFFICIENT_EVIDENCE"
        for c in result["CAP_RULES_TRIGGERED"]
    )
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_LIMITED


# ---------------------------------------------------------------------------
# The golden path can (barely) pass
# ---------------------------------------------------------------------------


def test_good_fresh_node_backed_positive_edge_thesis_is_buy_allowed():
    result = cg.evaluate_chicken_gate(golden_thesis())
    assert result["FRESHNESS_STATE"] == "FRESH"
    assert result["NET_EDGE"] > 0
    assert result["HARD_FLAG_TRIGGERED"] == "NONE"
    assert result["RAW_INFLATION_LEAKAGE"] == 0.0
    assert result["FINAL_SCORE"] >= 8.0
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_ALLOWED


# ---------------------------------------------------------------------------
# Demote-only invariant chain
# ---------------------------------------------------------------------------


def test_final_score_never_exceeds_raw_validated():
    variants = [
        golden_thesis(),
        {},
        {"operator_fit_score": 10.0, "information_access_premium": 0.0,
         "channel_premium_score": 0.0, "thesis_age_days": 0.0,
         "publicity_saturation_score": 0.0, "price_move_since_signal_pct": 0.0,
         "frozen_long_term": True, "frozen_justification": "structural"},
        {"house_edge_score": 10.0, "house_edge_confidence": 1.0,
         "operator_fit_score": 10.0, "thesis_age_days": 0.0},
        {"thesis_age_days": 500.0, "asset_lineage": "NARRATIVE"},
        {"information_access_premium": 9.9, "operator_fit_score": 0.0},
    ]
    for thesis in variants:
        result = cg.evaluate_chicken_gate(thesis)
        assert result["FINAL_SCORE"] <= result["RAW_VALIDATED_SCORE"] + 1e-9
        assert result["RAW_VALIDATED_SCORE"] <= result["RAW_TRADE_SCORE"] + 1e-9
        assert result["invariant_final_leq_raw"] is True


def test_all_multipliers_within_unit_interval():
    result = cg.evaluate_chicken_gate(golden_thesis())
    assert 0.0 <= result["FRESHNESS_MULTIPLIER"] <= 1.0
    assert 0.0 <= result["CHANNEL_MULTIPLIER"] <= 1.0
    assert 0.0 <= result["IAP_CONFIDENCE"] <= 1.0
    assert 0.0 <= result["OPERATOR_FIT_CONFIDENCE"] <= 1.0


# ---------------------------------------------------------------------------
# Missing evidence: degrade, never crash, never reward
# ---------------------------------------------------------------------------


def test_empty_thesis_degrades_and_blocks_on_silence():
    result = cg.evaluate_chicken_gate({})
    assert result["FRESHNESS_STATE"] == "INSUFFICIENT_EVIDENCE"
    assert result["LOAD_BEARING_NODE"] == "INSUFFICIENT_EVIDENCE"
    assert result["NET_EDGE"] is None
    assert result["EVIDENCE_NOTES"]
    assert result["FRESHNESS_ADJ_SCORE"] < result["RAW_VALIDATED_SCORE"]
    # v1.1 doctrine: total IAP silence is suspicious -> hard block.
    assert result["FINAL_ACTION_GATE"] == cg.GATE_BUY_BLOCKED


def test_garbage_inputs_do_not_crash():
    result = cg.evaluate_chicken_gate({
        "house_edge_score": "banana",
        "house_edge_confidence": "high",
        "thesis_first_signal_date": "not-a-date",
        "information_access_premium": float("nan"),
        "thesis_touches_node": "yes",
        "catalyst_date": "also-not-a-date",
        "model_probability": None,
        "holdings": "not-a-list",
    })
    assert result["FINAL_ACTION_GATE"] in (
        cg.GATE_BUY_ALLOWED, cg.GATE_BUY_LIMITED, cg.GATE_WATCHLIST, cg.GATE_BUY_BLOCKED
    )
    assert result["THESIS_TOUCHES_NODE"] is None


# ---------------------------------------------------------------------------
# Value-extraction ledger: exact conservation, named extractors
# ---------------------------------------------------------------------------


def test_ledger_conservation_v11():
    thesis = golden_thesis()
    thesis["thesis_age_days"] = 30.0
    thesis["information_access_premium"] = 4.0
    thesis["channel_premium_score"] = 7.0
    del thesis["operator_fit_score"]  # neutral fit + 0.90 confidence haircut
    del thesis["house_edge_confidence"]  # 0.5 default confidence
    result = cg.evaluate_chicken_gate(thesis)
    eaten = sum(row["points_eaten"] for row in result["VALUE_EXTRACTION_LEDGER"])
    expected = result["RAW_VALIDATED_SCORE"] - result["FINAL_SCORE"]
    assert abs(eaten - expected) <= 0.01
    assert abs(result["VALUE_EATEN_TOTAL_POINTS"] - expected) <= 0.01
    extractors = {row["extractor"] for row in result["VALUE_EXTRACTION_LEDGER"]}
    assert extractors == {
        "TIME_AND_EARLIER_HOLDERS",
        "EARLIER_INFORMED_PARTICIPANTS",
        "PACKAGING_CHANNEL_MARKUP",
        "PORTFOLIO_OVERLAP",
        "MISSING_EVIDENCE_HAIRCUT",
    }
    for row in result["VALUE_EXTRACTION_LEDGER"]:
        assert "reason" in row and row["reason"]
        assert "percent_of_raw_merit" in row


# ---------------------------------------------------------------------------
# Audit artifact: v1.1 fields, stamp, card, CLI, consolidation map
# ---------------------------------------------------------------------------


def test_audit_json_contains_v11_fields():
    result = cg.evaluate_chicken_gate(golden_thesis())
    for key in (
        "SCORING_PROFILE_VERSION", "RAW_TRADE_SCORE", "RAW_VALIDATED_SCORE",
        "RAW_INFLATION_LEAKAGE", "FRESHNESS_MULTIPLIER", "IAP_EFFECTIVE",
        "IAP_CONFIDENCE", "CHANNEL_MULTIPLIER", "OPERATOR_FIT_SCORE",
        "OPERATOR_FIT_CONFIDENCE", "FINAL_SCORE", "FINAL_ACTION_GATE",
        "HARD_FLAG_TRIGGERED", "CAP_RULES_TRIGGERED", "VALUE_EXTRACTION_LEDGER",
        "EVIDENCE_NOTES", "ADVISORY_ONLY_STAMP", "ONE_LINE_REASON",
    ):
        assert key in result, key
    assert result["SCORING_PROFILE_VERSION"] == "chicken-gate-v1.2"


def test_advisory_stamp_preserved():
    result = cg.evaluate_chicken_gate(golden_thesis())
    for stamp in (result["ADVISORY_ONLY_STAMP"], result["safety"]):
        assert stamp["advisory_status"] == "ADVISORY_ONLY"
        assert stamp["execution_gate"] == "LOCKED"
        assert stamp["can_execute"] is False
        assert stamp["broker_api_called"] is False
    assert result["human"]["human_final_decision_required"] is True


def test_trade_card_renders_decision_ledger_and_reason():
    result = cg.evaluate_chicken_gate(golden_thesis())
    card = cg.render_trade_card(result)
    assert "CHICKEN GATE TRADE CARD (v1.1)" in card
    assert "who ate the value before it reached you" in card
    assert "FINAL ACTION: BUY_ALLOWED" in card
    assert "REASON:" in card
    assert "ADVISORY_ONLY" in card


def test_cli_demo_smoke(capsys):
    assert cg.main(["--demo"]) == 0
    out = capsys.readouterr().out
    assert "FINAL ACTION:" in out


def test_consolidation_map_exists():
    map_path = _REPO_ROOT / "docs" / "chicken_gate_consolidation_map.md"
    assert map_path.exists()
    text = map_path.read_text(encoding="utf-8")
    assert "chicken_gate" in text
    assert "Canonical owner" in text or "canonical" in text.lower()
    assert "FUTURE_PORT" in text
