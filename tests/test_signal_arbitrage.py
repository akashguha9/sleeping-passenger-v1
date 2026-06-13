"""Tests for the signal_arbitrage upstream-to-downstream pipeline.

Deterministic, no network, no DB.  Proves each layer in isolation and the
multiplicative-gate property that makes the synthesis hard to fool.
"""
from __future__ import annotations

import pytest

from scripts.signal_arbitrage import (
    classify_platform,
    extract_tokens,
    detect_synthetic_liquidity,
    validate_blind,
    build_truth_ledger,
    compute_vitality,
    classify_timing,
    interpret_beholders,
    ProvenanceLedger,
    freshness_score,
    SignalDossier,
    score_opportunity,
    STAGES,
)
from scripts.signal_arbitrage import (
    analyze_signal,
    legacy_baseline_score,
    expand_ceiling,
)
from scripts.signal_arbitrage.fixtures import ALL_CASES
from scripts.signal_arbitrage import opportunity as opp
from scripts.signal_arbitrage.ceiling import LEVERS


# --------------------------------------------------------------------------
# Layer 1 — platform ecology
# --------------------------------------------------------------------------
def test_platform_ecology_distinguishes_reddit_from_tiktok():
    reddit = classify_platform("reddit")
    tiktok = classify_platform("TikTok")
    assert "pain" in reddit.signal_meaning or "demand" in reddit.signal_meaning
    # Reddit is a longer-half-life, higher-trust ecology than TikTok.
    assert reddit.half_life_days > tiktok.half_life_days
    assert reddit.trust_weight > tiktok.trust_weight


def test_platform_ecology_unknown_is_low_confidence():
    e = classify_platform("myspace")
    assert e.confidence <= 0.4
    assert any("UNKNOWN_PLATFORM" in r for r in e.reason_codes)


def test_platform_category_weight_discounts_off_strength():
    reddit = classify_platform("reddit")
    # Reddit is a reliable source for friction; less so for aesthetic.
    assert reddit.category_weight("friction") > reddit.category_weight("aesthetic")


# --------------------------------------------------------------------------
# Layer 2 — tokenizer
# --------------------------------------------------------------------------
def test_tokenizer_extracts_typed_categories():
    res = extract_tokens("Switched from the incumbent, raised prices 18%, still worth it")
    cats = {t.category for t in res.tokens}
    assert "churn" in cats
    assert "pricing_power" in cats
    assert res.specificity > 0  # "18%" is a specificity cue


def test_tokenizer_density_higher_for_dense_signal():
    dense = extract_tokens("churned 40% of seats, data loss on v2.3, migrated to competitor")
    vague = extract_tokens("this is so good wow amazing nice cool great")
    assert dense.semantic_density > vague.semantic_density


# --------------------------------------------------------------------------
# Layer 3 — synthetic liquidity
# --------------------------------------------------------------------------
def test_synthetic_liquidity_flags_bot_pattern():
    bot = detect_synthetic_liquidity(
        comments=["🔥🔥🔥", "love this", "first", "nice post", "love this"],
        views=1_000_000, likes=100_000, saves=5, conversions=0,
        followers=800_000, velocity=8000, baseline_velocity=400,
        comment_semantic_density=0.05,
    )
    clean = detect_synthetic_liquidity(
        comments=["We hit the same 480V wall and deployed two substations."],
        views=4000, likes=120, saves=40, conversions=15,
        followers=8000, velocity=60, baseline_velocity=55,
        comment_semantic_density=0.6,
    )
    assert bot.contamination > 0.5
    assert clean.contamination < 0.25
    assert bot.authenticity == round(1.0 - bot.contamination, 3)


# --------------------------------------------------------------------------
# Layer 4 — blind validation
# --------------------------------------------------------------------------
def test_blind_validation_explicit_cohort_low_purity():
    res = validate_blind(visible_score=0.8, blind_score=0.2)
    assert res.reality_purity == pytest.approx(0.25, abs=0.01)
    assert res.is_fragile
    assert res.perception_premium == pytest.approx(0.6, abs=0.01)


def test_blind_validation_derived_substance_floor_protects_real_signal():
    # Mostly substance mass, little hype, no contamination → survives blind.
    res = validate_blind(
        visible_score=0.7, hype_mass=0.2, bot_mass=0.0,
        contamination=0.05, substance_mass=3.0,
    )
    assert res.reality_purity >= 0.8
    assert not res.is_fragile


def test_blind_validation_derived_perception_dependent_collapses():
    res = validate_blind(
        visible_score=0.7, hype_mass=3.0, bot_mass=2.0,
        contamination=0.6, substance_mass=0.2,
    )
    assert res.reality_purity < 0.4


# --------------------------------------------------------------------------
# Layer 5 — binary truth ledger
# --------------------------------------------------------------------------
def test_binary_truth_genome_shape_and_state():
    res = build_truth_ledger({
        "authenticity": 0.9, "semantic_density": 0.5, "distinct_roles": 3,
        "conversion_strength": 0.5, "retention_strength": 0.5,
        "contamination": 0.1, "reality_purity": 0.8, "sovereignty": 0.6,
        "reality_confirmation": 0.5, "price_recognition": 0.3,
        "interpretation_gap": 0.4, "within_transfer_window": True,
    })
    assert len(res.genome) == 12
    assert set(res.genome) <= {"0", "1"}
    assert res.truth_state == pytest.approx(1.0)


def test_binary_truth_flags_gap_without_confirmation():
    res = build_truth_ledger({
        "interpretation_gap": 0.8, "reality_confirmation": 0.0,
        "authenticity": 0.2, "contamination": 0.7,
    })
    assert "GAP_WITHOUT_CONFIRMATION_TRAP_RISK" in res.reason_codes


# --------------------------------------------------------------------------
# Layer 6 — vitality funnel (transfer gating)
# --------------------------------------------------------------------------
def test_vitality_transfer_gate_caps_at_bottleneck():
    # Strong birth/attention/density, but conversion is the wall; later stages
    # high in isolation must NOT be credited past the bottleneck.
    scores = {s: 0.9 for s in STAGES}
    scores["conversion"] = 0.1  # stage 6 wall
    res = compute_vitality(scores)
    assert res.bottleneck_stage == "conversion"
    # Cleared the contiguous prefix before conversion (5 stages), not all 11.
    assert res.transferred_stages == 5
    # Transfer-gated vitality is far below the ungated mean.
    assert res.vitality_score < res.raw_vitality
    assert "conversion" in res.next_required_confirmation or res.next_required_confirmation


def test_vitality_full_funnel_high():
    res = compute_vitality({s: 0.8 for s in STAGES})
    assert res.transferred_stages == len(STAGES)
    assert res.vitality_score > 0.6


# --------------------------------------------------------------------------
# Layer 7 — timing
# --------------------------------------------------------------------------
def test_timing_priced_in_is_market_recognition():
    res = classify_timing(strength=0.8, age_days=1, half_life_days=30,
                          price_recognition=0.8)
    assert res.state == "MARKET_RECOGNITION"
    assert not res.within_transfer_window


def test_timing_fresh_breach_in_window():
    res = classify_timing(strength=0.8, age_days=1, half_life_days=90,
                          reality_confirmation=0.2, price_recognition=0.1)
    assert res.within_transfer_window
    assert res.timing_edge_score > 0.3


def test_timing_decay_past_half_life():
    res = classify_timing(strength=0.5, age_days=120, half_life_days=10)
    assert res.state == "POST_HALF_LIFE_DECAY"


# --------------------------------------------------------------------------
# Layer 8 — interpretation gap
# --------------------------------------------------------------------------
def test_interpretation_gap_widens_with_conflicting_tokens():
    # Churn + friction (bearish to longs, bullish to shorts/competitors).
    res = interpret_beholders({"churn": 2.0, "friction": 1.5, "adoption": 1.0})
    assert res.interpretation_gap > 0.3
    assert res.minority.beholder != res.dominant.beholder


# --------------------------------------------------------------------------
# Layer 9 — provenance ledger
# --------------------------------------------------------------------------
def test_provenance_chain_valid_and_tamper_detected():
    led = ProvenanceLedger("sig1")
    led.record(0, "FIRST_SEEN", {"source": "reddit"})
    e2 = led.record(1, "SCORE", {"value": 0.3})
    led.record(3, "SCORE", {"value": 0.55})
    assert led.verify_chain()
    assert led.score_deltas()[0]["delta"] == pytest.approx(0.25, abs=0.001)
    # Tamper with an earlier event's detail → chain breaks.
    led._events[1] = type(e2)(seq=1, day=1, kind="SCORE",
                              detail={"value": 0.99}, prev_hash=e2.prev_hash,
                              hash=e2.hash)
    assert not led.verify_chain()


def test_freshness_decays_with_recognition_and_crowding():
    fresh = freshness_score(age_days=2, half_life_days=90,
                            interpretation_migration=0.1, price_recognition=0.1,
                            crowding=0.1)
    stale = freshness_score(age_days=2, half_life_days=90,
                            interpretation_migration=0.8, price_recognition=0.8,
                            crowding=0.8)
    assert fresh["score"] > stale["score"]


# --------------------------------------------------------------------------
# Layer 10 — opportunity synthesis & the multiplicative-gate property
# --------------------------------------------------------------------------
@pytest.mark.parametrize("key,expected", [
    ("A", {"WATCH", "BUY"}),
    ("B", {"NARRATIVE_TRAP", "AVOID"}),
    ("C_shopify", {"WATCH", "BUY", "LONG_TERM_COMPOUNDER"}),
    ("C_etsy", {"AVOID", "NEEDS_CONFIRMATION"}),
    ("D", {"NARRATIVE_TRAP", "AVOID"}),
    ("E", {"WATCH", "BUY"}),
])
def test_case_decisions(key, expected):
    rep = score_opportunity(ALL_CASES[key]())
    assert rep["decision"] in expected, (key, rep["decision"], rep["decision_reason_codes"])


def test_multiplicative_gate_never_exceeds_merit():
    # The core anti-fool invariant: gates can only cap, never inflate.
    for fn in ALL_CASES.values():
        rep = score_opportunity(fn())
        ss = rep["segment_scores"]
        assert ss["final_opportunity"] <= ss["raw_merit_additive"] + 1e-9


def test_bot_hype_collapses_to_near_zero():
    rep = score_opportunity(ALL_CASES["B"]())
    assert rep["segment_scores"]["final_opportunity"] <= 0.05
    assert rep["segment_scores"]["synthetic_contamination"] >= 0.5


def test_blind_failure_has_low_purity():
    rep = score_opportunity(ALL_CASES["D"]())
    assert rep["segment_scores"]["reality_purity"] < 0.4


def test_shopify_more_sovereign_than_etsy():
    shop = score_opportunity(ALL_CASES["C_shopify"]())
    etsy = score_opportunity(ALL_CASES["C_etsy"]())
    assert shop["segment_scores"]["sovereignty"] > etsy["segment_scores"]["sovereignty"]
    # And the owned-demand merchant clears more of the funnel.
    assert shop["segment_scores"]["final_opportunity"] > etsy["segment_scores"]["final_opportunity"]


def test_early_interpretation_gap_is_watchable():
    rep = score_opportunity(ALL_CASES["E"]())
    assert rep["segment_scores"]["interpretation_gap"] >= 0.4
    assert rep["segment_scores"]["provenance_freshness"] >= 0.4
    assert rep["decision"] in {"WATCH", "BUY"}


def test_report_is_advisory_only_and_deterministic():
    d = ALL_CASES["A"]()
    r1 = score_opportunity(d)
    r2 = score_opportunity(d)
    assert r1["advisory_status"] == "ADVISORY_ONLY"
    assert r1["real_money_execution"] == "PROHIBITED"
    assert r1["broker_api_called"] is False
    assert r1["segment_scores"] == r2["segment_scores"]  # pure / deterministic


def test_decision_label_constants_cover_brief():
    required = {opp.BUY, opp.WATCH, opp.AVOID, opp.SHORT_CANDIDATE, opp.TOO_LATE,
               opp.EVENT_DRIVEN, opp.LONG_TERM_COMPOUNDER, opp.NARRATIVE_TRAP,
               opp.NEEDS_CONFIRMATION}
    assert len(required) == 9


# --------------------------------------------------------------------------
# Dual-score / ceiling / attribution layer
# --------------------------------------------------------------------------
def test_legacy_baseline_overscores_bot_hype():
    # The naive volume/social-proof model is fooled by the bot case; the gated
    # model is not.  That gap is the whole point of the upgrade.
    legacy = legacy_baseline_score(ALL_CASES["B"]())
    investable = analyze_signal(ALL_CASES["B"]())["investable_score"]
    assert legacy["score"] >= 0.7
    assert investable <= 0.05


def test_research_ceiling_never_below_investable():
    for fn in ALL_CASES.values():
        a = analyze_signal(fn())
        assert a["research_ceiling_score"] >= a["investable_score"] - 1e-9
        assert a["ceiling_delta"] >= -1e-9


def test_gate_haircut_is_nonpositive_risk_haircut():
    # A negative gate haircut is expected: it is risk removed, not failure.
    for fn in ALL_CASES.values():
        a = analyze_signal(fn())
        assert a["gate_haircut"] <= 1e-9


def test_bot_hype_ceiling_pinned_near_zero():
    # Even with EVERY achievable evidence lever maxed, a contaminated signal's
    # ceiling stays near zero — surface inflation cannot manufacture a Buy.
    a = analyze_signal(ALL_CASES["B"]())
    assert a["research_ceiling_score"] <= 0.1
    assert a["ceiling_decision"] not in {"BUY", "LONG_TERM_COMPOUNDER"}
    assert a["binding_gate"] == "reality_purity"


def test_blind_failure_ceiling_is_fraud_gated():
    a = analyze_signal(ALL_CASES["D"]())
    assert a["research_ceiling_score"] <= 0.15
    assert a["binding_gate"] == "reality_purity"


def test_trap_cases_show_positive_risk_detection():
    for key in ("B", "D"):
        a = analyze_signal(ALL_CASES[key]())
        assert a["risk_detection_delta"] > 0.5
        assert a["trap_suppression_score"] >= 0.5


def test_clean_cases_show_nonnegative_ceiling_delta():
    for key in ("A", "C_shopify", "E"):
        a = analyze_signal(ALL_CASES[key]())
        assert a["ceiling_delta"] >= 0.0


def test_early_opportunity_upgrade_delta_positive_and_buyable_ceiling():
    # The early interpretation-gap case is investable WATCH now, but its
    # research ceiling reaches BUY once fundamentals confirm — and that ceiling
    # genuinely exceeds the naive legacy model.
    a = analyze_signal(ALL_CASES["E"]())
    assert a["decision"] == "WATCH"
    assert a["ceiling_decision"] == "BUY"
    assert a["upgrade_delta"] > 0.0
    assert a["ceiling_delta"] > 0.1


def test_binding_bottleneck_fix_increases_ceiling():
    # The named bottleneck must actually move the score when applied.
    a = analyze_signal(ALL_CASES["E"]())
    bottleneck = a["binding_bottleneck"]
    assert bottleneck is not None
    effect = next(e for e in a["lever_effects"] if e["lever"] == bottleneck)
    assert effect["marginal_gain"] > 0.0
    assert effect["achievable"] is True


def test_counterfactuals_include_achievable_and_diagnostic():
    a = analyze_signal(ALL_CASES["A"]())
    levers = {e["lever"] for e in a["lever_effects"]}
    assert "fundamentals_confirm" in levers          # achievable
    assert "if_engagement_authentic" in levers       # fraud diagnostic
    assert "recognition_crowds" in levers            # downside diagnostic
    # The fraud diagnostic must be flagged non-achievable so it never counts
    # toward the investable ceiling.
    diag = next(e for e in a["lever_effects"] if e["lever"] == "if_engagement_authentic")
    assert diag["achievable"] is False


def test_dual_score_object_is_complete_and_advisory():
    a = analyze_signal(ALL_CASES["A"]())
    for key in ("investable_score", "research_ceiling_score", "trap_suppression_score",
                "legacy_baseline", "raw_merit", "upgrade_delta", "ceiling_delta",
                "risk_detection_delta", "gate_haircut", "binding_bottleneck",
                "binding_gate", "next_required_confirmation"):
        assert key in a, key
    assert a["advisory_status"] == "ADVISORY_ONLY"
    assert a["real_money_execution"] == "PROHIBITED"
    assert analyze_signal(ALL_CASES["A"]()) == a  # deterministic


def test_final_le_raw_merit_invariant_holds_at_ceiling_too():
    # The spine: gates only cap. Even the ceiling dossier obeys final<=merit.
    for fn in ALL_CASES.values():
        a = analyze_signal(fn())
        assert a["investable_score"] <= a["raw_merit"] + 1e-9


# --------------------------------------------------------------------------
# Strategist layer — EV / kill-switch / confidence / attribution / timing
# --------------------------------------------------------------------------
from scripts.signal_arbitrage import SignalDossier, strategize_signal


# ---- Expected value / ante ----
def test_ev_next_evidence_positive_for_early_opportunity():
    s = strategize_signal(ALL_CASES["E"]())
    assert s["next_evidence_gain"] > 0.0
    assert s["expected_value_of_waiting"] > 0.0


def test_ev_waiting_negative_for_crowded_or_decaying():
    s = strategize_signal(ALL_CASES["F"]())
    assert s["expected_value_of_waiting"] <= 0.0
    assert s["recommended_action"] in {"EXIT_OR_IGNORE", "SHORTLIST_ONLY"}


def test_bot_gets_no_positive_action_or_ev():
    s = strategize_signal(ALL_CASES["B"]())
    assert s["recommended_action"] in {"AVOID_TRAP", "REJECT_UNTIL_FRAUD_RESOLVED", "EXIT_OR_IGNORE"}
    assert s["expected_value_of_acting_now"] <= 0.0


def test_blind_failure_rejected_until_fraud_resolved():
    s = strategize_signal(ALL_CASES["D"]())
    assert s["recommended_action"] in {"REJECT_UNTIL_FRAUD_RESOLVED", "AVOID_TRAP"}


# ---- Kill switches ----
def test_every_analysis_has_thesis_break_conditions():
    for fn in ALL_CASES.values():
        s = strategize_signal(fn())
        assert len(s["kill_switches"]) >= 1
        assert len(s["thesis_break_conditions"]) >= 1
        for k in s["kill_switches"]:
            assert {"condition", "severity", "monitoring_signal", "current_risk"} <= set(k)


def test_bot_killswitch_includes_synthetic_or_reality():
    s = strategize_signal(ALL_CASES["B"]())
    conds = set(s["thesis_break_conditions"])
    assert "synthetic_contamination_rises" in conds or "blind_score_stays_weak" in conds


def test_blind_killswitch_includes_blind_reality():
    s = strategize_signal(ALL_CASES["D"]())
    assert "blind_score_stays_weak" in s["thesis_break_conditions"]


def test_clean_killswitch_includes_fundamentals_or_retention():
    for key in ("A", "E"):
        s = strategize_signal(ALL_CASES[key]())
        conds = set(s["thesis_break_conditions"])
        assert conds & {"fundamentals_fail_after_maturation", "retention_stays_zero",
                        "conversion_never_arrives"}


def test_negative_counterfactuals_present_and_drop_score():
    s = strategize_signal(ALL_CASES["A"]())
    assert len(s["negative_counterfactuals"]) >= 1
    names = {c["scenario"] for c in s["negative_counterfactuals"]}
    assert "fundamentals_fail" in names
    for c in s["negative_counterfactuals"]:
        assert c["score_drop"] >= -1e-9  # downside scenarios never raise the score


# ---- Confidence ----
def test_bot_hype_is_high_confidence_trap():
    s = strategize_signal(ALL_CASES["B"]())
    assert s["confidence_label"] == "HIGH_CONFIDENCE_TRAP"
    assert s["confidence_score"] >= 0.55


def test_blind_failure_is_high_confidence_trap():
    s = strategize_signal(ALL_CASES["D"]())
    assert s["confidence_label"] == "HIGH_CONFIDENCE_TRAP"


def test_interpretation_gap_is_fragile_opportunity():
    s = strategize_signal(ALL_CASES["E"]())
    assert s["confidence_label"] == "FRAGILE_OPPORTUNITY"
    assert "FRAGILE_FUNDAMENTALS_MISSING" in s["confidence"]["reason_codes"]


def test_insufficient_evidence_is_not_high_confidence():
    sparse = SignalDossier(signal_id="sparse", text="something happened recently",
                           platforms=["reddit"])
    s = strategize_signal(sparse)
    assert s["confidence_label"] == "INSUFFICIENT_EVIDENCE"
    assert s["confidence_score"] < 0.6


# ---- Attribution ----
def test_each_case_has_positive_and_negative_drivers():
    for fn in ALL_CASES.values():
        s = strategize_signal(fn())
        assert len(s["top_positive_drivers"]) >= 1
        assert len(s["top_negative_drivers"]) >= 1


def test_bot_negative_drivers_include_contamination_or_purity():
    s = strategize_signal(ALL_CASES["B"]())
    factors = " ".join(d["factor"] for d in s["top_negative_drivers"])
    assert "reality_purity" in factors or "contamination" in factors or "authenticity" in factors


def test_shopify_positive_drivers_include_sovereignty():
    s = strategize_signal(ALL_CASES["C_shopify"]())
    factors = {d["factor"] for d in s["top_positive_drivers"]}
    assert "sovereignty" in factors


def test_etsy_negative_drivers_include_platform_dependence():
    s = strategize_signal(ALL_CASES["C_etsy"]())
    factors = " ".join(d["factor"] for d in s["top_negative_drivers"])
    assert "platform_dependence" in factors or "sovereignty" in factors


def test_e_positive_drivers_include_gap_or_freshness():
    s = strategize_signal(ALL_CASES["E"]())
    factors = " ".join(d["factor"] for d in s["top_positive_drivers"])
    assert "interpretation_gap" in factors or "freshness" in factors
    # transfer is represented via the vitality(funnel_transfer) merit driver
    assert "transfer" in factors


def test_trap_suppression_drivers_are_gates_for_bot():
    s = strategize_signal(ALL_CASES["B"]())
    assert len(s["top_trap_suppression_drivers"]) >= 1
    factors = " ".join(d["factor"] for d in s["top_trap_suppression_drivers"])
    assert "reality_purity" in factors or "recognition" in factors or "transfer" in factors


# ---- Timing ----
def test_decay_and_crowding_adjusted_ceilings_le_research():
    for fn in ALL_CASES.values():
        s = strategize_signal(fn())
        assert s["decay_adjusted_ceiling"] <= s["research_ceiling_score"] + 1e-9
        assert s["crowding_adjusted_ceiling"] <= s["research_ceiling_score"] + 1e-9


def test_urgency_score_present_and_bounded():
    for fn in ALL_CASES.values():
        s = strategize_signal(fn())
        assert 0.0 <= s["urgency_score"] <= 1.0


def test_active_transfer_window_beats_post_half_life():
    active = strategize_signal(ALL_CASES["E"]())
    late = strategize_signal(ALL_CASES["F"]())
    assert active["timing"]["timing_edge_v2"] > late["timing"]["timing_edge_v2"]
    assert active["timing_quality_label"] in {"EARLY_AND_ALIVE", "ACTIVE_TRANSFER_WINDOW"}
    assert late["timing_quality_label"] in {"EXHAUSTED", "DECAYING", "CONFIRMED_BUT_CROWDED"}


# ---- Strategist-level invariants (fraud spine intact) ----
def test_strategist_research_ceiling_stays_fraud_gated():
    for key in ("B", "D"):
        s = strategize_signal(ALL_CASES[key]())
        assert s["research_ceiling_score"] <= 0.1
        assert s["durability_adjusted_ceiling"] <= 0.1  # durability can't rescue fraud


def test_strategist_fake_cannot_become_buy():
    for key in ("B", "D"):
        s = strategize_signal(ALL_CASES[key]())
        assert s["ceiling_decision"] not in {"BUY", "LONG_TERM_COMPOUNDER"}
        assert s["recommended_action"] != "ACT_NOW"


def test_strategist_is_deterministic():
    import json
    d = ALL_CASES["A"]()
    a = json.dumps(strategize_signal(d), sort_keys=True, default=str)
    b = json.dumps(strategize_signal(d), sort_keys=True, default=str)
    assert a == b


def test_strategist_final_le_raw_merit():
    for fn in ALL_CASES.values():
        s = strategize_signal(fn())
        assert s["investable_score"] <= s["raw_merit"] + 1e-9


def test_strategist_carries_advisory_stamps():
    s = strategize_signal(ALL_CASES["A"]())
    assert s["advisory_status"] == "ADVISORY_ONLY"
    assert s["real_money_execution"] == "PROHIBITED"
