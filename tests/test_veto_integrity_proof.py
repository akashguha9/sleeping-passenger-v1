"""Tests for the DIABLO / chaos-veto integrity proof pack (WORKSTREAM E)."""
from __future__ import annotations

import pytest

from scripts import veto_integrity_proof as vip


def test_veto_integrity_proof_diablo_blocks_positive_external_delta() -> None:
    proof = vip.build_veto_integrity_proof(
        {
            "base_score": 6.0,
            "external_evidence_delta": 0.5,  # mature high-weight positive boost
            "veto_type": "DIABLO",
            "base_class": "DIABLO",
        }
    )
    assert proof["veto_present"] is True
    assert proof["veto_type"] == vip.VETO_DIABLO
    assert proof["external_evidence_attempted_boost"] is True
    assert proof["boost_blocked"] is True
    # S_final = min(S_candidate, S_base) -> capped at base.
    assert proof["final_score_after_veto"] == pytest.approx(6.0)
    assert proof["score_capped"] is True
    assert proof["proof_status"] == vip.PROOF_BLOCKED


def test_veto_integrity_proof_no_new_risk_blocks_positive_external_delta() -> None:
    proof = vip.build_veto_integrity_proof(
        {
            "base_score": 5.0,
            "external_evidence_delta": 0.5,
            "no_new_risk": True,
            "base_class": "NO_NEW_RISK",
        }
    )
    assert proof["veto_type"] == vip.VETO_NO_NEW_RISK
    assert proof["boost_blocked"] is True
    assert proof["final_score_after_veto"] == pytest.approx(5.0)


def test_veto_integrity_class_preserved() -> None:
    proof = vip.build_veto_integrity_proof(
        {
            "base_score": 7.0,
            "external_evidence_delta": 0.4,
            "veto_type": "CHAOS_VETO",
            "base_class": "CHAOS_VETO",
        }
    )
    assert proof["class_preserved"] is True
    assert proof["final_class"] == "CHAOS_VETO"
    assert proof["veto_type"] == vip.VETO_CHAOS


def test_veto_integrity_human_review_required() -> None:
    proof = vip.build_veto_integrity_proof({"base_score": 5.0, "veto_type": "DIABLO"})
    assert proof["human_review_required"] is True
    assert proof["execution_gate"] == "LOCKED"
    assert proof["broker_api_called"] is False
    assert proof["ai_execution_count"] == 0
    assert proof["real_money_sizing_impact"] == "PROHIBITED"


def test_fake_confidence_high_cannot_boost_under_veto() -> None:
    proof = vip.build_veto_integrity_proof(
        {
            "base_score": 5.0,
            "external_evidence_delta": 0.5,
            "veto_type": "DIABLO",
            "base_class": "DIABLO",
            "fake_confidence_label": "HIGH_FAKE_CONFIDENCE_RISK",
        }
    )
    # Both the fake-confidence neutraliser AND the veto block the boost.
    assert proof["fake_confidence_boost_blocked"] is True
    assert proof["boost_blocked"] is True
    assert proof["external_evidence_delta_effective"] == 0.0
    assert proof["final_score_after_veto"] == pytest.approx(5.0)


def test_no_veto_allows_clamped_positive_delta() -> None:
    proof = vip.build_veto_integrity_proof(
        {"base_score": 5.0, "external_evidence_delta": 0.4, "base_class": "WATCHLIST"}
    )
    assert proof["veto_present"] is False
    assert proof["final_score_after_veto"] == pytest.approx(5.4)
    assert proof["boost_blocked"] is False
    assert proof["proof_status"] == vip.PROOF_CLEAR
