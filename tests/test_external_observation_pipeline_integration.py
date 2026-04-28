"""End-to-end wiring tests for the external observation lane.

Confirms that:
  * Running diagnostics without the lane does NOT add external fields that
    would mislead an operator into thinking external data is present.
  * Running diagnostics WITH a fake-provider lane flips operating_mode /
    truth_origin / live_quotes_available correctly, but does NOT raise
    can_deploy_capital or weaken system_readiness_state.
  * The new external_observation_context on the action report surfaces
    attachment + overlap counts without mutating action ranks.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest


@pytest.fixture
def fake_ok_provider():
    def _fn(symbol: str) -> dict:
        return {
            "last_price": 91.0,
            "previous_close": 90.0,
            "volume": 1_000_000,
            "currency": "USD",
            "regular_market_time": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
        }

    return _fn


@pytest.fixture
def fake_error_provider():
    def _fn(symbol: str) -> dict:
        raise RuntimeError("provider offline")

    return _fn


def test_diagnostics_without_lane_keeps_seeded_fallback(scratch_path: Path):
    from scripts.run_diagnostics_pipeline import run_diagnostics_pipeline

    report = run_diagnostics_pipeline(write_runtime=False)
    assert report["bridge_mode"] == "seeded"
    assert report["bridge_mode_reason"] == "no external observation mode requested"
    assert report["bridge_mode_safety_state"] == "paper_safe_only"
    assert report["operating_mode"] == "seeded"
    assert report["truth_origin"] == "seeded"
    assert report["system_readiness_state"] == "DO_NOT_DEPLOY"
    assert report["can_deploy_capital"] is False
    assert report["external_observation_active"] is False
    assert report["live_quotes_available"] is False
    assert report["external_observation_count"] == 0
    # Field must still be present (stable shape), just empty.
    assert "external_observation_summary" in report
    assert report["external_observation_summary"]["external_observation_active"] is False


def test_diagnostics_with_valid_lane_flips_truth_origin_but_preserves_governance(fake_ok_provider):
    from scripts.run_diagnostics_pipeline import run_diagnostics_pipeline
    from scripts.pipeline_health_report import format_pipeline_health_summary

    report = run_diagnostics_pipeline(
        include_external_observations=True,
        external_observation_symbols=["TLT", "TIP"],
        external_observation_provider_fn=fake_ok_provider,
        write_runtime=False,
    )
    # Governance must NOT weaken.
    assert report["system_readiness_state"] == "DO_NOT_DEPLOY"
    assert report["can_deploy_capital"] is False
    # Truth-origin / mode reflect external lane.
    assert report["operating_mode"] == "hybrid"
    assert report["truth_origin"] == "external"
    assert report["live_quotes_available"] is True
    # Lane fields populate.
    assert report["external_observation_active"] is True
    assert report["external_observation_count"] == 2
    assert report["external_observation_valid_count"] == 2
    assert report["external_observation_error_count"] == 0
    assert sorted(report["external_observation_symbols"]) == ["TIP", "TLT"]
    assert report["external_observation_provider"] == "yahoo"
    assert report["bridge_mode"] == "external_candidate_validation"
    assert (
        report["bridge_mode_reason"]
        == "valid external observations admitted as SCM candidate rows"
    )
    assert report["bridge_mode_safety_state"] == "paper_safe_only"
    assert report["external_candidate_count"] == 2
    assert report["external_paper_candidate_count"] == 2
    assert report["scm_external_row_count"] == 2
    assert report["scm_input_origin"] in {"mixed", "external_observation"}
    summary = format_pipeline_health_summary(report)
    assert "external_candidate_count=2" in summary
    assert "bridge_mode=external_candidate_validation" in summary
    assert "bridge_mode_safety_state=paper_safe_only" in summary
    # Candidate validation remains paper-safe only; no live order/fill path is triggered.
    assert report["can_deploy_capital"] is False
    assert report["system_readiness_state"] == "DO_NOT_DEPLOY"


def test_diagnostics_with_failing_lane_keeps_seeded_truth(fake_error_provider):
    from scripts.run_diagnostics_pipeline import run_diagnostics_pipeline

    report = run_diagnostics_pipeline(
        include_external_observations=True,
        external_observation_symbols=["UNG"],
        external_observation_provider_fn=fake_error_provider,
        write_runtime=False,
    )
    assert report["bridge_mode"] == "unavailable"
    assert (
        report["bridge_mode_reason"]
        == "external mode requested but provider returned zero valid observations"
    )
    assert report["bridge_mode_safety_state"] == "fail_closed"
    # No valid observation -> truth_origin stays seeded.
    assert report["operating_mode"] == "seeded"
    assert report["truth_origin"] == "seeded"
    assert report["live_quotes_available"] is False
    assert report["external_observation_active"] is False
    # But the lane DID run and the error is visible.
    assert report["external_observation_count"] == 1
    assert report["external_observation_error_count"] == 1
    assert report["external_observation_valid_count"] == 0
    # Governance holds even with a failing external lane.
    assert report["can_deploy_capital"] is False
    assert report["system_readiness_state"] == "DO_NOT_DEPLOY"


def test_diagnostics_with_observation_only_mode_resolves_hybrid_observation(fake_ok_provider):
    from scripts.run_diagnostics_pipeline import run_diagnostics_pipeline
    from scripts.pipeline_health_report import format_pipeline_health_summary

    report = run_diagnostics_pipeline(
        include_external_observations=True,
        bridge_external_candidates=False,
        external_observation_symbols=["TLT", "TIP"],
        external_observation_provider_fn=fake_ok_provider,
        write_runtime=False,
    )

    assert report["bridge_mode"] == "hybrid_observation"
    assert (
        report["bridge_mode_reason"]
        == "external observations active but no external candidates admitted into SCM"
    )
    assert report["bridge_mode_safety_state"] == "paper_safe_only"
    assert report["external_observation_active"] is True
    assert report["external_observation_valid_count"] == 2
    assert report["external_candidate_count"] == 0
    assert report["external_paper_candidate_count"] == 0
    assert report["scm_external_row_count"] == 0
    assert report["scm_input_origin"] == "seeded"
    assert report["can_deploy_capital"] is False
    assert report["system_readiness_state"] == "DO_NOT_DEPLOY"
    summary = format_pipeline_health_summary(report)
    assert "bridge_mode=hybrid_observation" in summary


def test_action_report_exposes_external_observation_context_when_active(fake_ok_provider):
    """The action engine's report attaches an advisory external_observation_context
    block when the runtime state carries an active external observation summary.
    Verified by calling build_action_report directly with a seeded state."""
    from scripts.action_engine import build_action_report
    from scripts.signal_conversion_monitor import build_signal_conversion_report
    from scripts.runtime_common import build_runtime_state_from_scm_report_payload

    scm_report = build_signal_conversion_report()
    state = build_runtime_state_from_scm_report_payload(scm_report)
    state["external_observation_summary"] = {
        "external_observation_active": True,
        "external_observation_count": 2,
        "external_observation_valid_count": 2,
        "external_observation_error_count": 0,
        "external_observation_symbols": ["UNG", "FCG"],
        "external_observation_provider": "yahoo",
    }

    action_report = build_action_report(runtime_state=state, write_runtime=False)
    ctx = action_report["external_observation_context"]
    assert ctx["external_observation_attached"] is True
    assert ctx["external_observation_provider"] == "yahoo"
    # Overlap with tickers present in the action report.
    tickers = {a["ticker"] for a in action_report["actions"]}
    expected_overlap = sorted({"UNG", "FCG"} & tickers)
    assert ctx["external_observation_symbols"] == expected_overlap
    assert ctx["external_observation_context_count"] == len(expected_overlap)
    assert ctx["external_observation_quality_summary"] == {
        "valid_count": 2,
        "error_count": 0,
        "total_count": 2,
    }


def test_action_report_context_is_inactive_when_no_external_summary():
    from scripts.action_engine import build_action_report
    from scripts.signal_conversion_monitor import build_signal_conversion_report
    from scripts.runtime_common import build_runtime_state_from_scm_report_payload

    scm_report = build_signal_conversion_report()
    state = build_runtime_state_from_scm_report_payload(scm_report)
    action_report = build_action_report(runtime_state=state, write_runtime=False)
    ctx = action_report["external_observation_context"]
    assert ctx["external_observation_attached"] is False
    assert ctx["external_observation_context_count"] == 0
    assert ctx["external_observation_symbols"] == []


def test_lane_preserves_stable_shape_even_when_empty():
    """Shape stability: with the lane inactive, the top-level keys still exist
    so downstream consumers do not need conditional key checks."""
    from scripts.run_diagnostics_pipeline import run_diagnostics_pipeline

    report = run_diagnostics_pipeline(write_runtime=False)
    required_keys = {
        "external_observation_active",
        "external_observation_count",
        "external_observation_valid_count",
        "external_observation_error_count",
        "external_observation_symbols",
        "external_observation_data_quality_counts",
        "external_observation_summary",
        "external_candidate_count",
        "bridge_mode",
        "bridge_mode_reason",
        "bridge_mode_safety_state",
        "live_quotes_available",
        "position_truth_summary",
        "position_source_divergence_detected",
        "position_truth_source",
        "curated_positions_count",
        "runtime_paper_positions_count",
    }
    missing = required_keys - set(report)
    assert not missing, f"missing stable keys: {missing}"
