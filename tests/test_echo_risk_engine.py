"""Tests for scripts/echo_risk_engine.py."""

from __future__ import annotations

from scripts.echo_risk_engine import (
    CONFIRMATION_QUALITIES,
    SAFETY_STAMPS,
    classify_confirmation_quality,
    compute_echo_risk,
    compute_source_independence,
)


def _assert_safety(payload: dict) -> None:
    safety = payload["safety"]
    assert safety["advisory_status"] == "ADVISORY_ONLY"
    assert safety["execution_gate"] == "LOCKED"
    assert safety["broker_api_called"] is False
    assert safety["ai_execution_count"] == 0
    assert safety["execution_permission"] is False
    assert safety["can_execute"] is False


def test_safety_stamps_constants():
    assert SAFETY_STAMPS["advisory_status"] == "ADVISORY_ONLY"
    assert SAFETY_STAMPS["execution_gate"] == "LOCKED"


def test_empty_items_returns_zero_safe():
    payload = compute_source_independence([])
    _assert_safety(payload)
    assert payload["total_mention_count"] == 0
    assert payload["independent_source_count"] == 0
    assert payload["source_independence_score"] == 0.0


def test_none_input_handled_safely():
    assert compute_source_independence(None)["total_mention_count"] == 0
    assert compute_echo_risk(None)["echo_risk_score"] == 0.0
    assert classify_confirmation_quality(None)["confirmation_quality"] == "insufficient_data"


def test_ten_copies_one_source_high_echo_risk():
    items = [
        {"source_name": "EchoBlog", "url": f"https://e.example/article", "title": "RUMOR", "claim_hash": "h1"}
        for _ in range(10)
    ]
    payload = compute_echo_risk(items)
    _assert_safety(payload)
    assert payload["echo_risk_score"] > 0.6
    assert payload["independent_source_count"] == 1
    assert payload["duplicate_or_echo_count"] >= 9


def test_three_independent_sources_yields_independent_confirmation():
    items = [
        {"source_name": "Reuters", "source_type": "primary", "canonical_url": "u1", "claim_hash": "h1"},
        {"source_name": "Bloomberg", "source_type": "news", "canonical_url": "u2", "claim_hash": "h2"},
        {"source_name": "FT", "source_type": "news", "canonical_url": "u3", "claim_hash": "h3"},
    ]
    payload = classify_confirmation_quality(items)
    _assert_safety(payload)
    assert payload["confirmation_quality"] == "independent_confirmation"
    assert payload["independent_source_count"] == 3
    assert payload["primary_source_present"] is True


def test_missing_primary_source_increases_echo_risk():
    items = [
        {"source_name": "Blog1", "source_type": "social", "url": "u1"},
        {"source_name": "Blog2", "source_type": "social", "url": "u2"},
        {"source_name": "Blog3", "source_type": "social", "url": "u3"},
    ]
    payload = compute_echo_risk(items)
    _assert_safety(payload)
    assert payload["primary_source_present"] is False
    assert payload["promotion_penalty"] > 0.0


def test_primary_source_present_lowers_echo_risk():
    primary_items = [
        {"source_name": "SEC", "source_type": "primary", "url": "u1", "claim_hash": "h1"},
        {"source_name": "Reuters", "source_type": "news", "url": "u2", "claim_hash": "h2"},
    ]
    without_primary_items = [
        {"source_name": "Reuters", "source_type": "news", "url": "u1", "claim_hash": "h1"},
        {"source_name": "Blog", "source_type": "social", "url": "u2", "claim_hash": "h2"},
    ]
    payload_with = compute_echo_risk(primary_items)
    payload_without = compute_echo_risk(without_primary_items)
    assert payload_with["echo_risk_score"] <= payload_without["echo_risk_score"]


def test_same_canonical_url_deduped():
    items = [
        {"source_name": "A", "source_type": "news", "canonical_url": "same"},
        {"source_name": "B", "source_type": "news", "canonical_url": "same"},
        {"source_name": "C", "source_type": "news", "canonical_url": "same"},
    ]
    payload = compute_source_independence(items)
    _assert_safety(payload)
    assert payload["unique_dedupe_keys"] == 1
    assert payload["duplicate_or_echo_count"] == 2


def test_same_claim_hash_deduped():
    items = [
        {"source_name": "A", "claim_hash": "X", "url": "u1"},
        {"source_name": "B", "claim_hash": "X", "url": "u2"},
    ]
    payload = compute_source_independence(items)
    _assert_safety(payload)
    assert payload["unique_dedupe_keys"] == 1


def test_ai_agreement_without_external_anchors_raises_ai_echo_risk():
    items = [
        {"source_name": "AI1", "source_type": "ai_summary", "ai_agreement_count": 3, "external_anchor_count": 0},
        {"source_name": "AI2", "source_type": "ai_summary", "ai_agreement_count": 4, "external_anchor_count": 0},
    ]
    payload = compute_echo_risk(items)
    _assert_safety(payload)
    assert payload["ai_echo_risk_score"] > 0.5


def test_ai_agreement_with_external_anchors_low_ai_echo_risk():
    items = [
        {"source_name": "AI1", "source_type": "ai_summary", "ai_agreement_count": 2, "external_anchor_count": 5},
    ]
    payload = compute_echo_risk(items)
    _assert_safety(payload)
    assert payload["ai_echo_risk_score"] < 0.5


def test_no_secret_or_execution_fields_in_output():
    items = [{"source_name": "A", "url": "u1"}]
    payload = classify_confirmation_quality(items)
    _assert_safety(payload)
    forbidden = {
        "broker_payload",
        "place_order",
        "execute",
        "api_key",
        "secret",
        "auth_token",
    }
    for key in payload.keys():
        assert key.lower() not in forbidden


def test_classify_confirmation_quality_set_complete():
    for q in ("independent_confirmation", "weak_confirmation",
              "echo_amplification", "missing_primary_source",
              "insufficient_data"):
        assert q in CONFIRMATION_QUALITIES


def test_deterministic_repeated_calls_equal():
    items = [
        {"source_name": "A", "url": "u1", "claim_hash": "h1"},
        {"source_name": "B", "url": "u2", "claim_hash": "h2"},
    ]
    a = classify_confirmation_quality(items)
    b = classify_confirmation_quality(items)
    assert a == b
