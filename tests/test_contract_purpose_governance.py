"""Purpose governance: case studies can never be mistaken for candidates."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts import signal_thesis_card_report as card
from scripts import signal_thesis_contract as tc

AS_OF = 1000


def _case_study(**overrides) -> tc.ThesisContract:
    """A case study with deliberately strong-buy-grade inputs — the point is
    that none of that strength may leak into investability."""
    base = tc.fixture_contract_strong(AS_OF)
    d = base.to_dict()
    d["thesis_id"] = "cs-test-0001"
    d["contract_purpose"] = tc.CASE_STUDY
    d["investment_eligibility"] = ""
    d["promotion_status"] = ""
    d["board_scope"] = ""
    d["trading_status"] = ""
    d.update(overrides)
    return tc.ThesisContract.from_dict(d)


def _hard(eid: str, claim: str, source: str, ecology: str,
          day: int) -> tc.EvidenceItem:
    """HARD_FILING item with full authenticity metadata (accession + hash) so
    it is hard-admissible under verified counting."""
    return tc.EvidenceItem(
        eid, claim, source, ecology, tc.HARD_DATA, tc.FOR_THESIS, day,
        source_mode=tc.SM_HARD_FILING,
        source_uri_or_adapter="https://www.sec.gov/fixture-filing",
        fetch_timestamp="2026-07-02T00:00:00Z", adapter_name="test_fixture",
        adapter_run_id="run-test-0001",
        source_hash="deadbeef" * 4,
        accession_or_filing_id=f"0000000000-26-{eid}", is_fixture=False)


def _passing_research() -> tc.ThesisContract:
    ev = [
        _hard("r-h1", "filing discloses take-rate share", "EDGAR",
              "sec_filing", AS_OF - 5),
        _hard("r-h2", "regulator record confirms license scope",
              "regulator", "regulatory", AS_OF - 8),
        _hard("r-h3", "second filing names partner revenue", "EDGAR",
              "sec_filing", AS_OF - 10),
        tc.EvidenceItem("r-m1", "transcript take-rate language",
                        "transcript", "earnings_call", tc.MARKET,
                        tc.FOR_THESIS, AS_OF - 6),
        tc.EvidenceItem("r-m2", "fee page cut confirmed", "pricing page",
                        "pricing_page", tc.MARKET, tc.FOR_THESIS, AS_OF - 4),
        tc.EvidenceItem("r-m3", "event market ΔP persistent", "polymarket",
                        "prediction_market", tc.MARKET, tc.FOR_THESIS,
                        AS_OF - 2),
        tc.EvidenceItem("r-m4", "traffic panel confirms adoption",
                        "web traffic", "web_traffic", tc.MARKET,
                        tc.FOR_THESIS, AS_OF - 3),
    ]
    return tc.ThesisContract(
        thesis_id="research-pass-0001", title="Passing research thesis",
        entity="ResearchCo", ticker="RSRCH", narrative="n", trigger="t",
        predicted_direction="UP", horizon_days=90, created_day=AS_OF - 10,
        expiry_day=AS_OF + 80,
        falsification_observable="metric X below Y by expiry",
        forced_null_thesis="growth is base-rate only",
        causal_path=["a", "b", "c", "d"],
        beneficiary_map={"house": ["RSRCH"], "mid": ["M"], "losers": ["L"]},
        evidence=ev,
        merit_inputs={"awareness_gap": 8.0, "long_tail_demand": 8.0,
                      "house_layer": 9.0, "infra_capture": 8.5,
                      "transaction_certainty": 8.5,
                      "narrative_transmission": 8.5},
        data_mode=tc.LIVE, contract_purpose=tc.LIVE_RESEARCH,
    )


# --- contract purpose tests (1-6) ----------------------------------------------

def test_case_study_defaults_to_not_eligible():
    c = _case_study()
    assert c.investment_eligibility == "NOT_ELIGIBLE"
    assert c.promotion_status == "NOT_PROMOTABLE"
    assert c.board_scope == "CASE_STUDY_BOARD"
    assert c.trading_status == "DO_NOT_TRADE"
    assert c.case_study_disclaimer  # auto-attached


def test_case_study_investability_is_zero():
    r = tc.grade(_case_study(), AS_OF)
    assert r["investability_score"] == 0.0
    assert r["eligibility_multiplier"] == 0.0


def test_fixture_test_investability_is_zero():
    r = tc.grade(tc.fixture_contract_strong(AS_OF), AS_OF)
    assert r["investability_score"] == 0.0


def test_live_research_cannot_sit_on_candidate_board():
    research = _passing_research()
    research.board_scope = "INVESTABLE_CANDIDATE_BOARD"
    with pytest.raises(ValueError, match="BOARD_ROUTING_VIOLATION"):
        tc.validate_purpose_routing(research)


def test_investable_candidate_requires_promotion_lineage():
    with pytest.raises(ValueError, match="UNPROMOTED_INVESTABLE_CANDIDATE"):
        tc.ThesisContract(
            thesis_id="forged", title="t", entity="e", ticker="X",
            narrative="n", trigger="t", predicted_direction="UP",
            horizon_days=10, created_day=1, expiry_day=20,
            falsification_observable="f", forced_null_thesis="n",
            contract_purpose=tc.INVESTABLE_CANDIDATE)


def test_missing_contract_purpose_fails_closed():
    with pytest.raises(ValueError, match="CONTRACT_PURPOSE_MISSING"):
        tc.ThesisContract(
            thesis_id="x", title="t", entity="e", ticker="X", narrative="n",
            trigger="t", predicted_direction="UP", horizon_days=10,
            created_day=1, expiry_day=20, falsification_observable="f",
            forced_null_thesis="n")
    d = tc.fixture_contract_strong(AS_OF).to_dict()
    del d["contract_purpose"]
    with pytest.raises(ValueError, match="CONTRACT_PURPOSE_MISSING"):
        tc.ThesisContract.from_dict(d)


# --- board routing tests (7-11) --------------------------------------------------

def test_purpose_board_routing():
    assert card.route_board(_case_study()) == "CASE_STUDY_BOARD"
    assert card.route_board(_passing_research()) == "RESEARCH_BOARD"
    promoted = tc.promote_research_to_investable(
        _passing_research(), approval_note="ok", as_of_day=AS_OF)
    assert promoted["promoted"] is True
    assert card.route_board(promoted["contract"]) == "INVESTABLE_CANDIDATE_BOARD"
    dead = _passing_research()
    tc.resolve(dead, dead.expiry_day, realized_return=-0.10)
    assert dead.contract_purpose == tc.FALSIFIED_PURPOSE
    assert card.route_board(dead) == "ARCHIVE"


def test_board_contamination_raises():
    contaminated = _case_study()
    contaminated.board_scope = "INVESTABLE_CANDIDATE_BOARD"
    with pytest.raises(ValueError, match="BOARD_ROUTING_VIOLATION"):
        card.build_boards([(contaminated, tc.grade(_case_study(), AS_OF))])


# --- verdict restriction tests (12-16) -------------------------------------------

def test_case_study_never_gets_investment_verdict():
    r = tc.grade(_case_study(), AS_OF)
    assert r["verdict"] in tc.CASE_STUDY_ALLOWED_VERDICTS
    assert r["verdict"] not in tc.INVESTMENT_VERDICTS


def test_fixture_test_never_gets_investment_verdict():
    r = tc.grade(tc.fixture_contract_strong(AS_OF), AS_OF)
    assert r["verdict"] in tc.CASE_STUDY_ALLOWED_VERDICTS


def test_case_study_card_prints_not_investable_banner():
    c = _case_study()
    md = card.render_thesis_card(c, tc.grade(c, AS_OF), AS_OF)
    assert "CASE STUDY ONLY — NOT INVESTABLE" in md
    assert "DO NOT TRADE" in md
    assert "INVESTABILITY STATUS: NOT ELIGIBLE" in md


def test_research_board_prints_not_a_buy_list_banner():
    research = _passing_research()
    boards = card.build_boards([(research, tc.grade(research, AS_OF))])
    md = card.render_board_markdown(boards)
    assert "RESEARCH ONLY — NOT A BUY LIST" in md["RESEARCH_BOARD"]


def test_empty_investable_board_reports_success():
    boards = card.build_boards([])
    md = card.render_board_markdown(boards)
    assert ("No investable candidates currently promoted. System is working "
            "correctly.") in md["INVESTABLE_CANDIDATE_BOARD"]


# --- promotion workflow tests (17-23) ---------------------------------------------

def test_case_study_cannot_be_edited_in_place_to_candidate():
    c = _case_study()
    c.contract_purpose = tc.INVESTABLE_CANDIDATE  # forged in-place edit
    with pytest.raises(ValueError, match="BOARD_ROUTING_VIOLATION"):
        tc.grade(c, AS_OF)   # routing still says CASE_STUDY_BOARD -> raises


def test_case_study_promotion_creates_new_contract_with_lineage():
    cs = _case_study()
    research = tc.promote_case_study_to_research(
        cs, day=AS_OF, expiry_day=AS_OF + 90,
        falsification_observable="new observable", rationale="worth research")
    assert research.thesis_id != cs.thesis_id
    assert research.parent_case_study_id == cs.thesis_id
    assert research.contract_purpose == tc.LIVE_RESEARCH
    assert research.trading_status == "PAPER_RESEARCH_ONLY"
    assert research.evidence == []      # research earns its own evidence


def test_promotion_fails_without_eqs():
    weak = _passing_research()
    weak.evidence = weak.evidence[:1]
    result = tc.promote_research_to_investable(
        weak, approval_note="try", as_of_day=AS_OF)
    assert result["promoted"] is False
    assert any(b.startswith("EQS_BELOW") for b in result["blockers"])


def test_promotion_fails_if_fixture_only():
    fixture = _passing_research()
    fixture.data_mode = tc.FIXTURE_DEMONSTRATION
    result = tc.promote_research_to_investable(
        fixture, approval_note="try", as_of_day=AS_OF)
    assert result["promoted"] is False
    assert "FIXTURE_ONLY_EVIDENCE" in result["blockers"]


def test_promotion_fails_if_anecdote_only():
    anec = tc.fixture_contract_anecdote_only(AS_OF)
    result = tc.promote_research_to_investable(
        anec, approval_note="try", as_of_day=AS_OF)
    assert result["promoted"] is False
    assert "ANECDOTE_ONLY_EVIDENCE" in result["blockers"]


def test_promotion_fails_on_banned_retrocast_category():
    result = tc.promote_research_to_investable(
        _passing_research(), approval_note="try", as_of_day=AS_OF,
        retrocast_category_status="BANNED_NO_TRANSMISSION")
    assert result["promoted"] is False
    assert any("RETROCAST_CATEGORY" in b for b in result["blockers"])


def test_promotion_succeeds_when_all_requirements_pass():
    research = _passing_research()
    result = tc.promote_research_to_investable(
        research, approval_note="approved", as_of_day=AS_OF)
    assert result["promoted"] is True, result
    cand = result["contract"]
    assert cand.contract_purpose == tc.INVESTABLE_CANDIDATE
    assert cand.promotion_status == "PROMOTED"
    assert cand.parent_research_id == "research-pass-0001"
    assert cand.thesis_id != "research-pass-0001"
    lineage = tc.verify_lineage(cand, research)
    assert lineage["valid"] is True, lineage
    r = tc.grade(cand, AS_OF, lineage_valid=lineage["valid"])
    assert r["derived_data_mode"] == "HARD"
    assert r["investability_score"] == r["research_quality_score"]  # mult 1.0
    assert r["investability_score"] >= 7.0
    # without lineage verification the same candidate fails closed
    r0 = tc.grade(cand, AS_OF)
    assert r0["investability_score"] == 0.0
    assert "LINEAGE_UNVERIFIED_FAIL_CLOSED" in r0["caps_applied"]


# --- score invariant tests (24-29) -----------------------------------------------

def test_score_invariants_hold_for_all_purposes():
    for c in (_case_study(), _passing_research(),
              tc.fixture_contract_strong(AS_OF)):
        r = tc.grade(c, AS_OF)
        assert r["final_score"] <= 10 * r["evidence_quality"] + 1e-9
        assert r["final_score"] <= r["merit"]["merit"] + 1e-9


def test_case_study_investability_zero_even_with_max_inputs():
    c = _case_study()
    c.merit_inputs = {k: 10.0 for k in
                      ("awareness_gap", "decision_moment_capture",
                       "long_tail_demand", "house_layer", "infra_capture",
                       "transaction_certainty", "narrative_transmission")}
    assert tc.grade(c, AS_OF)["investability_score"] == 0.0


def test_research_quality_nonzero_while_investability_zero():
    r = tc.grade(tc.fixture_contract_strong(AS_OF), AS_OF)
    assert r["research_quality_score"] > 0
    assert r["investability_score"] == 0.0


def test_framework_validation_high_while_investability_zero():
    r = tc.grade(_case_study(), AS_OF)
    assert r["framework_validation_score"] >= 8.0
    assert r["investability_score"] == 0.0


def test_unpromoted_research_investability_is_quartered():
    research = _passing_research()
    r = tc.grade(research, AS_OF)
    assert r["eligibility_multiplier"] == 0.25
    assert r["investability_score"] == round(0.25 * r["final_score"], 3)
    assert r["verdict"] not in tc.INVESTMENT_VERDICTS


# --- regression (32): live mode never silently falls back to fixture ------------

def test_cli_refuses_to_run_without_explicit_mode():
    """--mode {fixture,live/real} is REQUIRED: there is no default mode, so
    a live failure can never silently become a fixture run."""
    for module in ("scripts.retrocast_calibration",
                   "scripts.prediction_market_shock_engine"):
        proc = subprocess.run(
            [sys.executable, "-m", module],  # no --mode
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parents[1]))
        assert proc.returncode != 0
        assert "--mode" in (proc.stderr + proc.stdout)
