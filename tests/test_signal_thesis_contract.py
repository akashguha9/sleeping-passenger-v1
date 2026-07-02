"""Belief Escrow invariants: the contract engine cannot be talked past."""
from __future__ import annotations

from pathlib import Path

from scripts import signal_thesis_contract as tc


AS_OF = 1000


def _base_contract(**overrides) -> tc.ThesisContract:
    c = tc.fixture_contract_strong(AS_OF)
    for k, v in overrides.items():
        setattr(c, k, v)
    return c


def test_final_never_exceeds_evidence_cap():
    """I2: high merit + thin evidence => FIS pinned at 10*EQS."""
    c = _base_contract()
    c.evidence = [tc.EvidenceItem("only", "one market datum", "pm",
                                  "prediction_market", tc.MARKET,
                                  tc.FOR_THESIS, AS_OF - 1)]
    c.merit_inputs = {"awareness_gap": 9.5, "house_layer": 9.5,
                      "infra_capture": 9.0}
    r = tc.grade(c, AS_OF)
    assert r["final_score"] <= 10.0 * r["evidence_quality"] + 1e-9
    assert "EVIDENCE_QUALITY_CAP" in r["caps_applied"]


def test_final_never_exceeds_merit():
    """I1: gates only demote."""
    c = _base_contract()
    r = tc.grade(c, AS_OF)
    assert r["final_score"] <= r["merit"]["merit"] + 1e-9


def test_unfalsifiable_thesis_is_capped_and_insufficient():
    """I3: no falsification observable => FIS<=4 and INSUFFICIENT_EVIDENCE."""
    c = _base_contract(falsification_observable="   ")
    r = tc.grade(c, AS_OF)
    assert r["final_score"] <= tc.UNFALSIFIABLE_SCORE_CAP
    assert r["verdict"] == tc.V_INSUFFICIENT_EVIDENCE
    c2 = _base_contract(expiry_day=_base_contract().created_day)  # no expiry
    r2 = tc.grade(c2, AS_OF)
    assert r2["verdict"] == tc.V_INSUFFICIENT_EVIDENCE


def test_anecdote_only_thesis_cannot_become_strong_buy():
    """I5: anecdote-only evidence never clears the EQS floor."""
    c = tc.fixture_contract_anecdote_only(AS_OF)
    r = tc.grade(c, AS_OF)
    assert r["evidence_quality"] < tc.EQS_INSUFFICIENT_FLOOR
    assert r["verdict"] == tc.V_INSUFFICIENT_EVIDENCE
    assert r["verdict"] != tc.V_STRONG_BUY


def test_contradiction_lowers_score():
    """I4: adding FOR_NULL evidence strictly lowers FIS via g_contra."""
    clean = _base_contract()
    base = tc.grade(clean, AS_OF)
    contradicted = _base_contract()
    contradicted.evidence = list(contradicted.evidence) + [
        tc.EvidenceItem("ev-null-1", "Partner volume disclosed FLAT",
                        "earnings call", "earnings_call", tc.HARD_DATA,
                        tc.FOR_NULL, AS_OF - 2)]
    worse = tc.grade(contradicted, AS_OF)
    assert worse["discrimination"]["g_contra"] < base["discrimination"]["g_contra"]
    assert worse["final_score"] < base["final_score"]


def test_neutral_evidence_carries_no_discrimination_weight():
    c = _base_contract()
    before = tc.discrimination(c, AS_OF)
    c.evidence = list(c.evidence) + [
        tc.EvidenceItem("ev-neutral", "Company exists", "wiki", "news",
                        tc.HARD_DATA, tc.NEUTRAL, AS_OF)]
    after = tc.discrimination(c, AS_OF)
    assert after["net_discrimination"] == before["net_discrimination"]


def test_stale_evidence_decays():
    c = _base_contract()
    fresh = tc.grade(c, AS_OF)
    later = tc.grade(c, AS_OF + 400)
    assert later["evidence_quality"] < fresh["evidence_quality"]
    assert later["g_stale"] < fresh["g_stale"]
    assert later["final_score"] < fresh["final_score"]


def test_ecology_half_life_orders_decay():
    tik = tc.EvidenceItem("t", "x", "s", "tiktok", tc.MARKET, tc.FOR_THESIS, 0)
    fil = tc.EvidenceItem("f", "x", "s", "sec_filing", tc.MARKET,
                          tc.FOR_THESIS, 0)
    assert tc.freshness(tik, 30) < tc.freshness(fil, 30)


def test_anecdote_promotion_requires_independent_hard_corroboration():
    c = tc.fixture_contract_anecdote_only(AS_OF)
    anec = c.evidence[0]
    assert tc.item_weight(anec, c) == tc.PROVENANCE_WEIGHTS[tc.ANECDOTE]
    c.evidence = list(c.evidence) + [
        tc.EvidenceItem("ev-hard", "Filing confirms the same claim",
                        "EDGAR", "sec_filing", tc.HARD_DATA, tc.FOR_THESIS,
                        AS_OF - 1)]
    assert tc.item_weight(anec, c) == tc.ANECDOTE_CORROBORATED_WEIGHT


def test_strong_fixture_grades_high_but_capped_by_evidence():
    c = _base_contract()
    r = tc.grade(c, AS_OF)
    assert r["falsifiable"] is True
    # fixture-strong is a FIXTURE_TEST: verdicts are framework-scoped now
    assert r["verdict"] in tc.CASE_STUDY_ALLOWED_VERDICTS
    assert r["verdict"] not in tc.INVESTMENT_VERDICTS
    assert 0.0 < r["final_score"] <= 10.0
    assert r["investability_score"] == 0.0


def test_resolution_is_system_graded(tmp_path: Path):
    c = _base_contract()
    pre = tc.resolve(c, AS_OF)                       # before expiry: no-op
    assert pre["resolved"] is False
    rec = tc.resolve(c, c.expiry_day, realized_return=0.08)
    assert rec["status"] == tc.VALIDATED
    c2 = _base_contract()
    rec2 = tc.resolve(c2, c2.expiry_day, realized_return=-0.05)
    assert rec2["status"] == tc.FALSIFIED
    c3 = _base_contract()
    rec3 = tc.resolve(c3, c3.expiry_day)             # no outcome attached
    assert rec3["status"] == tc.EXPIRED
    cemetery = tmp_path / "thesis_cemetery.jsonl"
    tc.append_cemetery(cemetery, rec)
    tc.append_cemetery(cemetery, rec2)
    assert len(cemetery.read_text(encoding="utf-8").splitlines()) == 2


def test_contract_json_roundtrip(tmp_path: Path):
    c = _base_contract()
    p = tmp_path / "contract.json"
    tc.save_contract(c, p)
    back = tc.load_contract(p)
    assert back.to_dict() == c.to_dict()
    assert tc.grade(back, AS_OF) == tc.grade(c, AS_OF)


def test_advisory_stamps_present():
    r = tc.grade(_base_contract(), AS_OF)
    assert r["advisory_status"] == "ADVISORY_ONLY"
    assert r["real_money"] == "PROHIBITED"
