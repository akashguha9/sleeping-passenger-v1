"""Tests for live payload quality + downgrade reasons."""
from __future__ import annotations

from scripts import live_payload_quality as lpq


def _provider(provider, source_class, *, status, verification,
              age_hours=1.0, sla_hours=24.0):
    return {
        "provider": provider,
        "source_class": source_class,
        "status": status,
        "verification_status": verification,
        "age_hours": age_hours,
        "sla_hours": sla_hours,
    }


def test_freshness_score_halves_at_sla():
    val = lpq.freshness_score(24, 24)
    assert 0.49 <= val <= 0.51


def test_freshness_score_none_age_returns_zero():
    assert lpq.freshness_score(None, 24) == 0.0


def test_lpq_full_verified_passes_threshold():
    providers = [
        _provider("yfinance", "price", status=lpq.STATUS_HEALTHY,
                  verification=lpq.VERIF_VERIFIED, age_hours=0.5),
        _provider("sec_edgar", "filings", status=lpq.STATUS_HEALTHY,
                  verification=lpq.VERIF_VERIFIED, age_hours=2.0,
                  sla_hours=72.0),
        _provider("gdelt", "news_event", status=lpq.STATUS_HEALTHY,
                  verification=lpq.VERIF_VERIFIED, age_hours=1.0),
    ]
    out = lpq.compute_lpq(providers, ai_required=False)
    assert out["lpq_above_threshold"] is True
    assert out["m_live"] == 1.00
    assert out["downgrade_reasons"] == []


def test_fallback_blocks_promotion_via_mlive():
    providers = [
        _provider("yfinance", "price", status=lpq.STATUS_FALLBACK,
                  verification=lpq.VERIF_FALLBACK, age_hours=10.0),
        _provider("sec_edgar", "filings", status=lpq.STATUS_HEALTHY,
                  verification=lpq.VERIF_VERIFIED, age_hours=2.0,
                  sla_hours=72.0),
        _provider("gdelt", "news_event", status=lpq.STATUS_HEALTHY,
                  verification=lpq.VERIF_VERIFIED, age_hours=1.0),
    ]
    out = lpq.compute_lpq(providers, ai_required=False)
    assert out["m_live"] == 0.35
    assert "PRICE_SOURCE_FALLBACK" in out["downgrade_reasons"]


def test_stale_news_marks_downgrade():
    providers = [
        _provider("yfinance", "price", status=lpq.STATUS_HEALTHY,
                  verification=lpq.VERIF_VERIFIED, age_hours=1.0),
        _provider("sec_edgar", "filings", status=lpq.STATUS_HEALTHY,
                  verification=lpq.VERIF_VERIFIED, age_hours=2.0,
                  sla_hours=72.0),
        _provider("gdelt", "news_event", status=lpq.STATUS_STALE,
                  verification=lpq.VERIF_STALE, age_hours=72.0),
    ]
    out = lpq.compute_lpq(providers, ai_required=False)
    assert "NEWS_SOURCE_STALE" in out["downgrade_reasons"]
    assert out["m_live"] <= 0.50


def test_ai_missing_not_required_does_not_downgrade():
    providers = [
        _provider("yfinance", "price", status=lpq.STATUS_HEALTHY,
                  verification=lpq.VERIF_VERIFIED, age_hours=1.0),
        _provider("sec_edgar", "filings", status=lpq.STATUS_HEALTHY,
                  verification=lpq.VERIF_VERIFIED, age_hours=2.0,
                  sla_hours=72.0),
        _provider("gdelt", "news_event", status=lpq.STATUS_HEALTHY,
                  verification=lpq.VERIF_VERIFIED, age_hours=1.0),
    ]
    out = lpq.compute_lpq(providers, ai_required=False)
    assert "AI_REPORT_SOURCE_MISSING" not in out["downgrade_reasons"]


def test_ai_missing_when_required_adds_reason():
    providers = [
        _provider("yfinance", "price", status=lpq.STATUS_HEALTHY,
                  verification=lpq.VERIF_VERIFIED, age_hours=1.0),
        _provider("sec_edgar", "filings", status=lpq.STATUS_HEALTHY,
                  verification=lpq.VERIF_VERIFIED, age_hours=2.0,
                  sla_hours=72.0),
        _provider("gdelt", "news_event", status=lpq.STATUS_HEALTHY,
                  verification=lpq.VERIF_VERIFIED, age_hours=1.0),
    ]
    out = lpq.compute_lpq(providers, ai_required=True)
    assert "AI_REPORT_SOURCE_MISSING" in out["downgrade_reasons"]


def test_mock_overrides_to_lowest_multiplier():
    providers = [
        _provider("p", "price", status=lpq.STATUS_MOCK,
                  verification=lpq.VERIF_MOCK, age_hours=1.0),
        _provider("g", "filings", status=lpq.STATUS_HEALTHY,
                  verification=lpq.VERIF_VERIFIED, age_hours=1.0,
                  sla_hours=72.0),
        _provider("n", "news_event", status=lpq.STATUS_HEALTHY,
                  verification=lpq.VERIF_VERIFIED, age_hours=1.0),
    ]
    out = lpq.compute_lpq(providers)
    assert out["m_live"] == 0.20


def test_safety_stamps_present():
    out = lpq.compute_lpq([])
    assert out["advisory_status"] == "ADVISORY_ONLY"
    assert out["execution_gate"] == "LOCKED"
