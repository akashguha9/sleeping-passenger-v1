"""Tests for Mythos — the meaning-routing interpretation engine.

Deterministic, no network, no DB.  Proves the maps-metaphor behaviors: raw
observation is not truth, governance is differentiated, the same signal reads
differently by worldview, interpretations are reality-checked and confidence is
capped by layer integrity — and Mythos never lets weak/narrative-only evidence
become a high-conviction strategy or weaken Fable's fraud gates.
"""
from __future__ import annotations

import json

import pytest

from scripts.signal_arbitrage.mythos import (
    MythosObservation,
    run_mythos,
    build_fable5_dossier,
)
from scripts.signal_arbitrage.mythos_fixtures import ALL_MYTHOS_CASES
from scripts.signal_arbitrage.opportunity import score_opportunity


def M(key):
    return run_mythos(ALL_MYTHOS_CASES[key]())


# --------------------------------------------------------------------------
# Observation / governance
# --------------------------------------------------------------------------
def test_official_source_differs_from_social_feed():
    official = M("2_revenue_ambiguity")
    social = M("3_narrative_no_reality")
    assert official["governance_type"] == "OFFICIAL_SOURCE"
    assert social["governance_type"] == "SOCIAL_FEED"
    assert official["governance_trust_score"] > social["governance_trust_score"]


def test_open_community_gets_provisional_confidence():
    m = M("7_open_vs_closed_governance")
    assert m["governance_type"] == "OPEN_COMMUNITY"
    assert m["claim_status"] == "PROVISIONAL"
    assert m["strategy_eligibility"] != "STRATEGY_ALLOWED"


def test_noisy_source_cannot_be_high_confidence_alone():
    noisy = run_mythos(MythosObservation(
        source="x", entity="NOISE", raw_text="huge buzz, going viral",
        reliability=0.3, recency=0.9, independence=0.2, coverage=0.2, noise_level=0.9,
        confidence_prior=0.6, attention=0.9, mentions_velocity=0.9))
    assert "NOISY_SOURCE" in noisy["observation_reason_codes"]
    assert noisy["observation_quality_score"] < 0.5
    assert noisy["final_mythos_confidence"] < 0.6
    assert noisy["strategy_eligibility"] != "STRATEGY_ALLOWED"


# --------------------------------------------------------------------------
# Interpretation
# --------------------------------------------------------------------------
def test_same_signal_read_differently_by_worldview():
    m = M("8_worldview_disagreement")
    dirs = {w["implied_interpretation"] for w in m["worldview_interpretations"]}
    assert {"BULLISH", "BEARISH"} <= dirs            # genuine disagreement
    assert m["dominant_interpretation"]["beholder"] != m["contrarian_interpretation"]["beholder"]


def test_revenue_growth_yields_multiple_explanations():
    m = M("2_revenue_ambiguity")
    mm = m["map_matching"]
    assert len(mm["candidate_explanations"]) >= 5
    assert mm["best_explanation"] is None            # unresolved without corroboration
    assert mm["resolved"] is False


def test_map_matching_resolves_only_with_corroboration():
    bare = M("2_revenue_ambiguity")["map_matching"]
    corro = M("2b_revenue_corroborated")["map_matching"]
    assert bare["best_explanation"] is None
    assert corro["best_explanation"] == "organic_demand"
    assert corro["resolved"] is True


def test_interpretation_gap_increases_with_conflicting_tokens():
    conflict = run_mythos(MythosObservation(
        source="sec_filing", entity="C",
        raw_text="adoption rising but churn rising and margins falling, switched from us"))
    aligned = run_mythos(MythosObservation(
        source="sec_filing", entity="A",
        raw_text="adoption rising, retention strong, recommend, been using for years"))
    assert conflict["interpretation_gap_score"] >= aligned["interpretation_gap_score"]


# --------------------------------------------------------------------------
# Reality check
# --------------------------------------------------------------------------
def test_confirming_evidence_increases_trust():
    m = run_mythos(MythosObservation(
        source="sec_filing", entity="UP", raw_text="retention improved",
        confidence_prior=0.5, retention=0.7,
        evidence_events=({"day": 5, "supports": True, "weight": 0.8, "independent": 0.8},)))
    rc = m["reality_check"]
    assert rc["confidence_after"] > rc["confidence_before"]
    assert rc["survival_count"] == 1


def test_contradicting_evidence_reduces_trust():
    m = run_mythos(MythosObservation(
        source="sec_filing", entity="DOWN", raw_text="retention improved",
        confidence_prior=0.5, retention=0.7,
        evidence_events=({"day": 5, "supports": False, "weight": 0.8, "independent": 0.8},)))
    rc = m["reality_check"]
    assert rc["confidence_after"] < rc["confidence_before"]
    assert rc["contradiction_count"] == 1


def test_missed_validation_window_marks_stale():
    m = M("5_eta_error")
    assert m["claim_status"] in {"STALE", "CONTESTED"}


def test_reality_ledger_preserves_before_and_after_confidence():
    m = M("4_reality_up_narrative_down")
    rc = m["reality_check"]
    assert "confidence_before" in rc and "confidence_after" in rc
    assert isinstance(rc["evidence_stack"], list)


# --------------------------------------------------------------------------
# Routing / strategy
# --------------------------------------------------------------------------
def test_shortest_route_fallacy_is_rejected():
    m = M("1_theme_only")
    assert m["primary_route"] == "ROUTE_TO_FOOD_CHAIN_ANALYSIS"
    assert m["strategy_eligibility"] != "STRATEGY_ALLOWED"


def test_growing_sector_routes_to_food_chain():
    m = M("1_theme_only")
    assert m["recommended_next_module"] == "food_chain"


def test_weak_layer_integrity_blocks_high_conviction():
    m = M("3_narrative_no_reality")
    assert m["layer_integrity_score"] < 0.4
    assert m["strategy_eligibility"] in {"REJECT_STRATEGY", "NEEDS_REALITY_CHECK", "WATCH_ONLY"}


def test_strategy_confidence_capped_by_layer_integrity():
    for fn in ALL_MYTHOS_CASES.values():
        m = run_mythos(fn())
        assert m["final_mythos_confidence"] <= m["layer_integrity_score"] + 1e-9


# --------------------------------------------------------------------------
# ETA / timing
# --------------------------------------------------------------------------
def test_eta_error_is_computed():
    m = M("5_eta_error")
    assert m["eta"]["eta_error"] is True
    assert m["eta"]["timing_quality"] == "ETA_MISSED"


def test_thesis_eta_range_includes_uncertainty():
    m = M("4_reality_up_narrative_down")
    eta = m["eta"]
    lo, hi = eta["thesis_eta_range"]
    assert lo <= eta["thesis_eta_days"] <= hi
    assert eta["uncertainty_buffer"] > 0


def test_missed_catalyst_reduces_confidence():
    m = M("5_eta_error")
    rc = m["reality_check"]
    assert rc["confidence_after"] < rc["confidence_before"]


# --------------------------------------------------------------------------
# Economic vs narrative map
# --------------------------------------------------------------------------
def test_narrative_buzz_without_reality_is_not_high_conviction():
    m = M("3_narrative_no_reality")
    assert m["divergence_type"] == "NARRATIVE_UP_REALITY_DOWN"
    assert m["strategy_eligibility"] != "STRATEGY_ALLOWED"
    routes = {r["route"] for r in m["routes"]}
    assert "ROUTE_TO_REALITY_CHECK" in routes


def test_reality_up_narrative_down_is_detected():
    m = M("4_reality_up_narrative_down")
    assert m["divergence_type"] == "REALITY_UP_NARRATIVE_DOWN"
    assert m["economic_reality_score"] > m["narrative_belief_score"]


def test_saturated_narrative_reduces_edge():
    base = dict(source="sec_filing", entity="S", demand=0.8, revenue_growth=0.8,
                margin_trend=0.8, retention=0.8, pricing_power=0.7, customer_adoption=0.7,
                attention=0.1)
    fresh = run_mythos(MythosObservation(**base, saturation=0.0))
    saturated = run_mythos(MythosObservation(**base, saturation=0.9))
    assert saturated["two_map"]["mispricing_edge"] < fresh["two_map"]["mispricing_edge"]


# --------------------------------------------------------------------------
# Casino x food-chain bridge
# --------------------------------------------------------------------------
def test_payload_can_feed_fable5():
    obs = ALL_MYTHOS_CASES["4_reality_up_narrative_down"]()
    dossier = build_fable5_dossier(obs)
    fable = score_opportunity(dossier)        # Fable's fraud gates apply unchanged
    assert "decision" in fable
    assert fable["segment_scores"]["final_opportunity"] <= fable["segment_scores"]["raw_merit_additive"] + 1e-9


def test_value_capture_role_present():
    m = M("6_food_chain_capture_failure")
    assert m["food_chain"]["value_capture_role"] in {
        "PREDATOR", "PREY", "HABITAT", "PARASITE_RISK", "UNDIFFERENTIATED"}
    assert m["food_chain"]["value_capture_role"] == "PREY"  # weak capture, high dependency


def test_odds_edge_and_confidence_cap_in_payload():
    m = M("4_reality_up_narrative_down")
    payload = m["mythos_to_fable5_payload"]
    assert "odds_edge" in payload
    assert payload["confidence_cap"] == m["layer_integrity_score"]


# --------------------------------------------------------------------------
# Invariants
# --------------------------------------------------------------------------
def test_raw_observation_is_not_treated_as_truth():
    # High prior, governed source, but no confirming evidence -> never
    # HIGH_CONFIDENCE on arrival.
    m = run_mythos(MythosObservation(
        source="sec_filing", entity="FRESH", raw_text="revenue up",
        confidence_prior=0.95, revenue_growth=0.9))
    assert m["claim_status"] in {"PROVISIONAL", "UNTESTED", "SUPPORTED"}
    assert m["claim_status"] != "HIGH_CONFIDENCE"


def test_interpretation_without_reality_check_is_provisional():
    m = M("2_revenue_ambiguity")
    assert m["claim_status"] in {"PROVISIONAL", "UNTESTED"}


def test_no_high_conviction_when_integrity_below_threshold():
    for key in ("3_narrative_no_reality", "5_eta_error"):
        m = M(key)
        assert m["strategy_eligibility"] in {"REJECT_STRATEGY", "NEEDS_REALITY_CHECK",
                                             "NEEDS_INTERPRETATION_CLARITY", "WATCH_ONLY"}


def test_mythos_is_deterministic():
    obs = ALL_MYTHOS_CASES["8_worldview_disagreement"]()
    a = json.dumps(run_mythos(obs), sort_keys=True, default=str)
    b = json.dumps(run_mythos(obs), sort_keys=True, default=str)
    assert a == b


def test_advisory_only_stamp_present():
    for fn in ALL_MYTHOS_CASES.values():
        m = run_mythos(fn())
        assert m["advisory_status"] == "ADVISORY_ONLY"
        assert m["real_money_execution"] == "PROHIBITED"
        assert m["broker_api_called"] is False


def test_all_cases_run_and_carry_core_fields():
    required = {"observation_quality_score", "governance_trust_score",
                "interpretation_confidence", "interpretation_gap_score",
                "reality_check_score", "economic_reality_score", "narrative_belief_score",
                "reality_narrative_divergence", "food_chain", "casino",
                "layer_integrity_score", "strategy_eligibility_score",
                "final_mythos_confidence", "mythos_to_fable5_payload"}
    for fn in ALL_MYTHOS_CASES.values():
        m = run_mythos(fn())
        assert required <= set(m)


# ==========================================================================
# Mythos -> Fable 5 pipeline + persistent reality-check ledger
# ==========================================================================
from scripts.signal_arbitrage.mythos_pipeline import run_pipeline
from scripts.signal_arbitrage.mythos_ledger import MythosLedgerStore, claim_id_for
from scripts.signal_arbitrage.strategist import strategize_signal


def P(key, **kw):
    return run_pipeline(ALL_MYTHOS_CASES[key](), **kw)


# ---- routing pre-filter ----
def test_pipeline_blocks_narrative_only_before_fable():
    r = P("3_narrative_no_reality")
    assert r["routed_to_fable"] is False
    assert r["pre_scoring_decision"] in {"REJECTED_PRE_SCORING", "ROUTE_TO_REALITY_CHECK"}
    assert r["fable"] is None


def test_pipeline_routes_reality_up_to_fable():
    r = P("4_reality_up_narrative_down")
    assert r["pre_scoring_decision"] == "ROUTE_TO_FABLE5"
    assert r["routed_to_fable"] is True
    assert r["fable"] is not None


def test_pipeline_theme_only_routes_to_food_chain_not_fable():
    r = P("1_theme_only")
    assert r["pre_scoring_decision"] == "ROUTE_TO_FOOD_CHAIN"
    assert r["routed_to_fable"] is False


def test_pipeline_stale_thesis_rejected_pre_scoring():
    r = P("5_eta_error")
    assert r["pre_scoring_decision"] == "REJECTED_PRE_SCORING"
    assert r["routed_to_fable"] is False


# ---- confidence cap ----
def test_confidence_cap_applied_to_fable_output():
    r = P("4_reality_up_narrative_down")
    cap = r["mythos_confidence_cap"]
    fable_conf = r["fable"]["fable_confidence_score"]
    assert r["capped_confidence"] == pytest.approx(min(fable_conf, cap), abs=1e-9)
    assert r["capped_confidence"] <= cap + 1e-9


# ---- fraud gates preserved ----
def test_fable_fraud_gates_unchanged_through_pipeline():
    from scripts.signal_arbitrage.mythos import build_fable5_dossier
    obs = ALL_MYTHOS_CASES["4_reality_up_narrative_down"]()
    direct = score_opportunity(build_fable5_dossier(obs))
    r = run_pipeline(obs)
    # Pipeline did not alter Fable's gated score, and the spine invariant holds.
    assert r["fable"]["investable_score"] == direct["segment_scores"]["final_opportunity"]
    assert direct["segment_scores"]["final_opportunity"] <= \
        direct["segment_scores"]["raw_merit_additive"] + 1e-9


def test_pipeline_is_advisory_and_deterministic():
    obs = ALL_MYTHOS_CASES["4_reality_up_narrative_down"]()
    a = run_pipeline(obs)
    b = run_pipeline(obs)
    assert a == b
    assert a["advisory_status"] == "ADVISORY_ONLY"
    assert a["real_money_execution"] == "PROHIBITED"
    assert a["broker_api_called"] is False


# ---- persistent ledger ----
def test_claim_persists_across_runs(tmp_path):
    path = tmp_path / "ledger.json"
    s1 = MythosLedgerStore(path)
    r = run_pipeline(ALL_MYTHOS_CASES["4_reality_up_narrative_down"](), ledger=s1)
    s1.save()
    cid = r["ledger"]["claim_id"]
    # New store instance loads the persisted claim from disk.
    s2 = MythosLedgerStore(path)
    assert s2.get(cid) is not None
    assert s2.get(cid).chain_valid() is True


def test_confirming_evidence_increases_trust_in_ledger(tmp_path):
    s = MythosLedgerStore(tmp_path / "l.json")
    rec = s.upsert_claim(entity="CO", claim="retention improving",
                         interpretation="BULLISH", governance="OFFICIAL_SOURCE",
                         prior_confidence=0.5, day=0)
    before = rec.confidence
    s.apply_evidence(rec.claim_id, day=10, supports=True, weight=0.8, independent=0.8)
    assert s.get(rec.claim_id).confidence > before
    assert s.get(rec.claim_id).survival_count == 1
    assert s.get(rec.claim_id).status == "SUPPORTED"


def test_contradicting_evidence_reduces_trust_in_ledger(tmp_path):
    s = MythosLedgerStore(tmp_path / "l.json")
    rec = s.upsert_claim(entity="CO", claim="retention improving",
                         interpretation="BULLISH", governance="OFFICIAL_SOURCE",
                         prior_confidence=0.5, day=0)
    before = rec.confidence
    s.apply_evidence(rec.claim_id, day=10, supports=False, weight=0.8, independent=0.8)
    assert s.get(rec.claim_id).confidence < before
    assert s.get(rec.claim_id).contradiction_count == 1


def test_three_confirmations_reach_high_confidence(tmp_path):
    s = MythosLedgerStore(tmp_path / "l.json")
    rec = s.upsert_claim(entity="CO", claim="c", interpretation="BULLISH",
                         governance="OFFICIAL_SOURCE", prior_confidence=0.5, day=0)
    for d in (10, 20, 30):
        s.apply_evidence(rec.claim_id, day=d, supports=True, weight=0.7, independent=0.7)
    assert s.get(rec.claim_id).status == "HIGH_CONFIDENCE"


def test_confirm_then_contradict_is_contested(tmp_path):
    s = MythosLedgerStore(tmp_path / "l.json")
    rec = s.upsert_claim(entity="CO", claim="c", interpretation="BULLISH",
                         governance="OFFICIAL_SOURCE", prior_confidence=0.5, day=0)
    s.apply_evidence(rec.claim_id, day=10, supports=True, weight=0.7, independent=0.7)
    s.apply_evidence(rec.claim_id, day=20, supports=False, weight=0.7, independent=0.7)
    assert s.get(rec.claim_id).status == "CONTESTED"


def test_missed_validation_window_marks_stale(tmp_path):
    s = MythosLedgerStore(tmp_path / "l.json")
    rec = s.upsert_claim(entity="CO", claim="c", interpretation="BULLISH",
                         governance="OPEN_COMMUNITY", prior_confidence=0.5, day=0,
                         validation_window=30)
    changed = s.check_windows(current_day=100)   # well past the 30-day window
    assert rec.claim_id in {c.claim_id for c in changed}
    assert s.get(rec.claim_id).status in {"STALE", "CONTESTED"}


def test_cross_run_trust_accumulates_and_persists(tmp_path):
    path = tmp_path / "ledger.json"
    # Run 1: create claim, persist.
    s1 = MythosLedgerStore(path)
    r = run_pipeline(ALL_MYTHOS_CASES["4_reality_up_narrative_down"](), ledger=s1)
    cid = r["ledger"]["claim_id"]
    s1.save()
    # Run 2: a new reality check arrives; apply + persist.
    s2 = MythosLedgerStore(path)
    before = s2.get(cid).confidence
    s2.apply_evidence(cid, day=15, supports=True, weight=0.8, independent=0.8)
    s2.save()
    # Run 3: a fresh instance sees the accumulated trust and status.
    s3 = MythosLedgerStore(path)
    assert s3.get(cid).confidence > before
    assert s3.get(cid).survival_count == 1
    assert s3.get(cid).status == "SUPPORTED"
    assert s3.get(cid).chain_valid() is True


def test_ledger_chain_detects_tamper(tmp_path):
    s = MythosLedgerStore(tmp_path / "l.json")
    rec = s.upsert_claim(entity="CO", claim="c", interpretation="BULLISH",
                         governance="OFFICIAL_SOURCE", prior_confidence=0.5, day=0)
    assert rec.chain_valid() is True
    # Tamper with a stored event input -> replayed chain no longer matches a
    # later recompute against the original head.
    good_head = rec.head_hash()
    rec.events[0]["detail"]["interpretation"] = "BEARISH"
    assert rec.head_hash() != good_head


# ==========================================================================
# Richer Mythos -> Fable translation + calibration readiness
# ==========================================================================
from scripts.signal_arbitrage.mythos import (
    build_fable5_dossier, validation_window_for,
)
from scripts.signal_arbitrage.opportunity import SignalDossier
from scripts.signal_arbitrage.platform_ecology import PLATFORM_PROFILES, classify_platform
from scripts.signal_arbitrage.mythos_calibration import (
    run_calibration, real_corpus_readiness,
)


def _legacy_lossy_dossier(obs) -> SignalDossier:
    """The pre-sprint mapping, reconstructed for before/after comparison."""
    return SignalDossier(
        signal_id="legacy", text=obs.raw_text, platforms=[obs.source.lower()],
        conversion_strength=obs.customer_adoption or 0.0,
        retention_strength=obs.retention or 0.0,
        business_confirmation=obs.demand or 0.0,
        financial_confirmation=obs.margin_trend or 0.0,
        price_recognition=obs.consensus, crowding=obs.saturation, age_days=0.0)


def test_translation_preserves_platform_ecology():
    # An official-source signal maps to a REAL ecology, not "unknown".
    official = build_fable5_dossier(ALL_MYTHOS_CASES["4_reality_up_narrative_down"]())
    assert official.platforms[0] in PLATFORM_PROFILES
    assert official.platforms[0] != "sec_filing"
    assert classify_platform(official.platforms[0]).confidence > 0.3
    # A reddit source maps to the reddit ecology.
    community = build_fable5_dossier(ALL_MYTHOS_CASES["7_open_vs_closed_governance"]())
    assert community.platforms[0] == "reddit"


def test_reality_up_scores_higher_after_richer_translation():
    obs = ALL_MYTHOS_CASES["4_reality_up_narrative_down"]()
    old = score_opportunity(_legacy_lossy_dossier(obs))["segment_scores"]["final_opportunity"]
    new = score_opportunity(build_fable5_dossier(obs))["segment_scores"]["final_opportunity"]
    assert new > old


def test_perception_dependent_signal_fails_fable_purity_gate():
    # If a narrative-only signal were forced through Fable, the divergence-driven
    # blind score must collapse its purity -> never a Buy.
    obs = ALL_MYTHOS_CASES["3_narrative_no_reality"]()
    rep = score_opportunity(build_fable5_dossier(obs))
    assert rep["segment_scores"]["reality_purity"] < 0.4
    assert rep["decision"] not in {"BUY", "LONG_TERM_COMPOUNDER"}


def test_fable_final_le_raw_merit_for_all_translations():
    for fn in ALL_MYTHOS_CASES.values():
        rep = score_opportunity(build_fable5_dossier(fn()))
        ss = rep["segment_scores"]
        assert ss["final_opportunity"] <= ss["raw_merit_additive"] + 1e-9


def test_translation_is_deterministic():
    obs = ALL_MYTHOS_CASES["4_reality_up_narrative_down"]()
    assert build_fable5_dossier(obs) == build_fable5_dossier(obs)


def test_validation_windows_differ_by_claim_type():
    assert validation_window_for("narrative_buzz") < validation_window_for("theme_sector")
    assert validation_window_for("retention_up") != validation_window_for("generic")


def test_pipeline_uses_claim_type_window(tmp_path):
    led = MythosLedgerStore(tmp_path / "l.json")
    run_pipeline(ALL_MYTHOS_CASES["3_narrative_no_reality"](), ledger=led)   # narrative_buzz
    run_pipeline(ALL_MYTHOS_CASES["1_theme_only"](), ledger=led)            # theme_sector
    claims = {c.claim_id: c for c in led.all_claims()}
    narr = next(c for c in claims.values() if c.entity == "HYPE_AI")
    theme = next(c for c in claims.values() if c.entity == "GENERIC_AI_NAME")
    assert (narr.expected_check_day - narr.first_seen_day) == 14
    assert (theme.expected_check_day - theme.first_seen_day) == 90


def test_event_id_prevents_double_counting(tmp_path):
    s = MythosLedgerStore(tmp_path / "l.json")
    rec = s.upsert_claim(entity="CO", claim="c", interpretation="BULLISH",
                         governance="OFFICIAL_SOURCE", prior_confidence=0.5, day=0)
    s.apply_evidence(rec.claim_id, day=10, supports=True, weight=0.8,
                     independent=0.8, event_id="evt-1")
    conf_after_first = s.get(rec.claim_id).confidence
    # Re-applying the SAME event id is a no-op (rerun-safe).
    s.apply_evidence(rec.claim_id, day=10, supports=True, weight=0.8,
                     independent=0.8, event_id="evt-1")
    assert s.get(rec.claim_id).survival_count == 1
    assert s.get(rec.claim_id).confidence == conf_after_first
    # A genuinely new event id still applies.
    s.apply_evidence(rec.claim_id, day=20, supports=True, weight=0.8,
                     independent=0.8, event_id="evt-2")
    assert s.get(rec.claim_id).survival_count == 2


def test_calibration_separates_winners_from_losers_provisional():
    c = run_calibration()
    assert c["status"] == "PROVISIONAL"
    assert c["corpus"] == "PROVISIONAL_MINI_CORPUS"
    assert c["clean_rank_separation"] is True
    assert c["separation"] > 0
    assert c["winners_routed_to_fable"] is True
    assert c["losers_blocked_before_fable"] is True
    assert c["advisory_status"] == "ADVISORY_ONLY"


def test_real_corpus_is_insufficient_evidence():
    r = real_corpus_readiness()
    assert r["status"] == "INSUFFICIENT_EVIDENCE"
    assert r["calibratable_records"] == 0
    assert r["features_available_in_corpus"] is False


def test_calibration_is_deterministic():
    assert run_calibration() == run_calibration()


# ==========================================================================
# Multi-observation aggregator
# ==========================================================================
from scripts.signal_arbitrage.mythos_aggregator import (
    aggregate_cluster, run_aggregated_pipeline, dedup_observations,
)
from scripts.signal_arbitrage.mythos_calibration import run_aggregation_calibration
from scripts.signal_arbitrage.mythos_fixtures import (
    single_source_reality_baseline, multi_source_reality_cluster,
    same_source_spam_cluster, social_only_cluster,
)


def _inv(dossier):
    return score_opportunity(dossier)["segment_scores"]["final_opportunity"]


def test_multiple_independent_sources_increase_migration():
    single = build_fable5_dossier(single_source_reality_baseline())
    agg = aggregate_cluster(multi_source_reality_cluster())
    single_roles = score_opportunity(single)["platform_ecology"]["distinct_roles"]
    multi_roles = score_opportunity(agg.dossier)["platform_ecology"]["distinct_roles"]
    assert agg.n_distinct_ecologies == 3
    assert multi_roles > single_roles
    # Vitality transfers further once migration clears.
    assert score_opportunity(agg.dossier)["segment_scores"]["vitality"] > \
        score_opportunity(single)["segment_scores"]["vitality"]


def test_repeated_same_source_does_not_fake_migration():
    agg = aggregate_cluster(same_source_spam_cluster())
    assert agg.distinct_ecologies == ["reddit"]
    assert agg.n_distinct_ecologies == 1
    assert agg.corroboration == 0.0
    # Three posts were ingested but they are one ecology.
    assert agg.n_observations == 3


def test_dedup_collapses_exact_duplicates():
    one = single_source_reality_baseline()
    assert len(dedup_observations([one, one, one])) == 1


def test_multi_source_scores_higher_than_single_source():
    single_inv = _inv(build_fable5_dossier(single_source_reality_baseline()))
    multi_inv = _inv(aggregate_cluster(multi_source_reality_cluster()).dossier)
    assert multi_inv > single_inv


def test_narrative_only_cluster_remains_blocked():
    r = run_aggregated_pipeline(social_only_cluster())
    assert r["routed_to_fable"] is False
    agg = aggregate_cluster(social_only_cluster())
    rep = score_opportunity(agg.dossier)
    assert rep["segment_scores"]["reality_purity"] < 0.4
    assert rep["decision"] not in {"BUY", "LONG_TERM_COMPOUNDER"}


def test_fake_cluster_cannot_become_buy():
    agg = aggregate_cluster(social_only_cluster())
    rep = score_opportunity(agg.dossier)
    assert rep["decision"] not in {"BUY", "LONG_TERM_COMPOUNDER"}
    assert rep["segment_scores"]["final_opportunity"] <= 0.1


def test_confidence_cap_enforced_in_aggregation():
    r = run_aggregated_pipeline(multi_source_reality_cluster())
    assert r["routed_to_fable"] is True
    cap = r["mythos_confidence_cap"]
    fable_conf = r["fable"]["fable_confidence_score"]
    assert r["capped_confidence"] == pytest.approx(min(fable_conf, cap), abs=1e-9)
    assert r["capped_confidence"] <= cap + 1e-9


def test_aggregated_final_le_raw_merit():
    for cluster in (multi_source_reality_cluster(), same_source_spam_cluster(),
                    social_only_cluster(), [single_source_reality_baseline()]):
        ss = score_opportunity(aggregate_cluster(cluster).dossier)["segment_scores"]
        assert ss["final_opportunity"] <= ss["raw_merit_additive"] + 1e-9


def test_event_dedup_prevents_double_count_in_aggregated_ledger(tmp_path):
    path = tmp_path / "agg.json"
    led = MythosLedgerStore(path)
    r1 = run_aggregated_pipeline(multi_source_reality_cluster(), ledger=led)
    s1 = r1["ledger"]["survival_count"]
    # Re-run the same cluster: event ids (source:day) already applied -> no double count.
    r2 = run_aggregated_pipeline(multi_source_reality_cluster(), ledger=led)
    assert r2["ledger"]["survival_count"] == s1
    assert led.get(r1["ledger"]["claim_id"]).chain_valid() is True


def test_aggregation_is_deterministic():
    a = aggregate_cluster(multi_source_reality_cluster()).to_dict()
    b = aggregate_cluster(multi_source_reality_cluster()).to_dict()
    assert a == b
    assert run_aggregated_pipeline(multi_source_reality_cluster()) == \
        run_aggregated_pipeline(multi_source_reality_cluster())


def test_aggregation_calibration_separates_and_is_provisional():
    c = run_aggregation_calibration()
    assert c["status"] == "PROVISIONAL"
    assert c["clean_rank_separation"] is True
    assert c["separation"] > 0
    # corroborated multi-source winner out-ranks the single-source winner
    multi = next(r for r in c["rows"] if r["n_distinct_ecologies"] == 3)
    singles = [r for r in c["rows"] if r["outcome"] >= 0.5 and r["n_distinct_ecologies"] == 1]
    assert all(multi["strength"] >= s["strength"] for s in singles)


# ==========================================================================
# Real corpus backfill + live calibration engine
# ==========================================================================
import json as _json
from dataclasses import replace as _replace
from scripts.signal_arbitrage.mythos_corpus import (
    SCHEMA, build_calibration_record, backfill_calibration_records,
    run_real_calibration, real_corpus_backfill_readiness, prediction_score,
    IMPORTED_BACKTEST, SYNTHETIC_FIXTURE, INCONCLUSIVE, WIN, LOSS,
)


def _make_records(n):
    """Deterministic IMPORTED_BACKTEST records exercising the calibration ladder
    (test fixtures validating threshold/metric LOGIC, not real outcomes)."""
    out = []
    for i in range(n):
        if i % 2 == 0:
            out.append(build_calibration_record(
                cluster=multi_source_reality_cluster(), record_id=f"w{i}", ticker=f"T{i}",
                source_type=IMPORTED_BACKTEST, realized_return=0.10, horizon_days=30))
        else:
            out.append(build_calibration_record(
                cluster=social_only_cluster(), record_id=f"l{i}", ticker=f"T{i}",
                source_type=IMPORTED_BACKTEST, realized_return=-0.08, horizon_days=30))
    return out


# ---- schema ----
def test_calibration_record_has_all_schema_fields():
    rec = build_calibration_record(cluster=multi_source_reality_cluster(),
                                   record_id="r1", ticker="MULTI",
                                   source_type=IMPORTED_BACKTEST, realized_return=0.12)
    for group, keys in SCHEMA.items():
        present = getattr(rec, group)
        assert all(k in present for k in keys), (group, [k for k in keys if k not in present])


def test_unknown_outcome_becomes_inconclusive_not_guessed():
    rec = build_calibration_record(cluster=multi_source_reality_cluster(),
                                   record_id="r2", ticker="MULTI",
                                   source_type=IMPORTED_BACKTEST, realized_return=None)
    assert rec.outcome["outcome_label"] == INCONCLUSIVE
    assert rec.calibratable is False


def test_outcome_label_derived_from_return():
    win = build_calibration_record(cluster=multi_source_reality_cluster(), record_id="w",
                                   ticker="T", source_type=IMPORTED_BACKTEST, realized_return=0.2)
    loss = build_calibration_record(cluster=multi_source_reality_cluster(), record_id="l",
                                    ticker="T", source_type=IMPORTED_BACKTEST, realized_return=-0.2)
    assert win.outcome["outcome_label"] == WIN
    assert loss.outcome["outcome_label"] == LOSS


# ---- backfill pipeline ----
def _write_corpus(tmp_path, source_type=IMPORTED_BACKTEST, realized_return=0.1):
    obs = [
        {"source": "sec_filing", "entity": "BFCO", "claim_type": "retention_up",
         "raw_text": "retention and margins improved", "demand": 0.6, "margin_trend": 0.8,
         "retention": 0.85, "customer_adoption": 0.7, "sentiment": 0.3, "consensus": 0.3},
        {"source": "reddit", "entity": "BFCO", "claim_type": "retention_up",
         "raw_text": "switched and stayed, retention strong", "retention": 0.75,
         "customer_adoption": 0.65, "day": 1, "sentiment": 0.6},
        {"source": "web_traffic", "entity": "BFCO", "claim_type": "retention_up",
         "raw_text": "returning user traffic climbing", "demand": 0.7,
         "customer_adoption": 0.68, "day": 2},
    ]
    corpus = {"records": [{"record_id": "bf1", "entity": "BFCO", "ticker": "BFCO",
                           "claim": "retention improving", "claim_type": "retention_up",
                           "source_type": source_type, "realized_return": realized_return,
                           "horizon_days": 30, "observations": obs}]}
    path = tmp_path / "corpus.json"
    path.write_text(_json.dumps(corpus), encoding="utf-8")
    return path


def test_backfill_dry_run_does_not_write(tmp_path):
    src = _write_corpus(tmp_path)
    out = tmp_path / "out.jsonl"
    rep = backfill_calibration_records([str(src)], output_path=str(out), mode="dry_run")
    assert rep.output_path is None
    assert not out.exists()


def test_backfill_write_mode_is_deterministic(tmp_path):
    src = _write_corpus(tmp_path)
    out = tmp_path / "out.jsonl"
    backfill_calibration_records([str(src)], output_path=str(out), mode="write")
    first = out.read_text(encoding="utf-8")
    backfill_calibration_records([str(src)], output_path=str(out), mode="write")
    assert out.read_text(encoding="utf-8") == first
    assert out.exists()


def test_missing_corpus_returns_no_corpus_found(tmp_path):
    rep = backfill_calibration_records([str(tmp_path / "nope.json")], mode="dry_run")
    assert rep.status == "NO_CORPUS_FOUND"


def test_closed_positions_is_insufficient_not_fabricated():
    rep = backfill_calibration_records(
        ["data/daily_payload/closed_positions.json"], mode="dry_run")
    assert rep.feature_bearing == 0
    assert rep.inconclusive >= 1
    assert rep.status in {"INSUFFICIENT_EVIDENCE", "PARTIAL_BACKFILL"}


def test_feature_bearing_resolved_record_is_calibratable(tmp_path):
    src = _write_corpus(tmp_path, source_type=IMPORTED_BACKTEST, realized_return=0.1)
    rep = backfill_calibration_records([str(src)], mode="dry_run")
    assert rep.feature_bearing == 1
    assert rep.calibratable == 1


def test_synthetic_fixture_is_not_calibration_eligible(tmp_path):
    src = _write_corpus(tmp_path, source_type=SYNTHETIC_FIXTURE, realized_return=0.1)
    rep = backfill_calibration_records([str(src)], mode="dry_run")
    assert rep.feature_bearing == 1
    assert rep.calibratable == 0   # synthetic never counts


def test_backfill_duplicate_evidence_not_double_counted():
    base = single_source_reality_baseline()
    rec = build_calibration_record(cluster=[base, base, base], record_id="dup",
                                   ticker="DUP", source_type=IMPORTED_BACKTEST,
                                   realized_return=0.05)
    assert rec.aggregation["same_source_duplicate_count"] == 2
    assert rec.aggregation["n_distinct_ecologies"] == 1


def test_directional_disagreement_reduces_adjusted_corroboration():
    agree = multi_source_reality_cluster()
    # Flip the youtube source to narrative-up (same ecology, opposite direction).
    flipped = _replace(agree[2], demand=None, revenue_growth=None, margin_trend=None,
                       retention=None, customer_adoption=None, attention=0.9,
                       mentions_velocity=0.9, sentiment=0.9, amplification=0.8)
    disagree = [agree[0], agree[1], flipped]
    a = build_calibration_record(cluster=agree, record_id="a", ticker="A",
                                 source_type=IMPORTED_BACKTEST, realized_return=0.1)
    d = build_calibration_record(cluster=disagree, record_id="d", ticker="D",
                                 source_type=IMPORTED_BACKTEST, realized_return=0.1)
    assert d.aggregation["directional_agreement_score"] < a.aggregation["directional_agreement_score"]
    assert d.aggregation["corroboration_score"] < a.aggregation["corroboration_score"]


# ---- real calibration runner ----
def test_calibration_refuses_below_minimum():
    rep = run_real_calibration(records=_make_records(8))
    assert rep["status"] == "INSUFFICIENT_EVIDENCE"
    assert rep["weights_fitted"] is False
    assert rep["records_needed"] == 2


def test_calibration_provisional_at_ten():
    rep = run_real_calibration(records=_make_records(12))
    assert rep["status"] == "PROVISIONAL_DIAGNOSTIC"
    for k in ("separation", "auc_rank_separation", "trap_precision", "trap_recall",
              "action_accuracy", "brier_score", "ece"):
        assert rep[k] is not None


def test_calibration_first_pass_at_thirty():
    rep = run_real_calibration(records=_make_records(30))
    assert rep["status"] == "FIRST_PASS_CALIBRATION"


def test_calibration_is_deterministic():
    assert run_real_calibration(records=_make_records(12)) == \
        run_real_calibration(records=_make_records(12))


def test_no_weight_changes_on_insufficient_evidence():
    rep = real_corpus_backfill_readiness()
    assert rep["calibration"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert rep["calibration"]["weight_change_status"] == "NO_WEIGHT_CHANGES_INSUFFICIENT_EVIDENCE"
    assert rep["calibration"]["weights_fitted"] is False


# ---- invariants ----
def test_record_fable_final_le_raw_merit():
    for rec in _make_records(6):
        if rec.fable:
            assert rec.fable["final_opportunity_score"] <= rec.fable["raw_merit"] + 1e-9


def test_fake_cluster_record_is_not_a_buy():
    rec = build_calibration_record(cluster=social_only_cluster(), record_id="fake",
                                   ticker="FAKE", source_type=IMPORTED_BACKTEST,
                                   realized_return=-0.1)
    assert rec.fable["reality_purity"] < 0.4
    assert rec.fable["decision"] not in {"BUY", "LONG_TERM_COMPOUNDER"}


def test_corpus_reports_are_advisory_only():
    rep = real_corpus_backfill_readiness()
    assert rep["advisory_status"] == "ADVISORY_ONLY"
    assert rep["calibration"]["advisory_status"] == "ADVISORY_ONLY"


def test_prediction_score_is_fraud_gated():
    # A perception-dependent (purity 0) record cannot score as a likely win.
    fake = build_calibration_record(cluster=social_only_cluster(), record_id="f",
                                    ticker="F", source_type=IMPORTED_BACKTEST,
                                    realized_return=-0.1)
    real = build_calibration_record(cluster=multi_source_reality_cluster(), record_id="r",
                                    ticker="R", source_type=IMPORTED_BACKTEST,
                                    realized_return=0.1)
    assert prediction_score(fake) < prediction_score(real)
    assert prediction_score(fake) <= 0.05


# ==========================================================================
# Forward-logging decision capture + outcome resolution
# ==========================================================================
from scripts.signal_arbitrage.mythos_capture import (
    capture_decision_snapshot, resolve_decision_outcome, decision_id_for,
    derive_outcome_label, SCHEMA_VERSION, OPEN_OR_UNRESOLVED,
)
from scripts.signal_arbitrage.mythos_corpus import PAPER_TRADE


def _entity_cluster(i):
    return [_replace(o, entity=f"CO{i}") for o in multi_source_reality_cluster()]


def _forward_corpus(tmp_path, n):
    """Capture + resolve n distinct clusters into a JSONL corpus (WIN/LOSS mix)."""
    path = tmp_path / "decisions.jsonl"
    for i in range(n):
        rep = capture_decision_snapshot(_entity_cluster(i), output_path=str(path),
                                        mode="write", source_type=PAPER_TRADE)
        ret = 0.1 if i % 2 == 0 else -0.1
        resolve_decision_outcome(str(path), rep.decision_id, {"realized_return": ret},
                                 mode="write")
    return path


# ---- decision capture ----
def test_capture_dry_run_does_not_write(tmp_path):
    path = tmp_path / "d.jsonl"
    rep = capture_decision_snapshot(multi_source_reality_cluster(),
                                    output_path=str(path), mode="dry_run")
    assert rep.status == "CAPTURED_DRY_RUN"
    assert rep.written is False
    assert not path.exists()


def test_capture_write_is_deterministic_snapshot():
    a = capture_decision_snapshot(multi_source_reality_cluster()).snapshot
    b = capture_decision_snapshot(multi_source_reality_cluster()).snapshot
    assert a == b


def test_same_cluster_same_decision_id_new_cluster_differs():
    assert decision_id_for(multi_source_reality_cluster()) == \
        decision_id_for(multi_source_reality_cluster())
    assert decision_id_for([single_source_reality_baseline()]) != \
        decision_id_for(multi_source_reality_cluster())


def test_duplicate_decision_id_not_appended_twice(tmp_path):
    path = tmp_path / "d.jsonl"
    r1 = capture_decision_snapshot(multi_source_reality_cluster(), output_path=str(path),
                                   mode="write")
    r2 = capture_decision_snapshot(multi_source_reality_cluster(), output_path=str(path),
                                   mode="write")
    assert r1.status == "CAPTURED_WRITTEN"
    assert r2.status == "DUPLICATE_SKIPPED"
    assert len([l for l in path.read_text().splitlines() if l.strip()]) == 1


def test_snapshot_contains_all_schema_groups():
    s = capture_decision_snapshot(multi_source_reality_cluster()).snapshot
    for group, keys in SCHEMA.items():
        assert all(k in s.get(group, {}) for k in keys), group
    # forward-logging-specific groups
    assert "metadata" in s and "source_observation" in s
    assert s["schema_version"] == SCHEMA_VERSION
    assert s["outcome"]["final_outcome_status"] == OPEN_OR_UNRESOLVED


def test_snapshot_is_advisory_only_and_prohibits_real_money():
    s = capture_decision_snapshot(multi_source_reality_cluster()).snapshot
    assert s["metadata"]["advisory_status"] == "ADVISORY_ONLY"
    assert s["metadata"]["real_money_execution"] == "PROHIBITED"


# ---- routed / blocked ----
def test_reality_up_routes_and_captures_fable_features():
    rep = capture_decision_snapshot(multi_source_reality_cluster())
    assert rep.routed_to_fable is True
    assert rep.pre_scoring_decision == "ROUTE_TO_FABLE5"
    assert rep.snapshot["fable"].get("investable_score") is not None


def test_narrative_only_blocked_but_still_feature_bearing():
    rep = capture_decision_snapshot(social_only_cluster())
    assert rep.routed_to_fable is False
    s = rep.snapshot
    assert s["feature_bearing"] is True
    assert s["mythos"]["economic_reality_score"] is not None
    assert s["fable"]["block_reason"] == rep.pre_scoring_decision


def test_same_source_spam_snapshot_has_no_fake_migration():
    s = capture_decision_snapshot(same_source_spam_cluster()).snapshot
    assert s["aggregation"]["n_distinct_ecologies"] == 1
    assert s["aggregation"]["corroboration_adjusted"] == 0.0


def test_social_only_snapshot_is_not_a_buy():
    s = capture_decision_snapshot(social_only_cluster()).snapshot
    assert s["fable"].get("reality_purity", 0.0) < 0.4
    assert s["fable"].get("decision") not in {"BUY", "LONG_TERM_COMPOUNDER"}


# ---- invariants ----
def test_captured_fable_final_le_raw_merit():
    s = capture_decision_snapshot(multi_source_reality_cluster()).snapshot
    f = s["fable"]
    assert f["final_opportunity_score"] <= f["raw_merit"] + 1e-9


def test_captured_confidence_le_cap():
    s = capture_decision_snapshot(multi_source_reality_cluster()).snapshot
    assert s["captured_confidence"] is not None
    assert s["captured_confidence"] <= s["mythos_confidence_cap"] + 1e-9


# ---- outcome resolution ----
def test_unresolved_snapshot_is_inconclusive():
    s = capture_decision_snapshot(multi_source_reality_cluster()).snapshot
    assert s["outcome"]["outcome_label"] == "INCONCLUSIVE"
    assert s["calibratable"] is False


def test_positive_return_resolves_win(tmp_path):
    path = tmp_path / "d.jsonl"
    r = capture_decision_snapshot(multi_source_reality_cluster(), output_path=str(path),
                                  mode="write")
    res = resolve_decision_outcome(str(path), r.decision_id, {"realized_return": 0.12},
                                   mode="write")
    assert res.new_label == "WIN"
    assert res.calibration_eligible is True


def test_negative_return_engaged_resolves_loss(tmp_path):
    path = tmp_path / "d.jsonl"
    r = capture_decision_snapshot(multi_source_reality_cluster(), output_path=str(path),
                                  mode="write")
    res = resolve_decision_outcome(str(path), r.decision_id, {"realized_return": -0.1},
                                   mode="write")
    assert res.new_label == "LOSS"


def test_avoided_trap_resolution():
    snap = capture_decision_snapshot(social_only_cluster()).snapshot
    assert snap["routed_to_fable"] is False
    assert derive_outcome_label(snap, {"realized_return": -0.1}) == "AVOIDED_TRAP"


def test_missed_winner_resolution():
    snap = capture_decision_snapshot(social_only_cluster()).snapshot
    assert derive_outcome_label(snap, {"realized_return": 0.1}) == "MISSED_WINNER"


def test_unknown_return_stays_inconclusive():
    snap = capture_decision_snapshot(multi_source_reality_cluster()).snapshot
    assert derive_outcome_label(snap, {"realized_return": None}) == "INCONCLUSIVE"


def test_conflicting_resolution_rejected_unless_allowed(tmp_path):
    path = tmp_path / "d.jsonl"
    r = capture_decision_snapshot(multi_source_reality_cluster(), output_path=str(path),
                                  mode="write")
    resolve_decision_outcome(str(path), r.decision_id, {"realized_return": 0.1}, mode="write")
    conflict = resolve_decision_outcome(str(path), r.decision_id, {"realized_return": -0.1},
                                        mode="write")
    assert conflict.status == "CONFLICT_REJECTED"
    allowed = resolve_decision_outcome(str(path), r.decision_id, {"realized_return": -0.1},
                                       mode="write", allow_conflict=True)
    assert allowed.status == "RESOLVED"
    assert len(allowed.audit) >= 2   # audit trail preserved across resolutions


def test_resolution_dry_run_does_not_write(tmp_path):
    path = tmp_path / "d.jsonl"
    r = capture_decision_snapshot(multi_source_reality_cluster(), output_path=str(path),
                                  mode="write")
    before = path.read_text()
    res = resolve_decision_outcome(str(path), r.decision_id, {"realized_return": 0.1},
                                   mode="dry_run")
    assert res.status == "RESOLUTION_DRY_RUN"
    assert res.written is False
    assert path.read_text() == before


def test_resolve_missing_decision():
    res = resolve_decision_outcome("nonexistent.jsonl", "dec-x", {"realized_return": 0.1})
    assert res.status == "DECISION_NOT_FOUND"


# ---- calibration integration ----
def test_unresolved_snapshots_excluded_from_calibration(tmp_path):
    path = tmp_path / "d.jsonl"
    for i in range(12):
        capture_decision_snapshot(_entity_cluster(i), output_path=str(path), mode="write")
    rep = run_real_calibration(records_path=str(path))
    assert rep["status"] == "INSUFFICIENT_EVIDENCE"   # all INCONCLUSIVE


def test_resolved_forward_log_consumed_by_calibration(tmp_path):
    path = _forward_corpus(tmp_path, 12)
    rep = run_real_calibration(records_path=str(path))
    assert rep["status"] == "PROVISIONAL_DIAGNOSTIC"
    assert rep["separation"] is not None
    assert rep["action_accuracy"] is not None


def test_calibration_refuses_below_threshold_on_forward_log(tmp_path):
    path = _forward_corpus(tmp_path, 6)
    rep = run_real_calibration(records_path=str(path))
    assert rep["status"] == "INSUFFICIENT_EVIDENCE"
    assert rep["weights_fitted"] is False


def test_synthetic_capture_remains_calibration_ineligible(tmp_path):
    path = tmp_path / "d.jsonl"
    r = capture_decision_snapshot(multi_source_reality_cluster(), output_path=str(path),
                                  mode="write", source_type=SYNTHETIC_FIXTURE)
    res = resolve_decision_outcome(str(path), r.decision_id, {"realized_return": 0.2},
                                   mode="write")
    assert res.new_label == "WIN"
    assert res.calibration_eligible is False   # synthetic never eligible


def test_forward_corpus_is_deterministic(tmp_path):
    p1 = _forward_corpus(tmp_path / "a", 4)
    p2 = _forward_corpus(tmp_path / "b", 4)
    assert p1.read_text() == p2.read_text()


# ==========================================================================
# Advisory runner: opt-in forward decision capture
# ==========================================================================
from scripts.signal_arbitrage.advisory_runner import (
    run_advisory_with_capture, resolve_capture_config, CaptureConfig, CaptureError,
    check_decision_capture_corpus,
)
from scripts.signal_arbitrage.mythos_aggregator import run_aggregated_pipeline

_DISABLED = CaptureConfig(enabled=False)


def _enabled(path, **kw):
    return CaptureConfig(enabled=True, path=str(path), write=True, **kw)


def _boom(*a, **k):
    raise RuntimeError("disk full")


# ---- capture flag behavior ----
def test_default_run_does_not_write(tmp_path):
    path = tmp_path / "d.jsonl"
    r = run_advisory_with_capture(multi_source_reality_cluster(),
                                  capture=CaptureConfig(enabled=False, path=str(path)))
    assert r["capture_status"] == "CAPTURE_DISABLED"
    assert not path.exists()


def test_explicit_flag_writes_one_snapshot(tmp_path):
    path = tmp_path / "d.jsonl"
    r = run_advisory_with_capture(multi_source_reality_cluster(), capture=_enabled(path),
                                  run_id="run1", decision_date=1)
    assert r["capture_status"] == "CAPTURE_WRITTEN"
    assert len([l for l in path.read_text().splitlines() if l.strip()]) == 1


def test_rerun_same_evidence_skips_duplicate(tmp_path):
    path = tmp_path / "d.jsonl"
    run_advisory_with_capture(multi_source_reality_cluster(), capture=_enabled(path))
    r2 = run_advisory_with_capture(multi_source_reality_cluster(), capture=_enabled(path))
    assert r2["capture_status"] == "DUPLICATE_SKIPPED"
    assert len([l for l in path.read_text().splitlines() if l.strip()]) == 1


def test_custom_capture_path_works(tmp_path):
    path = tmp_path / "nested" / "custom.jsonl"
    r = run_advisory_with_capture(multi_source_reality_cluster(), capture=_enabled(path))
    assert r["capture_status"] == "CAPTURE_WRITTEN"
    assert path.exists()


def test_disabled_capture_returns_capture_disabled():
    r = run_advisory_with_capture(multi_source_reality_cluster(), capture=_DISABLED)
    assert r["capture_status"] == "CAPTURE_DISABLED"
    assert r["capture"] is None


def test_env_resolves_capture_config():
    on = resolve_capture_config(env={"SIGNAL_CAPTURE_DECISIONS": "1",
                                     "SIGNAL_CAPTURE_PATH": "x.jsonl",
                                     "SIGNAL_CAPTURE_STRICT": "1"})
    assert on.enabled and on.path == "x.jsonl" and on.strict
    assert resolve_capture_config(env={}).enabled is False


def test_enabled_dry_run_does_not_write(tmp_path):
    path = tmp_path / "d.jsonl"
    r = run_advisory_with_capture(multi_source_reality_cluster(),
                                  capture=CaptureConfig(enabled=True, path=str(path), write=False))
    assert r["capture_status"] == "CAPTURE_DRY_RUN"
    assert not path.exists()


# ---- advisory safety ----
def test_capture_failure_is_non_fatal_by_default(tmp_path):
    r = run_advisory_with_capture(multi_source_reality_cluster(),
                                  capture=_enabled(tmp_path / "d.jsonl"), capture_fn=_boom)
    assert r["capture_status"] == "CAPTURE_FAILED_NON_FATAL"
    assert "disk full" in r["capture_error"]
    assert r["advisory"]["pre_scoring_decision"] == "ROUTE_TO_FABLE5"   # preserved


def test_strict_capture_failure_raises(tmp_path):
    cfg = CaptureConfig(enabled=True, path=str(tmp_path / "d.jsonl"), strict=True, write=True)
    with pytest.raises(CaptureError):
        run_advisory_with_capture(multi_source_reality_cluster(), capture=cfg, capture_fn=_boom)


def test_original_advisory_output_preserved():
    obs = multi_source_reality_cluster()
    r = run_advisory_with_capture(obs, capture=_DISABLED)
    assert r["advisory"] == run_aggregated_pipeline(obs)


def test_capture_status_present_in_output():
    r = run_advisory_with_capture(multi_source_reality_cluster(), capture=_DISABLED)
    assert "capture_status" in r and "decision_context" in r


# ---- schema / context ----
def test_decision_context_fields_present():
    r = run_advisory_with_capture(multi_source_reality_cluster(), capture=_DISABLED,
                                  run_id="run1", decision_timestamp="2026-07-01",
                                  decision_date=1, universe="AI")
    ctx = r["decision_context"]
    for key in ("run_id", "runner_name", "pipeline_version", "advisory_output_id",
                "decision_source", "decision_timestamp", "decision_date",
                "strategy_family", "universe", "dry_run", "capture_mode", "capture_path"):
        assert key in ctx


def test_missing_context_fields_have_reason_codes():
    r = run_advisory_with_capture(multi_source_reality_cluster(), capture=_DISABLED)
    assert any(rc.startswith("MISSING:") for rc in r["context_reason_codes"])
    assert r["decision_context"]["run_id"] is None  # null, not fabricated


def test_runner_advisory_only_stamps(tmp_path):
    path = tmp_path / "d.jsonl"
    r = run_advisory_with_capture(multi_source_reality_cluster(), capture=_enabled(path))
    assert r["advisory_status"] == "ADVISORY_ONLY"
    assert r["real_money_execution"] == "PROHIBITED"
    snap = _json.loads(path.read_text().splitlines()[0])
    assert snap["metadata"]["advisory_status"] == "ADVISORY_ONLY"
    assert snap["metadata"]["real_money_execution"] == "PROHIBITED"


# ---- corpus readiness ----
def _write_eligible(path, n, label="WIN", source_type=PAPER_TRADE, calibratable=True):
    lines = []
    for i in range(n):
        lines.append(_json.dumps({
            "decision_id": f"dec-{label}-{i}", "source_type": source_type,
            "schema_version": "1.0", "feature_bearing": True, "calibratable": calibratable,
            "identity": {}, "mythos": {}, "aggregation": {}, "ledger": {},
            "outcome": {"outcome_label": label, "final_outcome_status": label},
            "metadata": {"created_at": f"2026-07-{(i % 27) + 1:02d}"}}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_readiness_no_corpus_found(tmp_path):
    assert check_decision_capture_corpus(str(tmp_path / "none.jsonl"))["status"] == "NO_CORPUS_FOUND"


def test_readiness_unresolved_only_is_capture_started(tmp_path):
    path = tmp_path / "d.jsonl"
    for i in range(4):
        run_advisory_with_capture(_entity_cluster(i), capture=_enabled(path))
    rep = check_decision_capture_corpus(str(path))
    assert rep["status"] == "CAPTURE_STARTED_NO_LABELS"
    assert rep["resolved"] == 0 and rep["unresolved"] == 4


def test_readiness_provisional_at_twelve(tmp_path):
    path = _write_eligible(tmp_path / "d.jsonl", 12)
    assert check_decision_capture_corpus(str(path))["status"] == "PROVISIONAL_DIAGNOSTIC_READY"


def test_readiness_first_pass_at_thirty(tmp_path):
    path = _write_eligible(tmp_path / "d.jsonl", 30)
    assert check_decision_capture_corpus(str(path))["status"] == "FIRST_PASS_CALIBRATION_READY"


def test_readiness_stronger_at_hundred(tmp_path):
    path = _write_eligible(tmp_path / "d.jsonl", 100)
    assert check_decision_capture_corpus(str(path))["status"] == "STRONGER_CALIBRATION_READY"


def test_readiness_synthetic_not_eligible(tmp_path):
    path = _write_eligible(tmp_path / "d.jsonl", 20, source_type=SYNTHETIC_FIXTURE)
    rep = check_decision_capture_corpus(str(path))
    assert rep["calibration_eligible"] == 0
    assert rep["synthetic_ineligible"] == 20
    assert rep["status"] == "CAPTURE_STARTED_NO_LABELS"


# ---- invariants via runner-captured snapshot ----
def test_runner_captured_snapshot_obeys_invariants(tmp_path):
    path = tmp_path / "d.jsonl"
    run_advisory_with_capture(multi_source_reality_cluster(), capture=_enabled(path))
    snap = _json.loads(path.read_text().splitlines()[0])
    assert snap["fable"]["final_opportunity_score"] <= snap["fable"]["raw_merit"] + 1e-9
    assert snap["captured_confidence"] <= snap["mythos_confidence_cap"] + 1e-9
    assert snap["outcome"]["outcome_label"] == "INCONCLUSIVE"   # unresolved
    assert snap["calibratable"] is False


def test_runner_social_only_not_buy(tmp_path):
    path = tmp_path / "d.jsonl"
    r = run_advisory_with_capture(social_only_cluster(), capture=_enabled(path))
    assert r["routed_to_fable"] is False
    snap = _json.loads(path.read_text().splitlines()[0])
    assert snap["fable"].get("decision") not in {"BUY", "LONG_TERM_COMPOUNDER"}


def test_runner_is_deterministic():
    obs = multi_source_reality_cluster()
    a = run_advisory_with_capture(obs, capture=_DISABLED, run_id="r", decision_date=1)
    b = run_advisory_with_capture(obs, capture=_DISABLED, run_id="r", decision_date=1)
    assert a == b


# ==========================================================================
# Operational CLI harness
# ==========================================================================
from scripts.signal_arbitrage.advisory_runner import cli as _cli


# ---- CLI capture flag behavior ----
def test_cli_default_demo_does_not_write(tmp_path):
    path = tmp_path / "decisions.jsonl"
    res = _cli(["--demo", "--capture-path", str(path)])
    assert res["capture_status"] == "CAPTURE_DISABLED"
    assert not path.exists()


def test_cli_capture_enabled_writes_one(tmp_path):
    path = tmp_path / "decisions.jsonl"
    res = _cli(["--demo", "--capture-decisions", "--capture-mode", "write",
                "--capture-path", str(path)])
    assert res["capture_status"] == "CAPTURE_WRITTEN"
    assert len([l for l in path.read_text().splitlines() if l.strip()]) == 1


def test_cli_dry_run_does_not_write(tmp_path):
    path = tmp_path / "decisions.jsonl"
    res = _cli(["--demo", "--capture-decisions", "--capture-mode", "dry_run",
                "--capture-path", str(path)])
    assert res["capture_status"] == "CAPTURE_DRY_RUN"
    assert not path.exists()


def test_cli_duplicate_rerun_not_appended(tmp_path):
    path = tmp_path / "decisions.jsonl"
    args = ["--demo", "--capture-decisions", "--capture-mode", "write",
            "--capture-path", str(path)]
    _cli(args)
    res2 = _cli(args)
    assert res2["capture_status"] == "DUPLICATE_SKIPPED"
    assert len([l for l in path.read_text().splitlines() if l.strip()]) == 1


def test_cli_custom_path_works(tmp_path):
    path = tmp_path / "deep" / "custom.jsonl"
    res = _cli(["--demo", "--capture-decisions", "--capture-mode", "write",
                "--capture-path", str(path)])
    assert res["capture_status"] == "CAPTURE_WRITTEN"
    assert path.exists()


def test_cli_no_observations_message(tmp_path):
    res = _cli(["--capture-path", str(tmp_path / "d.jsonl")])
    assert res["status"] == "NO_OBSERVATIONS_PROVIDED"


# ---- CLI corpus readiness ----
def test_cli_check_corpus_no_file(tmp_path):
    res = _cli(["--check-corpus", "--capture-path", str(tmp_path / "none.jsonl")])
    assert res["status"] == "NO_CORPUS_FOUND"


def test_cli_check_corpus_unresolved_only(tmp_path):
    path = tmp_path / "d.jsonl"
    for i in range(3):
        run_advisory_with_capture(_entity_cluster(i), capture=_enabled(path),
                                  decision_context_extra=None)
    res = _cli(["--check-corpus", "--capture-path", str(path)])
    assert res["status"] == "CAPTURE_STARTED_NO_LABELS"


def test_cli_check_corpus_provisional(tmp_path):
    path = _write_eligible(tmp_path / "d.jsonl", 12)
    res = _cli(["--check-corpus", "--capture-path", str(path)])
    assert res["status"] == "PROVISIONAL_DIAGNOSTIC_READY"


def test_cli_check_corpus_first_pass(tmp_path):
    path = _write_eligible(tmp_path / "d.jsonl", 30)
    res = _cli(["--check-corpus", "--capture-path", str(path)])
    assert res["status"] == "FIRST_PASS_CALIBRATION_READY"


def test_cli_check_corpus_stronger(tmp_path):
    path = _write_eligible(tmp_path / "d.jsonl", 100)
    res = _cli(["--check-corpus", "--capture-path", str(path)])
    assert res["status"] == "STRONGER_CALIBRATION_READY"


def test_cli_synthetic_resolved_remains_ineligible(tmp_path):
    path = _write_eligible(tmp_path / "d.jsonl", 15, source_type=SYNTHETIC_FIXTURE)
    res = _cli(["--check-corpus", "--capture-path", str(path)])
    assert res["calibration_eligible"] == 0
    assert res["status"] == "CAPTURE_STARTED_NO_LABELS"


# ---- CLI outcome resolution ----
def test_cli_resolve_outcome_win(tmp_path):
    path = tmp_path / "d.jsonl"
    r = run_advisory_with_capture(multi_source_reality_cluster(), capture=_enabled(path))
    did = r["capture"]["decision_id"]
    res = _cli(["--resolve-outcome", "--decision-id", did, "--realized-return", "0.12",
                "--capture-mode", "write", "--capture-path", str(path)])
    assert res["new_label"] == "WIN"
    assert res["calibration_eligible"] is True


def test_cli_resolve_dry_run_does_not_write(tmp_path):
    path = tmp_path / "d.jsonl"
    r = run_advisory_with_capture(multi_source_reality_cluster(), capture=_enabled(path))
    before = path.read_text()
    res = _cli(["--resolve-outcome", "--decision-id", r["capture"]["decision_id"],
                "--realized-return", "0.1", "--capture-path", str(path)])
    assert res["status"] == "RESOLUTION_DRY_RUN"
    assert path.read_text() == before


def test_cli_resolve_avoided_trap(tmp_path):
    path = tmp_path / "d.jsonl"
    r = run_advisory_with_capture(social_only_cluster(), capture=_enabled(path))
    did = r["capture"]["decision_id"]
    res = _cli(["--resolve-outcome", "--decision-id", did, "--realized-return", "-0.1",
                "--capture-mode", "write", "--capture-path", str(path)])
    assert res["new_label"] == "AVOIDED_TRAP"


def test_cli_resolve_conflict_rejected(tmp_path):
    path = tmp_path / "d.jsonl"
    r = run_advisory_with_capture(multi_source_reality_cluster(), capture=_enabled(path))
    did = r["capture"]["decision_id"]
    _cli(["--resolve-outcome", "--decision-id", did, "--realized-return", "0.1",
          "--capture-mode", "write", "--capture-path", str(path)])
    res = _cli(["--resolve-outcome", "--decision-id", did, "--realized-return", "-0.1",
                "--capture-mode", "write", "--capture-path", str(path)])
    assert res["status"] == "CONFLICT_REJECTED"


# ---- CLI calibration ----
def test_cli_run_calibration_insufficient(tmp_path):
    res = _cli(["--run-calibration", "--capture-path", str(tmp_path / "empty.jsonl")])
    assert res["status"] == "INSUFFICIENT_EVIDENCE"
    assert res["weights_fitted"] is False


def test_cli_run_calibration_provisional(tmp_path):
    path = _forward_corpus(tmp_path, 12)
    res = _cli(["--run-calibration", "--capture-path", str(path)])
    assert res["status"] == "PROVISIONAL_DIAGNOSTIC"


# ---- CLI invariants ----
def test_cli_outputs_are_advisory_only(tmp_path):
    res = _cli(["--check-corpus", "--capture-path", str(tmp_path / "x.jsonl")])
    assert res["advisory_status"] == "ADVISORY_ONLY"


def test_cli_is_deterministic(tmp_path):
    path = _write_eligible(tmp_path / "d.jsonl", 12)
    assert _cli(["--check-corpus", "--capture-path", str(path)]) == \
        _cli(["--check-corpus", "--capture-path", str(path)])
