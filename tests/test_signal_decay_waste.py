"""Tests for scripts/signal_decay_waste.py."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from scripts.signal_decay_waste import (
    DEFAULT_HALF_LIFE_HOURS,
    SAFETY_STAMPS,
    WASTE_CLASSES,
    WASTE_STATES,
    classify_signal_waste,
    compute_decay_factor,
    compute_signal_half_life,
    summarize_waste_load,
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


def test_compute_decay_factor_zero_age_equals_one():
    assert compute_decay_factor(0.0, 24.0) == 1.0


def test_compute_decay_factor_one_half_life_equals_half():
    val = compute_decay_factor(24.0, 24.0)
    assert math.isclose(val, 0.5, rel_tol=1e-6)


def test_compute_decay_factor_handles_garbage_safely():
    assert compute_decay_factor("nope", "also_nope") == 1.0
    assert compute_decay_factor(None, None) == 1.0


def test_signal_half_life_uses_signal_type_defaults():
    new_sig = compute_signal_half_life({
        "signal_type": "social_hype",
        "age_hours": 0.0,
        "initial_strength": 1.0,
    })
    _assert_safety(new_sig)
    assert new_sig["signal_half_life_hours"] == 6.0
    assert new_sig["decayed_strength"] == 1.0
    assert new_sig["stale_signal"] is False


def test_social_hype_decays_faster_than_filing():
    social = compute_signal_half_life({
        "signal_type": "social_hype",
        "age_hours": 24.0,
        "initial_strength": 1.0,
    })
    filing = compute_signal_half_life({
        "signal_type": "official_filing",
        "age_hours": 24.0,
        "initial_strength": 1.0,
    })
    assert social["decay_factor"] < filing["decay_factor"]


def test_old_signal_is_stale_and_archive_candidate():
    payload = classify_signal_waste({
        "signal_type": "social_hype",
        "age_hours": 100.0,
        "initial_strength": 1.0,
        "reinforcement_count": 0,
    })
    _assert_safety(payload)
    assert payload["stale_signal"] is True
    assert payload["waste_class"] in {"archive_candidate", "stale"}


def test_contradicted_signal_class():
    payload = classify_signal_waste({
        "signal_type": "news",
        "age_hours": 6.0,
        "contradiction_count": 5,
        "reinforcement_count": 0,
    })
    _assert_safety(payload)
    assert payload["waste_class"] == "contradicted"


def test_duplicate_echo_class():
    payload = classify_signal_waste({
        "signal_type": "news",
        "age_hours": 6.0,
        "duplicate_count": 5,
    })
    _assert_safety(payload)
    assert payload["waste_class"] == "duplicate_echo"


def test_failed_thesis_debt_class():
    payload = classify_signal_waste({
        "signal_type": "news",
        "age_hours": 1.0,
        "failed_thesis": True,
    })
    _assert_safety(payload)
    assert payload["waste_class"] == "failed_thesis_debt"


def test_unresolved_contradiction_class():
    payload = classify_signal_waste({
        "signal_type": "news",
        "age_hours": 1.0,
        "unresolved_contradiction": True,
    })
    _assert_safety(payload)
    assert payload["waste_class"] == "unresolved_contradiction"


def test_active_signal_class():
    payload = classify_signal_waste({
        "signal_type": "news",
        "age_hours": 1.0,
        "initial_strength": 0.9,
        "reinforcement_count": 1,
    })
    _assert_safety(payload)
    assert payload["waste_class"] == "active"


def test_missing_data_handled_safely():
    payload = classify_signal_waste({})
    _assert_safety(payload)
    assert payload["waste_class"] in WASTE_CLASSES


def test_compute_signal_half_life_uses_iso_created_at():
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    payload = compute_signal_half_life(
        {"signal_type": "news", "created_at": "2026-01-01T00:00:00Z"},
        now=now,
    )
    _assert_safety(payload)
    assert payload["signal_age_hours"] == 12.0


def test_summarize_waste_load_clean_low():
    summary = summarize_waste_load({
        "total_signal_count": 10,
        "false_positive_count": 0,
        "duplicate_count": 0,
        "stale_signal_count": 1,
        "unresolved_contradiction_count": 0,
        "failed_thesis_count": 0,
        "unreconciled_trade_count": 0,
        "quarantined_signal_count": 0,
    })
    _assert_safety(summary)
    assert summary["waste_state"] == "clean"


def test_summarize_waste_load_overloaded_high():
    summary = summarize_waste_load({
        "total_signal_count": 10,
        "false_positive_count": 3,
        "duplicate_count": 4,
        "stale_signal_count": 1,
        "unresolved_contradiction_count": 0,
        "failed_thesis_count": 0,
        "unreconciled_trade_count": 0,
        "quarantined_signal_count": 0,
    })
    _assert_safety(summary)
    assert summary["waste_state"] in {"overloaded", "cleanup_required"}
    assert "prune_duplicate_signals" in summary["cleanup_recommendations"]


def test_summarize_waste_load_empty_safe():
    summary = summarize_waste_load([])
    _assert_safety(summary)
    assert summary["waste_state"] == "insufficient_data"
    assert summary["waste_load_score"] == 0.0


def test_summarize_waste_load_unreconciled_trade_recommendation():
    summary = summarize_waste_load({
        "total_signal_count": 5,
        "unreconciled_trade_count": 2,
    })
    _assert_safety(summary)
    assert "reconcile_open_trades" in summary["cleanup_recommendations"]


def test_summarize_waste_load_handles_list_of_signals():
    signals = [
        {"signal_type": "news", "age_hours": 1.0, "initial_strength": 0.8},
        {"signal_type": "social_hype", "age_hours": 100.0, "initial_strength": 0.5},
        {"signal_type": "news", "age_hours": 1.0, "duplicate_count": 5},
    ]
    summary = summarize_waste_load(signals)
    _assert_safety(summary)
    assert summary["counts"]["total_signal_count"] == 3
    assert summary["counts"]["duplicate_count"] >= 1


def test_deterministic_outputs():
    sig = {"signal_type": "news", "age_hours": 5.0, "initial_strength": 0.8}
    a = compute_signal_half_life(sig)
    b = compute_signal_half_life(sig)
    assert a == b


def test_default_half_life_table_complete():
    for k in ("official_filing", "regulatory", "market_price",
              "social_hype", "news", "polymarket", "ai_summary", "unknown"):
        assert k in DEFAULT_HALF_LIFE_HOURS


def test_waste_state_set_complete():
    for s in ("clean", "accumulating", "overloaded",
              "cleanup_required", "insufficient_data"):
        assert s in WASTE_STATES
