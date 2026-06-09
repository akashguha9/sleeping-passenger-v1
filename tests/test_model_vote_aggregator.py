"""Stage 3 mechanical-aggregator math tests (deterministic, no model calls)."""
from __future__ import annotations

import pytest

from scripts.model_vote_aggregator import (
    CLASS_AVOID,
    CLASS_RISK_BLOCK,
    CLASS_WAIT,
    aggregate_model_lane_outputs,
    build_candidate_consensus_board,
    compute_concentration_penalty,
    compute_freshness_score,
    compute_manual_review_score,
    compute_model_agreement,
)

SESSION = "2026-06-07"


def _defense(grade: str = "CLEAN", score: float = 80.0) -> dict:
    return {
        "interpretation_defense_score": score,
        "interpretation_defense_grade": grade,
        "iqs": score,
        "iqs_grade": "HIGH",
        "mtr": 10.0,
        "stress_failure_risk": 0.0,
        "stress_grade": "ROBUST",
        "hard_blocks": [],
        "warnings": [],
    }


def _live_candidate(
    ticker: str,
    *,
    region: str = "UNKNOWN",
    theme: str = "UNKNOWN",
    defense: dict | None = None,
) -> dict:
    return {
        "ticker": ticker,
        "country": "UNKNOWN",
        "region": region,
        "sector": "UNKNOWN",
        "theme": theme,
        "source_health": "VERIFIED_LIVE",
        "is_live": True,
        "evidence_type": "LIVE_PRICE_MOVER",
        "live_evidence_count": 1,
        "last_live_seen_date": SESSION,
        "from_cache": False,
        "from_fallback": False,
        "from_moltbook": False,
        "from_trade_log": False,
        "allowed_in_fresh_discovery": True,
        "interpretation_defense": defense if defense is not None else _defense(),
    }


def _item(ticker, classification, evidence, confidence, contradiction="LOW", chaos="LOW") -> dict:
    return {
        "ticker": ticker,
        "classification": classification,
        "evidence_strength": evidence,
        "model_confidence": confidence,
        "contradiction_risk": contradiction,
        "chaos_risk": chaos,
    }


def _output(model, **lists) -> dict:
    base = {
        "model": model,
        "run_date": SESSION,
        "manual_consideration": [],
        "watch": [],
        "wait": [],
        "avoid": [],
        "risk_blocks": [],
        "rejected_due_to_missing_evidence": [],
        "model_confidence": "MEDIUM",
    }
    base.update(lists)
    return base


def _clean(candidates) -> dict:
    return {
        "run_date": SESSION,
        "fresh_discovery_status": "FRESH_DISCOVERY_OK",
        "candidates": candidates,
    }


# ---------------------------------------------------------------------------
# H. Deterministic five-model math.
# ---------------------------------------------------------------------------

def _five_outputs_for_pltr() -> list[dict]:
    manual = _item("PLTR", "MANUAL_CONSIDERATION", "HIGH", "HIGH")
    return [
        _output("gpt", manual_consideration=[manual]),
        _output("claude", manual_consideration=[manual]),
        _output("gemini", manual_consideration=[manual]),
        _output("grok", watch=[_item("PLTR", "WATCH", "MEDIUM", "MEDIUM")]),
        _output("mistral", avoid=[_item("PLTR", "AVOID", "LOW", "LOW", contradiction="MEDIUM", chaos="MEDIUM")]),
    ]


def test_H_agreement_components() -> None:
    outputs = _five_outputs_for_pltr()
    agreement = compute_model_agreement({"ticker": "PLTR"}, outputs)
    assert agreement["agreement"] == pytest.approx(0.8)        # 4/5 positive (3 manual + 1 watch)
    assert agreement["manual_support"] == pytest.approx(0.6)   # 3/5
    assert agreement["avoid_pressure"] == pytest.approx(0.2)   # 1/5
    assert agreement["reviewing_models"] == 5


def test_H_freshness_and_concentration() -> None:
    candidate = _live_candidate("PLTR")
    prov = {
        "source_health": "VERIFIED_LIVE",
        "is_live": True,
        "last_live_seen_date": SESSION,
        "run_date": SESSION,
    }
    assert compute_freshness_score(candidate, prov) == 1.0
    # Stale session -> 0.
    stale = dict(prov, last_live_seen_date="2026-06-01")
    assert compute_freshness_score(candidate, stale) == 0.0
    # UNKNOWN region/theme -> no concentration penalty.
    assert compute_concentration_penalty(candidate, [candidate, _live_candidate("X")]) == 0.0


def test_H_concentration_bands() -> None:
    us = [_live_candidate(t, region="US") for t in ("A", "B", "C", "D")]
    # 4/4 = 100% > 75% -> 0.45
    assert compute_concentration_penalty(us[0], us) == 0.45
    mixed = [
        _live_candidate("A", region="US"),
        _live_candidate("B", region="US"),
        _live_candidate("C", region="EU"),
        _live_candidate("D", region="JP"),
        _live_candidate("E", region="IN"),
    ]
    # US share 2/5 = 40% -> not > 40% -> 0.0
    assert compute_concentration_penalty(mixed[0], mixed) == 0.0


def test_H_manual_review_score_and_classification() -> None:
    outputs = _five_outputs_for_pltr()
    candidate = _live_candidate("PLTR")
    prov = {
        "source_health": "VERIFIED_LIVE",
        "is_live": True,
        "last_live_seen_date": SESSION,
        "allowed_in_fresh_discovery": True,
        "run_date": SESSION,
    }
    row = compute_manual_review_score(candidate, outputs, prov, 0.0)
    assert row["avg_evidence"] == pytest.approx(0.79)     # (3*1.0 + 0.65 + 0.30)/5
    assert row["avg_confidence"] == pytest.approx(0.79)
    assert row["avg_contradiction_risk"] == pytest.approx(0.07)  # 0.35/5
    assert row["avg_chaos_risk"] == pytest.approx(0.07)
    assert row["freshness"] == 1.0
    # New weighting with IDS component (0.17 * 0.80 = 0.136):
    # 0.18*0.8 + 0.14*0.6 + 0.14*0.79 + 0.10*0.79 + 0.12*1.0 + 0.17*0.80
    #   - 0.08*0.07 - 0.08*0.07 - 0.04*0.2 = 0.6544
    assert row["manual_review_score"] == pytest.approx(65.44, abs=1e-6)
    assert row["classification"] == CLASS_WAIT
    assert row["interpretation_defense_grade"] == "CLEAN"


def test_H_missing_interpretation_defense_risk_blocks() -> None:
    outputs = _five_outputs_for_pltr()
    candidate = _live_candidate("PLTR", defense=None)
    candidate.pop("interpretation_defense")
    prov = {"source_health": "VERIFIED_LIVE", "is_live": True,
            "last_live_seen_date": SESSION, "allowed_in_fresh_discovery": True, "run_date": SESSION}
    row = compute_manual_review_score(candidate, outputs, prov, 0.0)
    assert row["classification"] == CLASS_RISK_BLOCK
    assert any("interpretation_defense_missing" in o for o in row["hard_overrides"])


def test_H_ids_blocked_overrides_model_enthusiasm() -> None:
    outputs = _five_outputs_for_pltr()  # all bullish
    candidate = _live_candidate("PLTR", defense=_defense("BLOCKED", 10.0))
    prov = {"source_health": "VERIFIED_LIVE", "is_live": True,
            "last_live_seen_date": SESSION, "allowed_in_fresh_discovery": True, "run_date": SESSION}
    row = compute_manual_review_score(candidate, outputs, prov, 0.0)
    assert row["classification"] == CLASS_RISK_BLOCK


def test_H_ids_defensive_review_caps_at_wait() -> None:
    outputs = _five_outputs_for_pltr()
    candidate = _live_candidate("PLTR", defense=_defense("DEFENSIVE_REVIEW", 60.0))
    prov = {"source_health": "VERIFIED_LIVE", "is_live": True,
            "last_live_seen_date": SESSION, "allowed_in_fresh_discovery": True, "run_date": SESSION}
    row = compute_manual_review_score(candidate, outputs, prov, 0.0)
    assert row["classification"] in (CLASS_WAIT, CLASS_AVOID, CLASS_RISK_BLOCK)
    assert row["classification"] != "WATCH" and row["classification"] != "MANUAL_CONSIDERATION"


def test_H_clean_ids_improves_score_vs_missing() -> None:
    outputs = _five_outputs_for_pltr()
    prov = {"source_health": "VERIFIED_LIVE", "is_live": True,
            "last_live_seen_date": SESSION, "allowed_in_fresh_discovery": True, "run_date": SESSION}
    with_clean = compute_manual_review_score(_live_candidate("PLTR", defense=_defense("CLEAN", 95.0)), outputs, prov, 0.0)
    low = _live_candidate("PLTR", defense=_defense("CLEAN", 20.0))
    with_low = compute_manual_review_score(low, outputs, prov, 0.0)
    assert with_clean["manual_review_score"] > with_low["manual_review_score"]


def test_H_freshness_zero_forces_risk_block() -> None:
    outputs = _five_outputs_for_pltr()
    candidate = _live_candidate("PLTR")
    prov = {
        "source_health": "VERIFIED_LIVE",
        "is_live": True,
        "last_live_seen_date": "2026-06-01",  # stale -> freshness 0
        "allowed_in_fresh_discovery": True,
        "run_date": SESSION,
    }
    row = compute_manual_review_score(candidate, outputs, prov, 0.0)
    assert row["freshness"] == 0.0
    assert row["classification"] == CLASS_RISK_BLOCK


def test_H_non_verified_source_forces_risk_block() -> None:
    outputs = _five_outputs_for_pltr()
    candidate = dict(_live_candidate("PLTR"), source_health="OK")
    prov = {
        "source_health": "OK",
        "is_live": True,
        "last_live_seen_date": SESSION,
        "allowed_in_fresh_discovery": True,
        "run_date": SESSION,
    }
    row = compute_manual_review_score(candidate, outputs, prov, 0.0)
    assert row["classification"] == CLASS_RISK_BLOCK


def test_H_board_excludes_names_not_in_clean_payload() -> None:
    outputs = _five_outputs_for_pltr()
    clean = _clean([_live_candidate("PLTR")])
    board = build_candidate_consensus_board(outputs, clean)
    assert {r["ticker"] for r in board} == {"PLTR"}


def test_H_no_fresh_discovery_board_empty() -> None:
    clean = {"run_date": SESSION, "fresh_discovery_status": "NO_FRESH_DISCOVERY_GENERATED", "candidates": []}
    assert build_candidate_consensus_board(_five_outputs_for_pltr(), clean) == []
    agg = aggregate_model_lane_outputs(_five_outputs_for_pltr(), clean)
    assert agg["candidate_consensus"] == []
    assert agg["status"] == "NO_FRESH_DISCOVERY_GENERATED"


def test_H_aggregator_does_not_invent() -> None:
    # Outputs mention BOGUS, but it is not in the clean payload -> never ranked.
    outputs = [_output("gpt", manual_consideration=[_item("BOGUS", "MANUAL_CONSIDERATION", "HIGH", "HIGH")])]
    clean = _clean([_live_candidate("PLTR")])
    agg = aggregate_model_lane_outputs(outputs, clean)
    assert {r["ticker"] for r in agg["candidate_consensus"]} == {"PLTR"}
