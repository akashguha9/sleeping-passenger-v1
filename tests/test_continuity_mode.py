"""
Tests for ``scripts.continuity_mode``.

Pin
---
- Healthy system is NORMAL.
- DB unavailable forces CONTINUITY_SAFE_ADVISORY and disables manual
  trade logging in ``allowed_actions``.
- Safety invariant failure forces continuity-safe mode.
- Stale sources, AI validation failures, fallback active are flagged as
  degraded reasons.
- ``allowed_actions["execute_broker_order"]`` is ALWAYS False, no matter
  how healthy the system is — perception is not permission.
- Safety stamps locked on every output.
- Bad input does not crash.
"""
from __future__ import annotations

from scripts import continuity_mode as cm


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_healthy_system_is_normal():
    state = {
        "backend_available": True,
        "db_available": True,
        "safety_invariant_ok": True,
        "source_health_ok": True,
        "live_refresh_fresh": True,
        "backup_recent": True,
        "ai_validation_invalid_count": 0,
        "fallback_used": False,
        "mock_used": False,
    }
    result = cm.classify_continuity_mode(state)
    assert result["continuity_mode"] == "NORMAL"
    assert result["system_integrity_score"] >= 0.85
    assert result["degraded_reasons"] == []
    assert result["allowed_actions"]["log_manual_trade"] is True
    assert result["allowed_actions"]["execute_broker_order"] is False


# ---------------------------------------------------------------------------
# DB unavailable
# ---------------------------------------------------------------------------


def test_db_unavailable_forces_continuity_safe():
    state = {
        "backend_available": True,
        "db_available": False,
        "safety_invariant_ok": True,
        "source_health_ok": True,
    }
    result = cm.classify_continuity_mode(state)
    assert result["continuity_mode"] == "CONTINUITY_SAFE_ADVISORY"
    assert "db_unavailable" in result["degraded_reasons"]
    assert result["allowed_actions"]["log_manual_trade"] is False
    assert result["allowed_actions"]["reconcile"] is False
    assert result["allowed_actions"]["execute_broker_order"] is False


# ---------------------------------------------------------------------------
# Safety invariant broken
# ---------------------------------------------------------------------------


def test_safety_invariant_failure_forces_continuity_safe():
    state = {
        "backend_available": True,
        "db_available": True,
        "safety_invariant_ok": False,
        "source_health_ok": True,
    }
    result = cm.classify_continuity_mode(state)
    assert result["continuity_mode"] in {
        "CONTINUITY_SAFE_ADVISORY",
        "DEGRADED_ADVISORY",
    }
    # The hard floor caps integrity at 0.40 when safety invariant breaks.
    assert result["system_integrity_score"] <= 0.40
    assert "safety_invariant_broken" in result["degraded_reasons"]
    assert result["allowed_actions"]["execute_broker_order"] is False


# ---------------------------------------------------------------------------
# Stale / failed sources
# ---------------------------------------------------------------------------


def test_stale_sources_mark_degraded():
    state = {
        "backend_available": True,
        "db_available": True,
        "safety_invariant_ok": True,
        "stale_source_count": 2,
        "failed_source_count": 0,
        "live_refresh_fresh": True,
        "backup_recent": True,
    }
    result = cm.classify_continuity_mode(state)
    assert result["continuity_mode"] in {"DEGRADED_ADVISORY", "NORMAL"}
    if result["continuity_mode"] != "NORMAL":
        assert "source_health_degraded" in result["degraded_reasons"]


def test_failed_sources_drop_integrity_more():
    state = {
        "backend_available": True,
        "db_available": True,
        "safety_invariant_ok": True,
        "failed_source_count": 3,
        "stale_source_count": 0,
        "live_refresh_fresh": True,
        "backup_recent": True,
    }
    result = cm.classify_continuity_mode(state)
    assert result["continuity_mode"] in {
        "DEGRADED_ADVISORY",
        "CONTINUITY_SAFE_ADVISORY",
    }
    assert "source_health_degraded" in result["degraded_reasons"]


# ---------------------------------------------------------------------------
# Fallback / mock visibility
# ---------------------------------------------------------------------------


def test_fallback_active_flagged_even_if_score_high():
    state = {
        "backend_available": True,
        "db_available": True,
        "safety_invariant_ok": True,
        "source_health_ok": True,
        "live_refresh_fresh": True,
        "backup_recent": True,
        "fallback_used": True,
    }
    result = cm.classify_continuity_mode(state)
    assert "source_fallback_active" in result["degraded_reasons"]
    assert result["informational"]["fallback_used"] is True


def test_mock_active_flagged():
    state = {
        "backend_available": True,
        "db_available": True,
        "safety_invariant_ok": True,
        "source_health_ok": True,
        "live_refresh_fresh": True,
        "backup_recent": True,
        "mock_used": True,
    }
    result = cm.classify_continuity_mode(state)
    assert "mock_mode_active" in result["degraded_reasons"]
    assert result["informational"]["mock_used"] is True


# ---------------------------------------------------------------------------
# AI validation failures
# ---------------------------------------------------------------------------


def test_ai_validation_failures_degrade():
    state = {
        "backend_available": True,
        "db_available": True,
        "safety_invariant_ok": True,
        "source_health_ok": True,
        "live_refresh_fresh": True,
        "backup_recent": True,
        "ai_validation_invalid_count": 5,
    }
    result = cm.classify_continuity_mode(state)
    assert "ai_validation_failures" in result["degraded_reasons"]
    assert result["factors"]["ai_validation_health"] < 1.0


# ---------------------------------------------------------------------------
# Allowed actions invariants
# ---------------------------------------------------------------------------


def test_execute_broker_order_is_always_false():
    for state in (
        {"backend_available": True, "db_available": True, "safety_invariant_ok": True},
        {"backend_available": False},
        {"db_available": False, "safety_invariant_ok": False},
        {},
    ):
        result = cm.classify_continuity_mode(state)
        assert result["allowed_actions"]["execute_broker_order"] is False


# ---------------------------------------------------------------------------
# Safety stamps
# ---------------------------------------------------------------------------


def test_safety_stamps_locked():
    for state in (
        {"backend_available": True, "db_available": True, "safety_invariant_ok": True},
        {"backend_available": False, "safety_invariant_ok": False},
        {},
    ):
        result = cm.classify_continuity_mode(state)
        assert result["advisory_status"] == "ADVISORY_ONLY"
        assert result["execution_gate"] == "LOCKED"
        assert result["broker_api_called"] is False
        assert result["ai_execution_count"] == 0
        assert result["execution_permission"] is False
        assert result["can_execute"] is False
        assert result["may_execute"] is False


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


def test_non_dict_state_returns_continuity_safe():
    result = cm.classify_continuity_mode("not a dict")  # type: ignore[arg-type]
    assert result["continuity_mode"] == "CONTINUITY_SAFE_ADVISORY"
    assert result["validation_status"] == "invalid"
    assert result["allowed_actions"]["execute_broker_order"] is False


def test_empty_state_optimistic_defaults_to_normal():
    """Missing data is treated as healthy by design.

    Operators must pass `False` explicitly when something is known broken.
    """
    result = cm.classify_continuity_mode({})
    assert result["continuity_mode"] == "NORMAL"
    assert result["allowed_actions"]["execute_broker_order"] is False


def test_deterministic_output():
    state = {
        "backend_available": True,
        "db_available": True,
        "safety_invariant_ok": True,
        "stale_source_count": 1,
        "ai_validation_invalid_count": 1,
    }
    a = cm.classify_continuity_mode(state)
    b = cm.classify_continuity_mode(dict(state))
    assert a == b


def test_input_state_not_mutated():
    state = {"db_available": False, "safety_invariant_ok": True}
    snapshot = dict(state)
    cm.classify_continuity_mode(state)
    assert state == snapshot
