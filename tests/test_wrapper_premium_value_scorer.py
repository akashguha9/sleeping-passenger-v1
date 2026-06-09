"""Tests for the Wrapper-Premium / Value-Layer company scorer (WPVS)."""
from __future__ import annotations

import json

import pytest

from scripts.wrapper_premium_value_scorer import (
    DEFAULT_POSITIVE_WEIGHTS,
    EQ_MISSING,
    EV_MISSING,
    REC_AVOID,
    REC_BUY,
    REC_INSUFFICIENT,
    REC_WATCH,
    SEG_A,
    SEG_B,
    SEG_C,
    SEG_F,
    SEG_G,
    SEGMENT_KEYS,
    EvidenceStatus,
    SegmentScore,
    _norm,
    analyze_company,
    compute_delta,
    render_report,
    resolve_weights,
    score_company_legacy,
    score_company_upgraded,
)

TS = "2026-06-09T00:00:00Z"

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _premium_wrapper() -> dict:
    """Luxury / IP-heavy brand: strong wrapper, cultural asset, IP memory."""
    return {
        "ticker": "lux", "company_name": "Premium Wrapper Co", "sector": "luxury",
        "legacy_score": 60,
        "evidence": {
            "price_premium_vs_substitute": 0.9, "gross_margin_premium": 0.85,
            "resale_premium": 0.9, "brand_search_index": 0.85, "protection_durability": 0.8,
            "perceived_origin_strength": 0.8, "luxury_name_codes": 0.85,
            "narrative_story_strength": 0.85, "scarcity": 0.8, "community": 0.8,
            "liquidity": 0.7, "blind_valuation_ratio": 0.3,
            "partner_brand_heat": 0.85, "collab_history_perf": 0.8, "sellout_speed": 0.85,
            "cultural_novelty": 0.8, "resale_volume": 0.8, "bid_ask_tightness": 0.7,
            "authentication": 0.85, "visual_recognition": 0.9, "memeability": 0.75,
            "photo_impact": 0.8, "ip_nostalgia": 0.7, "licensing_revenue": 0.7,
            "fan_community_persistence": 0.75, "replica_volume": 0.6, "replica_price_gap": 0.7,
            "prestige_dilution": 0.25, "brand_enforcement_weakness": 0.2,
            "patent_protection": 0.6, "regulatory_exclusivity": 0.4, "clinical_trust": 0.5,
            "distribution_strength": 0.8, "generic_threat": 0.2, "private_label_penetration": 0.2,
            "open_source_threat": 0.1, "remaining_protection": 0.8, "catalog_size": 0.6,
            "licensing_optionality": 0.7, "hook_recognizability": 0.6, "reuse_frequency": 0.5,
            "licensability": 0.6,
            "format_market_fit": 0.7, "platform_fit": 0.7, "distribution_optionality": 0.7,
            "monetization_efficiency": 0.7,
            "patents_present": 0.5, "regulatory_approvals": 0.4, "brand_equity": 0.95,
            "distribution_scale": 0.8, "capital_access": 0.8, "network_assets": 0.6,
            "arbitrage_gap": 0.55, "market_misframing": 0.5, "capability_to_exploit": 0.7,
            "catalyst_visibility": 0.5,
            "demand_authenticity": 0.8, "placebo_pricing_power": 0.7,
            "measurement_contamination": 0.25, "false_pattern_risk": 0.25,
            "survivorship_bias_risk": 0.3, "anchoring_risk": 0.25, "confirmation_bias_risk": 0.25,
            "blind_utility_gap": 0.4, "paid_promo_intensity": 0.25,
            "brutal_utility": 0.3, "customer_roi": 0.4, "price_compression": 0.2,
            "behavior_expansion": 0.3, "friction_to_meme": 0.4, "brand_model_alignment": 0.6,
            "constraint_as_brand_asset": 0.3,
        },
    }


def _pharma_patent_cliff() -> dict:
    """Pharma at the patent cliff: protection real but decaying fast."""
    return {
        "ticker": "rx", "company_name": "Patent Cliff Pharma", "sector": "pharma",
        "legacy_score": 58,
        "evidence": {
            "patent_protection": 0.85, "regulatory_exclusivity": 0.8, "clinical_trust": 0.8,
            "distribution_strength": 0.7,
            "remaining_protection": 0.1, "generic_threat": 0.9, "private_label_penetration": 0.7,
            "open_source_threat": 0.2, "catalog_size": 0.4, "licensing_optionality": 0.3,
            "hook_recognizability": 0.2, "reuse_frequency": 0.2, "licensability": 0.3,
            "measurement_contamination": 0.3, "false_pattern_risk": 0.3,
            "demand_authenticity": 0.7, "blind_utility_gap": 0.2,
        },
    }


def _ryanair_brutal_utility() -> dict:
    """Brutal-utility / customer-ROI engine: low wrapper, high access-per-euro."""
    return {
        "ticker": "ryaay", "company_name": "Brutal Utility Air", "sector": "airline",
        "legacy_score": 55,
        "evidence": {
            "brutal_utility": 0.9, "customer_roi": 0.9, "price_compression": 0.85,
            "behavior_expansion": 0.8, "friction_to_meme": 0.85, "brand_model_alignment": 0.9,
            "constraint_as_brand_asset": 0.85,
            "price_premium_vs_substitute": 0.1, "gross_margin_premium": 0.15,
            "resale_premium": 0.05, "brand_search_index": 0.6, "blind_valuation_ratio": 0.95,
            "luxury_name_codes": 0.1, "perceived_origin_strength": 0.2,
            "format_market_fit": 0.7, "platform_fit": 0.6, "distribution_optionality": 0.7,
            "monetization_efficiency": 0.75,
            "demand_authenticity": 0.8, "measurement_contamination": 0.25,
            "false_pattern_risk": 0.2, "blind_utility_gap": 0.1, "paid_promo_intensity": 0.2,
            "arbitrage_gap": 0.5, "capability_to_exploit": 0.7, "distribution_scale": 0.9,
            "capital_access": 0.6, "network_assets": 0.7,
        },
    }


def _hype_only() -> dict:
    """Narrative noise, manufactured demand, contaminated metrics — a hype trap."""
    return {
        "ticker": "hype", "company_name": "Hype Only Inc", "sector": "consumer",
        "legacy_score": 50,
        "evidence": {
            "narrative_story_strength": 0.9, "brand_search_index": 0.7, "memeability": 0.85,
            "visual_recognition": 0.7, "scarcity": 0.6,
            "measurement_contamination": 0.85, "false_pattern_risk": 0.9,
            "survivorship_bias_risk": 0.8, "anchoring_risk": 0.7, "confirmation_bias_risk": 0.8,
            "blind_utility_gap": 0.9, "paid_promo_intensity": 0.9, "demand_authenticity": 0.15,
            "placebo_pricing_power": 0.2,
            "price_premium_vs_substitute": 0.6, "gross_margin_premium": 0.4,
            "resale_premium": 0.5, "blind_valuation_ratio": 0.85,
            "protection_durability": 0.2, "patent_protection": 0.1, "remaining_protection": 0.3,
            "generic_threat": 0.7,
            "brutal_utility": 0.2, "customer_roi": 0.3,
        },
    }


def _commodity() -> dict:
    """Decent fundamentals, but no wrapper / cultural / IP story at all."""
    return {
        "ticker": "comm", "company_name": "Commodity Corp", "sector": "industrials",
        "fundamentals": {
            "operating_margin": 0.12, "revenue_growth": 0.08, "fcf_margin": 0.10,
            "debt_to_equity": 0.4,
        },
        "evidence": {
            "price_premium_vs_substitute": 0.15, "gross_margin_premium": 0.1,
            "resale_premium": 0.05, "brand_search_index": 0.2, "blind_valuation_ratio": 0.95,
            "luxury_name_codes": 0.1, "narrative_story_strength": 0.15,
            "patent_protection": 0.2, "remaining_protection": 0.5, "generic_threat": 0.6,
            "demand_authenticity": 0.6, "measurement_contamination": 0.3,
            "false_pattern_risk": 0.2, "blind_utility_gap": 0.9,
            "brutal_utility": 0.4, "customer_roi": 0.45,
        },
    }


# --------------------------------------------------------------------------- #
# Unit: helpers / normalization
# --------------------------------------------------------------------------- #


def test_norm_accepts_fraction_and_percent_and_clamps():
    assert _norm(0.8) == 0.8
    assert _norm(80) == 0.8
    assert _norm(0) == 0.0
    assert _norm(150) == 1.0
    assert _norm(-5) == 0.0
    assert _norm(None) is None
    assert _norm("x") is None


def test_evidence_status_from_coverage():
    assert EvidenceStatus.from_coverage(0.9) == "direct"
    assert EvidenceStatus.from_coverage(0.4) == "proxy"
    assert EvidenceStatus.from_coverage(0.0) == "missing"


def test_segment_score_to_dict_serializable():
    s = SegmentScore(key=SEG_A, score=70, confidence=80, evidence_status="direct")
    json.dumps(s.to_dict())


# --------------------------------------------------------------------------- #
# Unit: legacy pre-score
# --------------------------------------------------------------------------- #


def test_legacy_uses_provided_score():
    r = score_company_legacy({"legacy_score": 73})
    assert r["legacy_pre_score"] == 73.0
    assert r["synthetic"] is False


def test_legacy_synthesizes_from_fundamentals_when_missing():
    r = score_company_legacy({"fundamentals": {"operating_margin": 0.30, "revenue_growth": 0.30, "fcf_margin": 0.25, "debt_to_equity": 0.1}})
    assert r["synthetic"] is True
    assert r["source"] == "synthetic_pre_score_from_existing_inputs"
    assert r["legacy_pre_score"] > 50  # strong fundamentals lift the baseline


def test_legacy_neutral_when_no_inputs():
    r = score_company_legacy({"ticker": "X"})
    assert r["legacy_pre_score"] == 50.0
    assert r["evidence_quality"] == EQ_MISSING


# --------------------------------------------------------------------------- #
# Unit: sector weighting
# --------------------------------------------------------------------------- #


def test_default_weights_sum_preserved():
    w = resolve_weights(None)
    assert w == DEFAULT_POSITIVE_WEIGHTS


def test_airline_tilt_boosts_brutal_utility_and_preserves_total():
    w = resolve_weights("airline")
    assert w[SEG_G] > DEFAULT_POSITIVE_WEIGHTS[SEG_G]
    assert w[SEG_A] < DEFAULT_POSITIVE_WEIGHTS[SEG_A]
    assert abs(sum(w.values()) - sum(DEFAULT_POSITIVE_WEIGHTS.values())) < 1e-9


def test_pharma_tilt_boosts_ip_segment():
    w = resolve_weights("pharma")
    assert w[SEG_C] > DEFAULT_POSITIVE_WEIGHTS[SEG_C]


# --------------------------------------------------------------------------- #
# Unit: missing evidence + risk penalty + delta + determinism
# --------------------------------------------------------------------------- #


def test_missing_evidence_is_neutral_and_insufficient():
    r = analyze_company({"ticker": "BARE"}, analysis_timestamp=TS)
    assert r["evidence_quality"] == EQ_MISSING
    assert r["recommendation"] == REC_INSUFFICIENT
    # neutral evidence → post barely moves from pre.
    assert abs(r["delta"]) < 5
    for seg in SEGMENT_KEYS:
        assert r["segmented_scores"][seg]["evidence_status"] == EV_MISSING


def test_minimal_input_does_not_crash_and_serializes():
    r = analyze_company({"ticker": "X"})
    json.dumps(r)


def test_risk_penalty_applies_for_contaminated_company():
    r = analyze_company(_hype_only(), analysis_timestamp=TS)
    assert r["bias_penalty"]["points"] > 0
    assert r["segmented_scores"][SEG_F]["risk_score"] >= 60
    # contributions: the bias segment contributes negatively.
    contrib = {row["segment"]: row for row in r["pre_post_delta_table"]}
    assert SEG_F in contrib


def test_compute_delta_table_shape():
    pre, post = 60.0, 64.0
    post_map = {k: 55.0 for k in SEGMENT_KEYS}
    table = compute_delta(pre, post, {k: None for k in SEGMENT_KEYS}, post_map)
    assert table[0]["segment"] == "OVERALL"
    assert table[0]["delta"] == 4.0
    seg_rows = {row["segment"]: row for row in table[1:]}
    assert set(seg_rows) == set(SEGMENT_KEYS)
    for row in seg_rows.values():
        assert row["pre"] is None and row["delta"] is None


def test_determinism():
    a = analyze_company(_premium_wrapper(), analysis_timestamp=TS)
    b = analyze_company(_premium_wrapper(), analysis_timestamp=TS)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_reflection_model_off_is_passthrough():
    r = score_company_upgraded(_premium_wrapper(), reflection_model=False)
    assert r["upgraded_post_score"] == score_company_legacy(_premium_wrapper())["legacy_pre_score"]


# --------------------------------------------------------------------------- #
# Fixture behaviour
# --------------------------------------------------------------------------- #


def test_premium_wrapper_strong_segments_and_positive_delta():
    r = analyze_company(_premium_wrapper(), analysis_timestamp=TS)
    seg = r["segmented_scores"]
    assert seg[SEG_A]["score"] >= 60  # strong wrapper premium
    assert seg[SEG_B]["score"] >= 55  # cultural asset
    assert r["delta"] > 0
    assert r["recommendation"] in {REC_BUY, REC_WATCH}


def test_pharma_patent_cliff_flags_decay():
    r = analyze_company(_pharma_patent_cliff(), analysis_timestamp=TS)
    c = r["segmented_scores"][SEG_C]
    assert c["modules"]["commodity_decay_risk"] >= 60
    assert any("cliff" in f or "decay" in f for f in r["red_flags"])


def test_ryanair_brutal_utility_drives_delta():
    r = analyze_company(_ryanair_brutal_utility(), analysis_timestamp=TS)
    seg = r["segmented_scores"]
    assert seg[SEG_G]["score"] >= 75  # strong brutal-utility engine
    assert seg[SEG_A]["score"] <= 45  # deliberately low wrapper
    assert r["delta"] > 0
    # G is the dominant positive contributor for an airline.
    top = r["delta_explanation"]["largest_segment_contributors"][0]["segment"]
    assert top == SEG_G


def test_hype_only_is_penalized_and_flagged():
    r = analyze_company(_hype_only(), analysis_timestamp=TS)
    assert r["segmented_scores"][SEG_F]["risk_score"] >= 65
    assert r["delta"] < 0
    assert r["recommendation"] in {REC_AVOID, REC_WATCH}
    assert r["red_flags"]


def test_commodity_low_wrapper_low_cultural():
    r = analyze_company(_commodity(), analysis_timestamp=TS)
    seg = r["segmented_scores"]
    assert seg[SEG_A]["score"] <= 40
    assert seg[SEG_B]["score"] <= 55


def test_premium_beats_hype_on_post_score():
    premium = analyze_company(_premium_wrapper(), analysis_timestamp=TS)
    hype = analyze_company(_hype_only(), analysis_timestamp=TS)
    assert premium["upgraded_post_score"] > hype["upgraded_post_score"]


# --------------------------------------------------------------------------- #
# Output contract + report
# --------------------------------------------------------------------------- #


def test_full_json_contract_keys_present():
    r = analyze_company(_premium_wrapper(), analysis_timestamp=TS)
    for key in (
        "ticker", "company_name", "analysis_timestamp", "legacy_pre_score",
        "upgraded_post_score", "delta", "recommendation", "confidence",
        "evidence_quality", "segmented_scores", "delta_explanation",
        "pre_post_delta_table", "red_flags", "missing_evidence",
        "next_evidence_to_collect",
    ):
        assert key in r, key
    assert set(r["segmented_scores"]) == set(SEGMENT_KEYS)
    assert r["advisory_only"] is True
    # advisory safety invariants honoured.
    assert r["execution"]["execution_mode"] == "HUMAN_ONLY"


def test_render_report_is_markdown_with_headline():
    r = analyze_company(_ryanair_brutal_utility(), analysis_timestamp=TS)
    md = render_report(r)
    assert md.startswith("# Wrapper-Premium Value Analysis")
    assert "Upgraded post-score" in md
    assert "Pre / Post / Delta" in md
