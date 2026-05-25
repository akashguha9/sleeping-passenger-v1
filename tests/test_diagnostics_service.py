"""Tests for the read-only diagnostics service + partial-failure taxonomy (Task 2).

Proves: a failed subreport surfaces as DEGRADED (never fake-clean), the top-level
status reflects degraded/blocked subreports, a fresh cache avoids recomputation,
and the payload keeps its read-only/advisory safety stamps.
"""
from __future__ import annotations

import pytest

from scripts import diagnostics_service as svc


# ---------------------------------------------------------------------------
# Pure status mapping
# ---------------------------------------------------------------------------

def test_status_from_data_release_gate():
    assert svc._status_from_data("truth_purity", {"release_gate_passed": True}) == svc.CLEAN
    assert svc._status_from_data("truth_purity", {"release_gate_passed": False}) == svc.BLOCK


def test_status_from_data_impact():
    assert svc._status_from_data("bw", {"release_gate_impact": "WARN"}) == svc.WARN
    assert svc._status_from_data("bw", {"release_gate_impact": "BLOCK"}) == svc.BLOCK
    assert svc._status_from_data("bw", {"release_gate_impact": "CLEAN"}) == svc.CLEAN


def test_status_from_data_flagged_cohorts_is_warn():
    assert svc._status_from_data("si", {"flagged_cohorts": ["AAPL"]}) == svc.WARN
    assert svc._status_from_data("si", {"flagged_cohorts": []}) == svc.CLEAN


def test_status_from_data_unknown_payload():
    assert svc._status_from_data("x", None) == svc.UNKNOWN
    assert svc._status_from_data("x", 42) == svc.UNKNOWN
    # Built dict with no recognised signal → clean (built successfully).
    assert svc._status_from_data("x", {"foo": "bar"}) == svc.CLEAN


# ---------------------------------------------------------------------------
# Resolution: failed subreport is DEGRADED, not fake clean
# ---------------------------------------------------------------------------

def _raw(**subs):
    return subs


def test_failed_subreport_is_degraded_in_partial_failures():
    raw = _raw(
        truth_purity={"status": "OK", "data": {"release_gate_passed": True}},
        broken_windows={"status": "DEGRADED", "error_type": "OperationalError",
                        "recovery_command": "python scripts/broken_windows_report.py"},
    )
    resolved, partial = svc._resolve_subreports(raw, include_heavy=False)
    assert resolved["broken_windows"]["status"] == svc.DEGRADED
    assert resolved["broken_windows"]["safe_recovery_command"]
    assert partial == [{
        "subreport": "broken_windows",
        "error_type": "OperationalError",
        "safe_recovery_command": "python scripts/broken_windows_report.py",
    }]
    # The failed subreport did NOT become {"...": 0} clean.
    assert "data" not in resolved["broken_windows"] or resolved["broken_windows"].get("data") is None


def test_include_heavy_embeds_data():
    raw = _raw(truth_purity={"status": "OK", "data": {"release_gate_passed": True}})
    light, _ = svc._resolve_subreports(raw, include_heavy=False)
    heavy, _ = svc._resolve_subreports(raw, include_heavy=True)
    assert "data" not in light["truth_purity"]
    assert heavy["truth_purity"]["data"] == {"release_gate_passed": True}


# ---------------------------------------------------------------------------
# Top-level status escalation
# ---------------------------------------------------------------------------

def test_critical_degraded_escalates_to_block():
    resolved = {"truth_purity": {"status": svc.DEGRADED}, "broken_windows": {"status": svc.CLEAN}}
    assert svc._top_level_status(resolved) == svc.BLOCK


def test_noncritical_degraded_is_degraded():
    resolved = {"truth_purity": {"status": svc.CLEAN}, "broken_windows": {"status": svc.DEGRADED}}
    assert svc._top_level_status(resolved) == svc.DEGRADED


def test_block_propagates():
    resolved = {"truth_purity": {"status": svc.CLEAN}, "x": {"status": svc.BLOCK}}
    assert svc._top_level_status(resolved) == svc.BLOCK


def test_warn_propagates_when_no_worse():
    resolved = {"a": {"status": svc.CLEAN}, "b": {"status": svc.WARN}}
    assert svc._top_level_status(resolved) == svc.WARN


def test_all_clean_is_clean():
    resolved = {"a": {"status": svc.CLEAN}, "b": {"status": svc.CLEAN}}
    assert svc._top_level_status(resolved) == svc.CLEAN


# ---------------------------------------------------------------------------
# DiagnosticsHealth
# ---------------------------------------------------------------------------

def test_diagnostics_health_formula():
    # 1 failed (DEGRADED) + 1 degraded (WARN) of 4 → 1 - 1/4 - 0.5*1/4 = 0.625
    resolved = {
        "a": {"status": svc.DEGRADED},
        "b": {"status": svc.WARN},
        "c": {"status": svc.CLEAN},
        "d": {"status": svc.CLEAN},
    }
    assert svc._diagnostics_health(resolved) == 0.625


def test_diagnostics_health_all_clean_is_one():
    resolved = {"a": {"status": svc.CLEAN}, "b": {"status": svc.CLEAN}}
    assert svc._diagnostics_health(resolved) == 1.0


# ---------------------------------------------------------------------------
# Cache hit avoids recomputation
# ---------------------------------------------------------------------------

def test_cache_hit_avoids_recompute(monkeypatch):
    snap = {
        "generated_at_utc": "2026-05-21T00:00:00Z",
        "subreports": {"truth_purity": {"status": "OK", "data": {"release_gate_passed": True}}},
    }
    monkeypatch.setattr(svc._cache, "read_snapshot", lambda: snap)
    monkeypatch.setattr(svc._cache, "cache_validity",
                        lambda s, d=None: {"valid": True, "age_seconds": 1})

    def _boom(*a, **k):
        raise AssertionError("refresh must not be called on a cache hit")

    monkeypatch.setattr(svc._cache, "refresh", _boom)
    out = svc.get_diagnostics_snapshot(use_cache=True, max_age_seconds=300)
    assert out["cache_status"] == "hit"
    assert out["status"] == svc.CLEAN


def test_stale_cache_recomputes(monkeypatch):
    fresh = {
        "generated_at_utc": "2026-05-21T01:00:00Z",
        "subreports": {"truth_purity": {"status": "OK", "data": {"release_gate_passed": True}}},
    }
    monkeypatch.setattr(svc._cache, "read_snapshot", lambda: {"subreports": {}})
    monkeypatch.setattr(svc._cache, "cache_validity",
                        lambda s, d=None: {"valid": False, "reason": "ttl_expired"})
    monkeypatch.setattr(svc._cache, "refresh", lambda d=None: fresh)
    out = svc.get_diagnostics_snapshot(use_cache=True)
    assert out["cache_status"] == "miss_recomputed"


# ---------------------------------------------------------------------------
# Safety stamps preserved; no execution
# ---------------------------------------------------------------------------

def test_safety_stamps_preserved(monkeypatch):
    snap = {"generated_at_utc": "t", "subreports": {"truth_purity": {"status": "OK", "data": {"release_gate_passed": True}}}}
    monkeypatch.setattr(svc._cache, "read_snapshot", lambda: snap)
    monkeypatch.setattr(svc._cache, "cache_validity", lambda s, d=None: {"valid": True, "age_seconds": 1})
    out = svc.get_diagnostics_snapshot()
    stamps = out["safety_stamps"]
    assert stamps["advisory_status"] == "ADVISORY_ONLY"
    assert stamps["execution_gate"] == "LOCKED"
    assert stamps["broker_api_called"] is False
    assert stamps["ai_execution_count"] == 0
    assert out["canonical_truth_source"] == "sqlite"
    assert out["human_review_required"] is True
