"""Tests — LIVE_VERIFIED proof pack (deterministic, pure).

Kanté Ceiling Push II, Workstream E.  Proves mock→MOCK_ONLY, stale→STALE,
a fully-safe fresh source→LIVE_VERIFIED, that LIVE_VERIFIED never relaxes the
real-money prohibition, and that missing secret redaction blocks verification.
"""
from __future__ import annotations

import pytest

from scripts.live_verified_proof_pack import (
    LABEL_LIVE_VERIFIED,
    LABEL_MOCK_ONLY,
    LABEL_STALE,
    build_live_verified_proof_pack,
)


def _safe_fresh_source(**overrides):
    src = {
        "source_name": "kalshi",
        "configured": True,
        "enabled": True,
        "mock_mode": False,
        "rows_seen": 100,
        "rows_accepted": 100,
        "canonical_rows_written": 100,
        "last_fresh_signal_at_utc": "2026-05-30T00:00:00Z",
        "freshness_age_hours": 0.5,
        "freshness_ttl_hours": 24.0,
        "advisory_only": True,
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
        "decision_impact": "ADVISORY_CONTEXT_ONLY",
        "secrets_redacted": True,
        "no_execution_language": True,
        "provider_error": None,
    }
    src.update(overrides)
    return src


# --- 1 ----------------------------------------------------------------------
def test_live_verified_proof_mock_only():
    pack = build_live_verified_proof_pack(_safe_fresh_source(mock_mode=True))
    assert pack["proof_label"] == LABEL_MOCK_ONLY
    assert pack["live_verified"] is False
    assert pack["non_mock_score"] == 0.0


# --- 2 ----------------------------------------------------------------------
def test_live_verified_proof_stale():
    pack = build_live_verified_proof_pack(
        _safe_fresh_source(freshness_age_hours=72.0, freshness_ttl_hours=24.0)
    )
    assert pack["proof_label"] == LABEL_STALE
    assert pack["live_verified"] is False
    assert pack["freshness_score"] == 0.0


# --- 3 ----------------------------------------------------------------------
def test_live_verified_proof_safe_fresh_verified():
    pack = build_live_verified_proof_pack(_safe_fresh_source())
    assert pack["proof_label"] == LABEL_LIVE_VERIFIED
    assert pack["live_verified"] is True
    assert pack["blockers"] == []
    # Graded freshness: a 0.5h-old source is fresh but not "just now".
    assert pack["live_verification_readiness_score"] >= 0.95


# --- 4 ----------------------------------------------------------------------
def test_live_verified_proof_real_money_prohibited():
    pack = build_live_verified_proof_pack(_safe_fresh_source())
    assert pack["live_verified"] is True
    assert pack["real_money_sizing_impact"] == "PROHIBITED"
    assert pack["real_money_weight_allowed"] is False
    assert pack["live_verified_is_execution_readiness"] is False
    assert pack["execution_gate"] == "LOCKED"
    assert pack["broker_api_called"] is False
    assert pack["ai_execution_count"] == 0


# --- 5 ----------------------------------------------------------------------
def test_live_verified_secret_redaction_blocks():
    pack = build_live_verified_proof_pack(_safe_fresh_source(secrets_redacted=False))
    assert pack["live_verified"] is False
    assert pack["proof_label"] != LABEL_LIVE_VERIFIED
    assert "secrets_not_redacted" in pack["blockers"]
    assert pack["secret_redaction_score"] == 0.0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
