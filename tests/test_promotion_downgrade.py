"""Tests for the promotion_downgrade decision module."""
from __future__ import annotations

from scripts import live_payload_quality as lpq
from scripts import promotion_downgrade as pd


def _healthy_lpq():
    providers = [
        {"provider": "p", "source_class": "price",
         "status": lpq.STATUS_HEALTHY,
         "verification_status": lpq.VERIF_VERIFIED, "age_hours": 1.0},
        {"provider": "s", "source_class": "filings",
         "status": lpq.STATUS_HEALTHY,
         "verification_status": lpq.VERIF_VERIFIED,
         "age_hours": 1.0, "sla_hours": 72.0},
        {"provider": "g", "source_class": "news_event",
         "status": lpq.STATUS_HEALTHY,
         "verification_status": lpq.VERIF_VERIFIED, "age_hours": 1.0},
    ]
    return lpq.compute_lpq(providers, ai_required=False)


def _stale_price_lpq():
    providers = [
        {"provider": "p", "source_class": "price",
         "status": lpq.STATUS_STALE,
         "verification_status": lpq.VERIF_STALE, "age_hours": 72.0},
        {"provider": "s", "source_class": "filings",
         "status": lpq.STATUS_HEALTHY,
         "verification_status": lpq.VERIF_VERIFIED,
         "age_hours": 1.0, "sla_hours": 72.0},
        {"provider": "g", "source_class": "news_event",
         "status": lpq.STATUS_HEALTHY,
         "verification_status": lpq.VERIF_VERIFIED, "age_hours": 1.0},
    ]
    return lpq.compute_lpq(providers, ai_required=False)


def test_strong_cqs_with_stale_price_does_not_promote():
    decision = pd.decide_promotion(
        cqs_raw=0.92,
        why_today_score=0.85,
        lpq_summary=_stale_price_lpq(),
    )
    assert decision["promoted"] is False
    assert "PRICE_SOURCE_STALE" in decision["downgrade_reasons"]
    assert decision["state"] != "ADVISORY_CANDIDATE_HUMAN_REVIEW"


def test_strong_cqs_with_healthy_sources_promotes():
    decision = pd.decide_promotion(
        cqs_raw=0.92,
        why_today_score=0.85,
        lpq_summary=_healthy_lpq(),
    )
    assert decision["state"] == "ADVISORY_CANDIDATE_HUMAN_REVIEW"
    assert decision["promoted"] is True
    assert decision["execution_permission"] == "ADVISORY_ONLY"
    assert decision["broker_api_called"] is False


def test_diablo_veto_blocks_promotion():
    decision = pd.decide_promotion(
        cqs_raw=0.92,
        why_today_score=0.85,
        lpq_summary=_healthy_lpq(),
        diablo_veto=True,
    )
    assert decision["state"] == "DIABLO_REVIEW"
    assert decision["promoted"] is False
    assert "DIABLO_MODEL_VETO" in decision["downgrade_reasons"]


def test_high_model_disagreement_routes_to_research():
    decision = pd.decide_promotion(
        cqs_raw=0.92,
        why_today_score=0.85,
        lpq_summary=_healthy_lpq(),
        model_disagreement=0.75,
    )
    assert decision["state"] == "RESEARCH_CANDIDATE"
    assert "MODEL_DISAGREEMENT_HIGH" in decision["downgrade_reasons"]


def test_weak_why_today_drops_state():
    decision = pd.decide_promotion(
        cqs_raw=0.92,
        why_today_score=0.20,
        lpq_summary=_healthy_lpq(),
    )
    assert decision["promoted"] is False
    assert "WHY_TODAY_WEAK" in decision["downgrade_reasons"]


def test_advisory_invariants_always_set():
    decision = pd.decide_promotion(
        cqs_raw=0.5, why_today_score=0.5,
        lpq_summary=_healthy_lpq(),
    )
    assert decision["advisory_only"] is True
    assert decision["human_review_required"] is True
    assert decision["execution_permission"] == "ADVISORY_ONLY"
    assert decision["execution_gate"] == "LOCKED"
