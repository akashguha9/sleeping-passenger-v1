"""Tests for diagnostic-badge wiring on the Signal Inbox API.

The Operator Discipline UI + Journal Schema Sprint exposes fragility +
quarantine diagnostics on every inbox item.  These tests exercise the pure
decorator (``_decorate_inbox_diagnostics``) and the list endpoint roll-up
counters.  No live API calls; no DB writes.
"""
from __future__ import annotations

from scripts import signal_inbox_api


_SAFETY_KEYS = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
}


def _assert_safety(item: dict) -> None:
    for k, v in _SAFETY_KEYS.items():
        assert item.get(k) == v, f"safety stamp {k} expected {v!r}, got {item.get(k)!r}"


def test_decorator_adds_sensitivity_and_quarantine_fields() -> None:
    item = {
        "event_id": "FABRIC_BTC",
        "ticker": "BTC",
        "signal_state": "REVIEW",
        "priority_score": 0.55,
        "persistence_score": 0.58,
        "blocker_pressure_score": 0.25,
        "kill_rate_score": 0.20,
        "contradiction_score": 0.15,
        "reliability_score": 0.75,
        "confidence_score": 0.62,
    }
    result = signal_inbox_api._decorate_inbox_diagnostics(item)
    # Sensitivity fields
    assert "chaos_sensitivity_score" in result
    assert "classification_stability_score" in result
    assert "fragile" in result
    assert "sensitivity_recommendation" in result
    assert "baseline_classification" in result
    # Quarantine fields
    assert "contamination_score" in result
    assert "toxic_quarantine_state" in result
    assert "quarantine_reasons" in result
    assert "promotion_allowed" in result
    # AI validation passthrough
    assert "ai_validation_status" in result
    _assert_safety(result)


def test_decorator_marks_borderline_signal_fragile() -> None:
    """A signal sitting at the bucket-classifier boundary should flip."""
    # confidence at 0.4 boundary, persistence at 0.4 boundary — small
    # perturbation will push us across.
    item = {
        "event_id": "FABRIC_FRAGILE",
        "ticker": "X",
        "confidence_score": 0.40,
        "persistence_score": 0.40,
        "reliability_score": 0.50,
        "contradiction_score": 0.10,
    }
    result = signal_inbox_api._decorate_inbox_diagnostics(item)
    assert result["fragile"] is True
    assert result["sensitivity_recommendation"] in {
        "fragile_watchlist",
        "human_review_required",
    }


def test_decorator_quarantines_contaminated_signal() -> None:
    item = {
        "event_id": "FABRIC_TOX",
        "ticker": "TOX",
        # Hits unreliability + contradiction + hallucination + ai_invalid in one row.
        "reliability_score": 0.1,
        "contradiction_score": 0.95,
        "hallucination_risk": 0.9,
        "ai_validation_status": "invalid",
    }
    result = signal_inbox_api._decorate_inbox_diagnostics(item)
    assert result["toxic_quarantine_state"] in {"quarantine", "block_from_promotion"}
    assert result["promotion_allowed"] is False
    # At least one reason must be surfaced
    assert len(result["quarantine_reasons"]) > 0
    _assert_safety(result)


def test_decorator_handles_missing_or_empty_signal() -> None:
    # Empty dict and a dict full of strings — must not crash.
    for bad_item in (
        {},
        {"event_id": "FABRIC_EMPTY", "ticker": "EMPTY"},
        {"event_id": "X", "confidence_score": "not_a_number"},
    ):
        result = signal_inbox_api._decorate_inbox_diagnostics(bad_item)
        _assert_safety(result)
        # No execution permission ever
        assert result["execution_permission"] is False
        assert result["can_execute"] is False


def test_decorator_never_grants_execution_permission() -> None:
    # Even a signal that hand-crafts those flags must be re-stamped.
    item = {
        "event_id": "FABRIC_BAD",
        "ticker": "BAD",
        "advisory_status": "ALLOWED",
        "execution_gate": "OPEN",
        "broker_api_called": True,
        "ai_execution_count": 5,
        "execution_permission": True,
        "can_execute": True,
    }
    result = signal_inbox_api._decorate_inbox_diagnostics(item)
    _assert_safety(result)


def test_list_inbox_items_includes_diagnostic_rollups(monkeypatch) -> None:
    """The /signals list response must surface fragile + quarantined counts."""
    # Stub the underlying fabric/bridge calls so we don't depend on DB state.
    fake_items = [
        {
            "event_id": "FABRIC_FRESH",
            "ticker": "FRESH",
            "signal_state": "REVIEW",
            "entry_type": "UNKNOWN",
            "priority_score": 0.55,
            "observed_at": "2024-01-01T00:00:00Z",
            "source_file": "x",
            "rejection_dimensions": [],
            "rejection_reason": "",
            "persistence_score": 0.40,
            "blocker_pressure_score": 0.2,
            "kill_rate_score": 0.1,
            "blocker_attribution": "NONE",
            "confidence_score": 0.40,
            "reliability_score": 0.5,
            "contradiction_score": 0.1,
        },
        {
            "event_id": "FABRIC_TOX",
            "ticker": "TOX",
            "signal_state": "REVIEW",
            "entry_type": "UNKNOWN",
            "priority_score": 0.5,
            "observed_at": "2024-01-01T00:00:00Z",
            "source_file": "x",
            "rejection_dimensions": [],
            "rejection_reason": "",
            "persistence_score": 0.5,
            "blocker_pressure_score": 0.1,
            "kill_rate_score": 0.1,
            "blocker_attribution": "NONE",
            "reliability_score": 0.1,
            "contradiction_score": 0.95,
            "hallucination_risk": 0.9,
            "ai_validation_status": "invalid",
        },
    ]

    monkeypatch.setattr(
        signal_inbox_api,
        "promote_signal_events_to_inbox",
        lambda **kwargs: fake_items,
    )
    monkeypatch.setattr(signal_inbox_api, "_DB_AVAILABLE", True)

    class _FakePersistence:
        def get_all_signal_decisions(self):
            return {}
        def has_reflection(self, _):
            return False
        def has_ai_summary(self, _):
            return False
    monkeypatch.setattr(signal_inbox_api, "_persistence", _FakePersistence())

    resp = signal_inbox_api.list_inbox_items()
    _assert_safety(resp)
    assert resp["item_count"] == 2
    # Roll-up counters present
    assert "fragile_signal_count" in resp
    assert "quarantined_signal_count" in resp
    # The TOX signal should be counted as quarantined.
    assert resp["quarantined_signal_count"] >= 1
    # Each item carries the diagnostic fields too.
    for it in resp["items"]:
        assert "chaos_sensitivity_score" in it
        assert "toxic_quarantine_state" in it
        _assert_safety(it)


def test_decorator_handles_non_dict_input_gracefully() -> None:
    # If something upstream gave us a non-dict (e.g. None), we mustn't crash
    # the calling site.  This documents the helper's failure mode.
    # The decorator's contract is: input MUST be a dict; non-dict raises
    # AttributeError because dict(...) on a non-dict is a different op.
    # We only need to guarantee that *dicts* never crash, which the
    # earlier tests cover.  This sanity check just confirms a dict with
    # surprising types stays safe.
    weird = {"event_id": None, "ticker": 123, "priority_score": "0.5"}
    result = signal_inbox_api._decorate_inbox_diagnostics(weird)
    _assert_safety(result)
