"""Live-evidence governance: lineage forgery blocked, data-mode derived."""
from __future__ import annotations

import pytest

from scripts import signal_thesis_card_report as card
from scripts import signal_thesis_contract as tc

AS_OF = 1000


def _research_with(evidence: list[tc.EvidenceItem],
                   data_mode: str = tc.LIVE) -> tc.ThesisContract:
    return tc.ThesisContract(
        thesis_id="lr-auth-0001", title="auth test", entity="E", ticker="T",
        narrative="n", trigger="t", predicted_direction="UP",
        horizon_days=60, created_day=AS_OF - 10, expiry_day=AS_OF + 50,
        falsification_observable="f", forced_null_thesis="null",
        causal_path=["a", "b"], beneficiary_map={"house": ["T"]},
        evidence=evidence, merit_inputs={"awareness_gap": 8.0,
                                         "house_layer": 8.0},
        data_mode=data_mode, contract_purpose=tc.LIVE_RESEARCH)


def _promoted_pair():
    """A legitimately promoted candidate plus its research parent."""
    ecologies = ("sec_filing", "regulatory", "earnings_call", "pricing_page")
    ev = [tc.EvidenceItem(
        f"h{i}", "filing", "EDGAR", ecologies[i % len(ecologies)],
        tc.HARD_DATA, tc.FOR_THESIS, AS_OF - i,
        source_mode=tc.SM_HARD_FILING,
        source_uri_or_adapter="https://sec.gov/x",
        fetch_timestamp="2026-07-02T00:00:00Z", adapter_name="t",
        adapter_run_id="r1", source_hash="ab" * 16,
        accession_or_filing_id=f"acc-{i}", is_fixture=False)
        for i in range(1, 8)]
    research = _research_with(ev)
    research.merit_inputs = {"awareness_gap": 8.0, "long_tail_demand": 8.0,
                             "house_layer": 9.0, "infra_capture": 8.5,
                             "transaction_certainty": 8.5,
                             "narrative_transmission": 8.5}
    result = tc.promote_research_to_investable(
        research, approval_note="ok", as_of_day=AS_OF)
    assert result["promoted"] is True, result
    return result["contract"], research


# --- lineage forgery -------------------------------------------------------------

def test_forged_candidate_fails_lineage_and_scores_zero():
    forged = tc.ThesisContract(
        thesis_id="forged-cand", title="forged", entity="E", ticker="T",
        narrative="n", trigger="t", predicted_direction="UP",
        horizon_days=30, created_day=AS_OF, expiry_day=AS_OF + 30,
        falsification_observable="f", forced_null_thesis="null",
        contract_purpose=tc.INVESTABLE_CANDIDATE,
        promotion_status="PROMOTED", parent_research_id="does-not-exist",
        parent_hash="ff" * 16, lineage_hash="ee" * 16)
    lineage = tc.verify_lineage_from_index(forged, {})
    assert lineage["valid"] is False
    assert "CONTRACT_LINEAGE_FAIL_CLOSED:PARENT_NOT_FOUND" in lineage["reasons"]
    r = tc.grade(forged, AS_OF)          # no lineage proof supplied
    assert r["investability_score"] == 0.0
    assert "LINEAGE_UNVERIFIED_FAIL_CLOSED" in r["caps_applied"]


def test_forged_candidate_cannot_sit_on_investable_board():
    cand, research = _promoted_pair()
    # tamper with the parent's ESCROW COLLATERAL after promotion: the
    # identity hash no longer matches (evidence additions would be fine;
    # re-pointing the falsification contract is not)
    research.falsification_observable = "weakened after promotion"
    lineage = tc.verify_lineage(cand, research)
    assert lineage["valid"] is False
    assert "PARENT_HASH_MISMATCH" in lineage["reasons"]
    with pytest.raises(ValueError, match="CONTRACT_LINEAGE_FAIL_CLOSED"):
        card.build_boards(
            [(cand, tc.grade(cand, AS_OF, lineage_valid=False))],
            contract_index={research.thesis_id: research})


def test_legit_promotion_verifies_and_boards():
    cand, research = _promoted_pair()
    lineage = tc.verify_lineage(cand, research)
    assert lineage["valid"] is True, lineage
    boards = card.build_boards(
        [(cand, tc.grade(cand, AS_OF, lineage_valid=True))],
        contract_index={research.thesis_id: research})
    assert len(boards["INVESTABLE_CANDIDATE_BOARD"]) == 1


def test_evidence_accumulation_does_not_break_lineage():
    """Research must be able to EARN evidence after cloning; only the escrow
    collateral is hash-bound."""
    cand, research = _promoted_pair()
    research.evidence = list(research.evidence) + [tc.EvidenceItem(
        "new-ev", "later filing", "EDGAR", "sec_filing", tc.HARD_DATA,
        tc.FOR_THESIS, AS_OF + 1, source_mode=tc.SM_HARD_FILING,
        source_hash="ff" * 16, accession_or_filing_id="acc-new",
        is_fixture=False)]
    assert tc.verify_lineage(cand, research)["valid"] is True


def test_retired_parent_cannot_mint_candidates():
    cand, research = _promoted_pair()
    tc._reassign_purpose(research, tc.RETIRED)
    lineage = tc.verify_lineage(cand, research)
    assert lineage["valid"] is False
    assert any("TRANSITION_NOT_ALLOWED" in r or "PARENT_PURPOSE" in r
               for r in lineage["reasons"])


def test_lineage_hash_binds_promotion_note():
    cand, research = _promoted_pair()
    cand.promotion_note = "rewritten rationale"   # post-hoc edit
    lineage = tc.verify_lineage(cand, research)
    assert lineage["valid"] is False
    assert "LINEAGE_HASH_MISMATCH" in lineage["reasons"]


# --- data-mode authenticity ------------------------------------------------------

def test_self_declared_live_without_proof_is_not_live():
    bare = tc.EvidenceItem("x", "claim", "src", "news", tc.MARKET,
                           tc.FOR_THESIS, AS_OF, source_mode=tc.SM_LIVE)
    assert tc.item_live_verified(bare) is False
    c = _research_with([bare])
    r = tc.grade(c, AS_OF)
    assert r["derived_data_mode"] != "LIVE"
    assert r["evidence_mode_counts"]["live_verified"] == 0


def test_live_with_full_adapter_metadata_verifies():
    proven = tc.EvidenceItem(
        "x", "claim", "src", "prediction_market", tc.MARKET, tc.FOR_THESIS,
        AS_OF, source_mode=tc.SM_LIVE,
        source_uri_or_adapter="https://api.example/markets",
        fetch_timestamp="2026-07-02T10:00:00Z",
        adapter_name="kalshi_public", adapter_run_id="run-1",
        source_hash="cd" * 16, is_fixture=False)
    assert tc.item_live_verified(proven) is True
    r = tc.grade(_research_with([proven]), AS_OF)
    assert r["derived_data_mode"] == "LIVE"
    assert r["authenticity_cap"] == 10.0


def test_fixture_mislabeled_live_is_blocked_on_candidate():
    mislabeled = tc.EvidenceItem(
        "x", "claim", "src", "prediction_market", tc.MARKET, tc.FOR_THESIS,
        AS_OF, source_mode=tc.SM_LIVE,
        source_uri_or_adapter="u", fetch_timestamp="t",
        adapter_name="a", adapter_run_id="r", source_hash="h",
        is_fixture=True)   # the tell: fixture flag survives the costume
    cand, research = _promoted_pair()
    cand.evidence = list(cand.evidence) + [mislabeled]
    r = tc.grade(cand, AS_OF, lineage_valid=True)
    assert r["verdict"] == tc.V_BLOCKED_FIXTURE_CONTAMINATION
    assert r["investability_score"] == 0.0
    assert "FIXTURE_CONTAMINATION_BLOCK" in r["caps_applied"]


def test_hard_filing_without_accession_not_admissible():
    no_acc = tc.EvidenceItem("x", "filing", "EDGAR", "sec_filing",
                             tc.HARD_DATA, tc.FOR_THESIS, AS_OF,
                             source_mode=tc.SM_HARD_FILING,
                             source_hash="ab" * 16, is_fixture=False)
    assert tc.item_hard_admissible(no_acc) is False
    r = tc.grade(_research_with([no_acc]), AS_OF)
    assert r["evidence_mode_counts"]["hard_admissible"] == 0
    assert r["derived_data_mode"] == "ANALYST_PRIOR"
    assert r["authenticity_cap"] == 5.0


def test_derived_mode_ignores_declared_label():
    """Declared data_mode=LIVE with anecdote-only evidence derives
    ANECDOTE_ONLY — no manual override."""
    anec = tc.EvidenceItem("a", "story", "field", "field_observation",
                           tc.ANECDOTE, tc.FOR_THESIS, AS_OF,
                           is_fixture=False)
    r = tc.grade(_research_with([anec], data_mode=tc.LIVE), AS_OF)
    assert r["derived_data_mode"] == "ANECDOTE_ONLY"
    assert r["authenticity_cap"] == 3.0
    assert r["research_quality_score"] <= 3.0


def test_mixed_mode_from_two_verified_kinds():
    live = tc.EvidenceItem(
        "l", "live", "src", "prediction_market", tc.MARKET, tc.FOR_THESIS,
        AS_OF, source_mode=tc.SM_LIVE, source_uri_or_adapter="u",
        fetch_timestamp="t", adapter_name="a", adapter_run_id="r",
        source_hash="h1", is_fixture=False)
    hard = tc.EvidenceItem(
        "h", "filing", "EDGAR", "sec_filing", tc.HARD_DATA, tc.FOR_THESIS,
        AS_OF, source_mode=tc.SM_HARD_FILING, source_hash="h2",
        accession_or_filing_id="acc-1", is_fixture=False)
    r = tc.grade(_research_with([live, hard]), AS_OF)
    assert r["derived_data_mode"] == "MIXED"
    assert r["authenticity_cap"] == 10.0


def test_case_studies_cannot_feed_investability_families():
    """Case-study contracts contribute FVS, never investability inputs."""
    cs = tc.fixture_contract_strong(AS_OF)
    r = tc.grade(cs, AS_OF)
    assert r["derived_data_mode"] == "FIXTURE"
    assert r["investability_score"] == 0.0
    assert r["research_quality_score"] <= 3.0   # fixture demo cap
