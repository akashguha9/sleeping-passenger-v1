"""Narrative Branch Engine (nbi-v1.0) — invariant + guardrail regression tests.

Covers the ten sprint guardrails:
 1. P(venue) can never exceed P(core)                (structural invariant)
 2. Social-only rumor can never upgrade a score      (velocity is not truth)
 3. Same-cluster repetition does not compound        (independence discipline)
 4. Venue collapse downgrades the local symbolic basket but preserves the
    broad macro basket                               (Guwahati -> Delhi doctrine)
 5. Missing evidence refs fail closed (UNVERIFIED / score 0)
 6. RumorRisk >= cap threshold can never produce ACT
 7. FINAL_TICKER_SCORE <= VALIDATED <= BASE (demote-only multiplier chain)
 8. Operator card carries evidence counts + branch explanation
 9. Missing price validation -> WATCH_ONLY, never actionable
10. A partial-resolution event is not DEAD unless the core branch collapses

Plus: chicken-gate min() composition, backtest-case schema, NDM/CFD wiring,
scope-guard + module-boundary registration, and the advisory safety stamp.
"""
from __future__ import annotations

import copy
import json

from scripts import narrative_branch_engine as nbi
from scripts import chicken_gate as cg
from scripts import core_module_boundary as cmb
from scripts import private_scope_guard as psg


# ---------------------------------------------------------------------------
# Event builders (deterministic: recency comes from explicit age_hours only)
# ---------------------------------------------------------------------------


def _claim(**overrides) -> dict:
    base = {
        "claim_id": "c",
        "layer": "CORE_FACT",
        "claim_text": "summit reported",
        "source_cluster": "cluster-a",
        "source_class": "CREDIBLE_MEDIA",
        "jurisdiction": "JP",
        "historical_accuracy": 0.85,
        "age_hours": 12,
        "direction": "SUPPORTS",
        "branch": "core_event",
        "strength": 0.8,
        "evidence_refs": ["https://example.com/a"],
    }
    base.update(overrides)
    return base


def _exposure(**overrides) -> dict:
    base = {
        "ticker": "CORE1",
        "channel": "BROAD_THEMATIC",
        "base_relevance": 9.0,
        "evidence_confidence": 1.0,
        "evidence_refs": ["https://example.com/filing"],
        "filing_confirmed": True,
        "liquidity_ok": True,
        "days_since_last_verified": 0.0,
        "model_probability": 0.62,
        "market_implied_probability": 0.50,
        "realized_move_zscore": 1.2,
    }
    base.update(overrides)
    return base


def _event(claims=None, exposures=None, priors=None, **overrides) -> dict:
    event = {
        "event_id": "test-event",
        "event_name": "test event",
        "decision_jurisdictions": ["JP", "IN"],
        "claims": claims if claims is not None else [_claim()],
        "exposures": exposures if exposures is not None else [_exposure()],
    }
    if priors is not None:
        event["priors"] = priors
    event.update(overrides)
    return event


def demo_report() -> dict:
    return nbi.build_event_report(copy.deepcopy(nbi.DEMO_EVENT))


# ---------------------------------------------------------------------------
# 1. Sub-branch <= core invariant
# ---------------------------------------------------------------------------


def test_venue_probability_cannot_exceed_core():
    # Strong venue support, weak core: venue must be capped at core.
    claims = [
        _claim(claim_id="v1", branch="venue_specific",
               source_class="OFFICIAL_GOVERNMENT", historical_accuracy=1.0,
               strength=1.0, age_hours=1),
        _claim(claim_id="c1", branch="core_event", source_class="LOCAL_MEDIA",
               strength=0.2, source_cluster="cluster-b"),
    ]
    branches = nbi.evaluate_event_branches(
        nbi.normalize_claims(claims), {"core_event": 0.4, "venue_specific": 0.5},
        ["JP", "IN"],
    )
    assert branches["venue_specific"]["p"] <= branches["core_event"]["p"] + 1e-9
    assert "CAPPED_BY_CORE" in branches["venue_specific"]["status"]


def test_all_core_bounded_branches_capped_in_report():
    report = demo_report()
    assert report["invariants"]["sub_branches_leq_core"] is True
    core = report["branches"]["core_event"]["p"]
    for b in nbi.CORE_BOUNDED_BRANCHES:
        assert report["branches"][b]["p"] <= core + 1e-9


# ---------------------------------------------------------------------------
# 2. Social media is velocity, never truth; rumor can only demote
# ---------------------------------------------------------------------------


def test_social_claims_do_not_move_branch_probabilities():
    no_social = nbi.evaluate_event_branches(
        nbi.normalize_claims([_claim()]), None, ["JP"],
    )
    with_social = nbi.evaluate_event_branches(
        nbi.normalize_claims([
            _claim(),
            _claim(claim_id="s1", source_class="SOCIAL_MEDIA",
                   source_cluster="viral-1", strength=1.0),
            _claim(claim_id="s2", source_class="SOCIAL_MEDIA",
                   source_cluster="viral-2", strength=1.0),
        ]), None, ["JP"],
    )
    assert with_social["core_event"]["p"] == no_social["core_event"]["p"]


def test_rumor_claims_can_only_lower_final_score():
    quiet = nbi.build_event_report(_event())
    rumor_claims = [
        _claim(),
        _claim(claim_id="k1", layer="TRIGGER", source_class="LOCAL_MEDIA",
               source_cluster="local-1", direction="NEUTRAL", strength=1.0,
               jurisdiction="IN"),
        _claim(claim_id="r1", layer="RUMOR", source_class="SOCIAL_MEDIA",
               source_cluster="insta", direction="REFUTES",
               claim_text="BREAKING chaos panic!! cancelled",
               claim_magnitude=10.0, evidence_strength=0.0,
               mentions_per_hour=60),
    ]
    noisy = nbi.build_event_report(_event(claims=rumor_claims))
    q = quiet["tickers"][0]["FINAL_TICKER_SCORE"]
    n = noisy["tickers"][0]["FINAL_TICKER_SCORE"]
    assert noisy["scores"]["RUMOR_RISK"] > 0
    assert n <= q  # rumor never upgrades


# ---------------------------------------------------------------------------
# 3. Cluster independence: repetition inside a cluster does not compound
# ---------------------------------------------------------------------------


def test_same_cluster_repetition_does_not_compound():
    one = nbi.evaluate_event_branches(
        nbi.normalize_claims([_claim()]), None, ["JP"],
    )
    five_same_cluster = nbi.evaluate_event_branches(
        nbi.normalize_claims([
            _claim(claim_id=f"c{i}") for i in range(5)
        ]), None, ["JP"],
    )
    assert five_same_cluster["core_event"]["p"] == one["core_event"]["p"]
    assert five_same_cluster["core_event"]["n_clusters"] == 1


def test_independent_cluster_adds_confirmation():
    one = nbi.evaluate_event_branches(
        nbi.normalize_claims([_claim()]), None, ["JP"],
    )
    two_clusters = nbi.evaluate_event_branches(
        nbi.normalize_claims([
            _claim(),
            _claim(claim_id="c2", source_cluster="cluster-b"),
        ]), None, ["JP"],
    )
    assert two_clusters["core_event"]["p"] > one["core_event"]["p"]
    assert two_clusters["core_event"]["n_clusters"] == 2


# ---------------------------------------------------------------------------
# 4. The Guwahati -> Delhi doctrine: rotate, don't die
# ---------------------------------------------------------------------------


def test_venue_collapse_downgrades_local_preserves_macro():
    report = demo_report()
    assert report["EVENT_STATE"] == "TRANSFORMED"
    by_ticker = {t["ticker"]: t for t in report["tickers"]}
    # Local symbolic / venue names downgraded...
    assert by_ticker["ASSAMINFRA"]["downgraded"] is True
    assert by_ticker["NE_CEMENT"]["downgraded"] is True
    assert "ASSAMINFRA" in report["downgraded_tickers"]
    # ...while broad macro names survive on the core branch.
    assert by_ticker["JPMACH"]["downgraded"] is False
    assert by_ticker["JPMACH"]["governing_branch"] == "core_event"
    assert by_ticker["JPMACH"]["FINAL_TICKER_SCORE"] > \
        by_ticker["ASSAMINFRA"]["FINAL_TICKER_SCORE"]
    assert report["ACTION"] == "ROTATE"
    assert "venue_specific" in report["surviving_layer"]["killed_branches"]
    assert "core_event" in report["surviving_layer"]["surviving_branches"]


def test_hedge_pairs_long_survivors_against_collapsed_basket():
    report = demo_report()
    hedge = report["hedge"]
    assert hedge["status"] == "COMPUTED"
    assert set(hedge["underweight_basket"]) == {"ASSAMINFRA", "NE_CEMENT"}
    assert "JPMACH" in hedge["long_basket"]
    assert hedge["hedge_ratio"] is not None and hedge["hedge_ratio"] >= 0
    assert isinstance(hedge["hedge_class"], str) and hedge["hedge_class"]


# ---------------------------------------------------------------------------
# 5. Cite-or-drop provenance: missing evidence fails closed
# ---------------------------------------------------------------------------


def test_claim_without_evidence_refs_is_unverified_and_excluded():
    claims = nbi.normalize_claims([_claim(evidence_refs=[])])
    assert claims[0]["verification"] == "UNVERIFIED"
    branches = nbi.evaluate_event_branches(claims, None, ["JP"])
    assert branches["core_event"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert branches["core_event"]["p"] == branches["core_event"]["prior"]


def test_exposure_without_evidence_refs_scores_zero():
    report = nbi.build_event_report(
        _event(exposures=[_exposure(evidence_refs=[])])
    )
    row = report["tickers"][0]
    assert row["FINAL_TICKER_SCORE"] == 0.0
    assert row["status"] == "NO_VERIFIED_EVIDENCE"
    assert row["actionable"] is False
    assert report["ACTION"] == "NO_ACTIONABLE_EXPOSURE"


def test_unverified_claims_listed_in_report():
    report = nbi.build_event_report(
        _event(claims=[_claim(), _claim(claim_id="bad", evidence_refs=[])])
    )
    excluded = report["claims_excluded_unverified"]
    assert len(excluded) == 1 and excluded[0]["claim_id"] == "bad"
    assert report["claims_verified"] == 1


# ---------------------------------------------------------------------------
# 6. Rumor cap: high rumor risk can never produce ACT
# ---------------------------------------------------------------------------


def _high_rumor_event() -> dict:
    claims = [
        _claim(source_class="OFFICIAL_GOVERNMENT", historical_accuracy=1.0,
               strength=1.0, age_hours=1),
        _claim(claim_id="k1", layer="TRIGGER", source_class="LOCAL_MEDIA",
               source_cluster="local-1", direction="NEUTRAL", strength=1.0,
               jurisdiction="IN"),
        _claim(claim_id="r1", layer="RUMOR", source_class="SOCIAL_MEDIA",
               source_cluster="insta", direction="REFUTES",
               claim_text="BREAKING!! chaos panic shocking urgent crisis",
               claim_magnitude=10.0, evidence_strength=0.0,
               mentions_per_hour=60),
    ]
    return _event(claims=claims, priors={"core_event": 0.7})


def test_high_rumor_risk_caps_action_below_act():
    report = nbi.build_event_report(_high_rumor_event())
    assert report["scores"]["RUMOR_RISK"] >= nbi.RUMOR_CAP_THRESHOLD
    assert report["ACTION"] in ("WATCH", "ROTATE")
    assert report["ACTION"] != "ACT"
    assert all(t["actionable"] is False for t in report["tickers"])


def test_high_rumor_does_not_kill_high_core_thesis():
    """Rumor reduces confidence but the core branch and thesis survive."""
    report = nbi.build_event_report(_high_rumor_event())
    assert report["branches"]["core_event"]["p"] >= 0.5
    assert report["EVENT_STATE"] in ("RUMOR_CONTESTED", "ACTIVE", "EMERGING")
    assert report["EVENT_STATE"] != "DEAD"
    row = report["tickers"][0]
    assert row["FINAL_TICKER_SCORE"] > 0  # demoted, not discarded


def test_low_rumor_fully_validated_exposure_can_act():
    claims = [
        _claim(source_class="OFFICIAL_GOVERNMENT", historical_accuracy=1.0,
               strength=1.0, age_hours=1),
        _claim(claim_id="c2", source_cluster="cluster-b"),
        _claim(claim_id="c3", source_cluster="cluster-c"),
    ]
    report = nbi.build_event_report(
        _event(claims=claims, priors={"core_event": 0.8})
    )
    assert report["scores"]["RUMOR_RISK"] == 0.0
    assert report["ACTION"] == "ACT"
    assert report["tickers"][0]["actionable"] is True


# ---------------------------------------------------------------------------
# 7. Demote-only multiplier chain
# ---------------------------------------------------------------------------


def test_final_leq_validated_leq_base_everywhere():
    for report in (demo_report(), nbi.build_event_report(_high_rumor_event())):
        assert report["invariants"]["final_leq_validated_all_tickers"] is True
        for t in report["tickers"]:
            assert t["FINAL_TICKER_SCORE"] <= t["VALIDATED_RELEVANCE"] + 1e-9
            assert t["VALIDATED_RELEVANCE"] <= t["BASE_RELEVANCE"] + 1e-9
            for name, m in t["multipliers"].items():
                assert 0.0 <= m <= 1.0, f"{name} multiplier out of [0,1]"


def test_hard_gate_liquidity_zeroes_score():
    report = nbi.build_event_report(
        _event(exposures=[_exposure(liquidity_ok=False)])
    )
    assert report["tickers"][0]["FINAL_TICKER_SCORE"] == 0.0
    assert report["tickers"][0]["actionable"] is False


def test_filing_unconfirmed_haircut_applied():
    confirmed = nbi.build_event_report(_event())
    unconfirmed = nbi.build_event_report(
        _event(exposures=[_exposure(filing_confirmed=False)])
    )
    assert unconfirmed["tickers"][0]["FINAL_TICKER_SCORE"] < \
        confirmed["tickers"][0]["FINAL_TICKER_SCORE"]
    assert unconfirmed["tickers"][0]["multipliers"]["m_filing"] == \
        nbi.FILING_UNCONFIRMED_MULTIPLIER


# ---------------------------------------------------------------------------
# 8. Operator card: evidence + branch explanation, machine-parseable report
# ---------------------------------------------------------------------------


def test_event_card_contains_evidence_and_branch_explanation():
    report = demo_report()
    card = nbi.render_event_card(report)
    assert "BRANCHES:" in card and "core_event=" in card
    assert "EVIDENCE:" in card and "independent clusters" in card
    assert "SURVIVING LAYER:" in card
    assert "RUMOR RISK:" in card
    assert "VERIFY NEXT:" in card
    assert "ACTION: ROTATE" in card
    assert "ADVISORY_ONLY" in card and "human decides" in card
    # Every branch update in the report is traceable to evidence refs.
    for b in nbi.BRANCHES:
        for ev in report["branches"][b]["evidence"]:
            assert ev["evidence_refs"], f"branch {b} evidence missing refs"


def test_report_is_json_serializable():
    json.dumps(demo_report(), default=str)


# ---------------------------------------------------------------------------
# 9. Price validation absent -> WATCH_ONLY
# ---------------------------------------------------------------------------


def test_missing_price_validation_caps_watch_only():
    report = nbi.build_event_report(
        _event(exposures=[_exposure(model_probability=None,
                                    market_implied_probability=None,
                                    realized_move_zscore=None)])
    )
    row = report["tickers"][0]
    assert row["status"] == "WATCH_ONLY"
    assert row["actionable"] is False
    assert row["price_validation"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert report["ACTION"] != "ACT"
    assert any("price/volume validation" in v for v in report["verify_next"])


def test_dislocation_watch_flag_requires_price_and_rumor_and_core():
    report = demo_report()
    by_ticker = {t["ticker"]: t for t in report["tickers"]}
    assert "DISLOCATION_WATCH" in by_ticker["JPMACH"]["flags"]
    # No price data -> no dislocation flag, ever.
    assert "DISLOCATION_WATCH" not in by_ticker["ASSAMINFRA"]["flags"]


# ---------------------------------------------------------------------------
# 10. Partial resolution never means DEAD unless core collapses
# ---------------------------------------------------------------------------


def test_partial_resolution_with_live_core_is_not_dead():
    claims = [
        _claim(),
        _claim(claim_id="p1", layer="PARTIAL_RESOLUTION",
               source_class="OFFICIAL_GOVERNMENT", source_cluster="mofa",
               direction="NEUTRAL", strength=0.9, age_hours=2),
    ]
    report = nbi.build_event_report(_event(claims=claims))
    assert report["EVENT_STATE"] == "PARTIAL_RESOLUTION"
    assert report["EVENT_STATE"] != "DEAD"


def test_core_collapse_is_dead_even_with_partial_resolution_claim():
    claims = [
        _claim(claim_id="kill", source_class="OFFICIAL_GOVERNMENT",
               source_cluster="mofa", direction="REFUTES", strength=1.0,
               historical_accuracy=1.0, age_hours=1),
        _claim(claim_id="p1", layer="PARTIAL_RESOLUTION",
               source_class="OFFICIAL_GOVERNMENT", source_cluster="mofa2",
               direction="NEUTRAL", strength=0.9, age_hours=2),
    ]
    report = nbi.build_event_report(
        _event(claims=claims, priors={"core_event": 0.3})
    )
    assert report["branches"]["core_event"]["p"] < nbi.CORE_DEAD_THRESHOLD
    assert report["EVENT_STATE"] == "DEAD"
    assert report["ACTION"] == "FOLD"


# ---------------------------------------------------------------------------
# v1.1 additions: branch chain, confidence decay, velocity source
# ---------------------------------------------------------------------------


def test_deals_capped_by_delegation_without_direct_evidence():
    branches = nbi.evaluate_event_branches(
        nbi.normalize_claims([_claim(branch="delegation_intact", strength=0.3)]),
        {"deals_or_mous": 0.9, "delegation_intact": 0.4, "core_event": 0.95},
        ["JP"],
    )
    assert branches["deals_or_mous"]["p"] <= \
        branches["delegation_intact"]["p"] + 1e-9
    assert "CAPPED_BY_DELEGATION" in branches["deals_or_mous"]["status"]


def test_deals_with_direct_evidence_escapes_delegation_cap():
    claims = nbi.normalize_claims([
        _claim(claim_id="d1", branch="deals_or_mous",
               source_class="EXCHANGE_FILING", strength=0.9, age_hours=2),
        _claim(claim_id="g1", branch="delegation_intact", direction="REFUTES",
               strength=0.7, source_cluster="cluster-b"),
    ])
    branches = nbi.evaluate_event_branches(
        claims, {"core_event": 0.9, "deals_or_mous": 0.5,
                 "delegation_intact": 0.5}, ["JP"],
    )
    # Direct filing evidence lets deals exceed a reduced delegation branch...
    assert branches["deals_or_mous"]["p"] > branches["delegation_intact"]["p"]
    # ...but never the core.
    assert branches["deals_or_mous"]["p"] <= branches["core_event"]["p"] + 1e-9


def test_confidence_decay_from_official_claim_age():
    claims = nbi.normalize_claims([
        _claim(source_class="OFFICIAL_GOVERNMENT", age_hours=48),
    ])
    decay = nbi.evaluate_confidence_decay({}, claims)
    assert decay["source"] == "official_claim_age"
    assert decay["days_unconfirmed"] == 2.0
    assert 0.89 < decay["C_t"] < 0.91  # e^(-0.05*2)


def test_confidence_decay_missing_official_signal_haircuts():
    decay = nbi.evaluate_confidence_decay({}, nbi.normalize_claims([_claim()]))
    assert decay["source"] == "INSUFFICIENT_EVIDENCE"
    assert decay["C_t"] == nbi.CONFIDENCE_DECAY_MISSING
    # And it demotes ticker scores end-to-end.
    report = nbi.build_event_report(_event())
    assert report["tickers"][0]["multipliers"]["m_confidence_decay"] == \
        nbi.CONFIDENCE_DECAY_MISSING


def test_rumor_velocity_source_disclosed():
    assert nbi.evaluate_rumor_risk([])["velocity_source"] == "NONE"
    report = demo_report()
    assert report["rumor"]["velocity_source"] == "mentions_per_hour"


# ---------------------------------------------------------------------------
# Rumor detector doctrine: Truth(Event) != Truth(CausalClaim)
# ---------------------------------------------------------------------------


def test_traffic_incident_does_not_prove_visit_cancelled():
    """The Ganeshguri case: verified trigger + unverified macro claim."""
    report = demo_report()
    rumor = report["rumor"]
    assert rumor["verdict"] == "TRUE_MICRO_EVENT_UNSUPPORTED_MACRO_CLAIM"
    assert rumor["kernel_truth"] >= 0.5      # the traffic jam was real
    assert rumor["causal_leap"] >= 0.5       # the cancellation link is not
    # And crucially: the rumor did NOT drag the core branch down.
    assert report["branches"]["core_event"]["p"] >= 0.6


def test_fabrication_suspected_without_verified_kernel():
    claims = [
        _claim(claim_id="r1", layer="RUMOR", source_class="SOCIAL_MEDIA",
               source_cluster="anon", claim_text="secret deal collapse",
               claim_magnitude=9.0, evidence_strength=0.0,
               evidence_refs=["https://example.com/anon"]),
    ]
    rumor = nbi.evaluate_rumor_risk(nbi.normalize_claims(claims))
    assert rumor["verdict"] == "FABRICATION_SUSPECTED"


def test_no_rumor_claims_scores_zero():
    rumor = nbi.evaluate_rumor_risk(nbi.normalize_claims([_claim()]))
    assert rumor["RUMOR_RISK"] == 0.0
    assert rumor["verdict"] == "NO_RUMOR"


# ---------------------------------------------------------------------------
# Chicken-gate composition: NBI can only demote an existing decision
# ---------------------------------------------------------------------------


def test_chicken_gate_integration_is_min_composition():
    chicken = cg.evaluate_chicken_gate(dict(cg.DEMO_THESIS, ticker="JPMACH"))
    report = demo_report()
    integrated = nbi.integrate_with_chicken_gate(chicken, report, "JPMACH")
    nbi_score = next(
        t["FINAL_TICKER_SCORE"] for t in report["tickers"]
        if t["ticker"] == "JPMACH"
    )
    assert integrated["nbi_applied"] is True
    assert integrated["INTEGRATED_FINAL_SCORE"] <= chicken["FINAL_SCORE"] + 1e-9
    assert integrated["INTEGRATED_FINAL_SCORE"] <= nbi_score + 1e-9
    # JPMACH is RUMOR_CAPPED in the demo -> gate capped at WATCHLIST.
    assert integrated["INTEGRATED_GATE"] in ("WATCHLIST", "BUY_BLOCKED")


def test_chicken_gate_integration_unknown_ticker_unchanged():
    chicken = cg.evaluate_chicken_gate(dict(cg.DEMO_THESIS, ticker="ZZZ"))
    integrated = nbi.integrate_with_chicken_gate(chicken, demo_report(), "ZZZ")
    assert integrated["nbi_applied"] is False
    assert integrated["INTEGRATED_FINAL_SCORE"] == round(chicken["FINAL_SCORE"], 4)
    assert integrated["INTEGRATED_GATE"] == chicken["FINAL_ACTION_GATE"]


# ---------------------------------------------------------------------------
# Backtest case seed
# ---------------------------------------------------------------------------


def test_backtest_case_schema_complete_and_labelled():
    report = demo_report()
    case = nbi.build_backtest_case(
        report,
        category="DIPLOMATIC_SUMMIT",
        resolution_labels={"core": "HAPPENED", "venue": "CHANGED_TO_DELHI"},
        outcome_label="CORE_HELD_SUB_BRANCH_COLLAPSED",
        benchmark="NIFTY50",
    )
    for field in nbi.BACKTEST_CASE_FIELDS:
        assert field in case
    assert case["branch_probabilities_at_rumor_peak"]["core_event"] == \
        report["branches"]["core_event"]["p"]
    # Demo action is ROTATE: neither a false positive nor a false negative
    # under a core-held/sub-branch-collapsed resolution.
    assert case["false_positive"] is False
    assert case["false_negative"] is False


def test_backtest_case_rejects_unknown_outcome_label():
    try:
        nbi.build_backtest_case(
            demo_report(), category="X", resolution_labels={},
            outcome_label="NOT_A_LABEL",
        )
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("unknown outcome_label must raise")


# ---------------------------------------------------------------------------
# Existing-module wiring: NDM, CFD, hedge classifier
# ---------------------------------------------------------------------------


def test_ndm_flags_rumor_heavy_corpus_as_narrative_first():
    report = nbi.build_event_report(_high_rumor_event())
    assert report["ndm"]["ndm_state"] in ("WATCH", "DRIFTING", "NARRATIVE_FIRST")


def test_consensus_view_computed_and_fails_closed():
    assert nbi.build_consensus_view(None)["status"] == "INSUFFICIENT_EVIDENCE"
    assert nbi.build_consensus_view({"pc": 0.5})["status"] == "INSUFFICIENT_EVIDENCE"
    view = nbi.build_consensus_view(
        {"pc": 0.9, "rs": 0.9, "cc": 0.8, "ms": 0.9, "cs_previous": 0.4}
    )
    assert view["status"] == "COMPUTED"
    assert view["cfd_state"] in ("FORMING", "EMERGING", "CONVERGING", "LOCKED")


# ---------------------------------------------------------------------------
# Registration + safety stamps
# ---------------------------------------------------------------------------


def test_module_registered_in_scope_guard_and_boundary():
    assert psg._classify("narrative_branch_engine.py") == "in_scope"
    assert cmb.classify("narrative_branch_engine") == cmb.SUPPORT


def test_report_carries_advisory_safety_stamps():
    report = demo_report()
    for key in ("ADVISORY_ONLY_STAMP", "safety"):
        assert report[key]["advisory_status"] == "ADVISORY_ONLY"
    assert report["human"]["execution_mode"] == "HUMAN_ONLY"


def test_demo_cli_runs_and_prints_card(capsys):
    assert nbi.main(["--demo"]) == 0
    out = capsys.readouterr().out
    assert "NARRATIVE BRANCH EVENT CARD" in out
    assert nbi.main(["--demo", "--json"]) == 0
