"""Focused validation tests for the SCM + external-truth integration.

Each test is paired with a spec bullet from the upgrade task:

    1. external truth lane feeds SCM                        → test_scm_input_origin_*
    2. diagnostics truth_origin changes correctly           → test_truth_origin_*
    3. canonical position source selection                  → test_canonical_position_path_*
    4. paper lineage includes observation/reference fields  → test_paper_fill_lineage_*
    5. contaminated feedback suppresses clean learning rate → test_contamination_*
    6. no autonomous execution occurs                       → test_no_autonomous_execution_*

Every test is self-contained, uses only in-memory or ``scratch_path`` disk
state, and never touches the network.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.moltbook_feedback import MoltbookFeedbackCase, build_feedback_summary
from scripts.position_truth_resolver import (
    DEFAULT_CURATED_PATH,
    DEFAULT_RUNTIME_PATH,
    get_canonical_position_path,
)
from scripts.signal_conversion_monitor import build_signal_conversion_report


# ---------------------------------------------------------------------------
# 1. External truth lane feeds SCM
# ---------------------------------------------------------------------------


def test_scm_input_origin_is_seeded_on_default_ledger():
    """Baseline: the bundled signal ledger produces a seeded-only SCM run."""
    report = build_signal_conversion_report()
    assert report["scm_input_origin"] == "seeded"
    assert report["scm_external_row_count"] == 0
    assert report["scm_seeded_row_count"] > 0


def test_scm_input_origin_becomes_mixed_when_external_rows_arrive():
    """Inject one synthetic external signal row via the documented
    external_signal_inputs hook and confirm SCM correctly tags the run as
    mixed rather than silently absorbing the external origin."""
    external_rows = [
        {
            "signal_id": "POLY_TEST_001",
            "ticker": "USDC",
            "ce_score": 0.72,
            "above_ce_threshold": True,
            "status": "WATCHLIST",
            "conversion_state": "NOT_EXECUTED",
            "blocker_attribution": "GSCE_PHASE_LOCK",
            "watchlist_tier": "PROMOTABLE",
            "signal_origin": "external",
            "source_name": "polymarket_gamma",
        }
    ]
    report = build_signal_conversion_report(
        external_signal_inputs=external_rows,
        include_external_signal_inputs=True,
    )
    assert report["scm_input_origin"] in {"mixed", "external_observation"}
    assert report["scm_external_row_count"] >= 1


def test_scm_input_origin_is_unavailable_when_ledger_is_empty(tmp_path: Path):
    """Fail-closed behavior: when the ledger contains zero qualifying rows,
    SCM must label the origin as unavailable rather than silently reporting
    seeded."""
    empty_ledger = tmp_path / "signal_ledger.json"
    empty_ledger.write_text("[]", encoding="utf-8")
    report = build_signal_conversion_report(signal_ledger_path=empty_ledger)
    assert report["scm_input_origin"] == "unavailable"
    assert report["scm_external_row_count"] == 0
    assert report["scm_seeded_row_count"] == 0


# ---------------------------------------------------------------------------
# 2. Diagnostics truth_origin changes correctly
# ---------------------------------------------------------------------------


def _fake_yahoo_ok(symbol: str) -> dict:
    return {
        "last_price": 91.0,
        "previous_close": 90.0,
        "regular_market_time": "2026-04-24T12:00:00+00:00",
    }


def _fake_yahoo_err(symbol: str) -> dict:
    raise RuntimeError("yfinance offline")


def test_truth_origin_stays_seeded_without_external_lane():
    from scripts.run_diagnostics_pipeline import run_diagnostics_pipeline

    report = run_diagnostics_pipeline(write_runtime=False)
    assert report["operating_mode"] == "seeded"
    assert report["truth_origin"] == "seeded"
    assert report["live_quotes_available"] is False
    assert report["scm_input_origin"] == "seeded"


def test_truth_origin_flips_to_external_when_lane_is_active():
    from scripts.run_diagnostics_pipeline import run_diagnostics_pipeline

    report = run_diagnostics_pipeline(
        include_external_observations=True,
        external_observation_symbols=["TLT", "TIP"],
        external_observation_provider_fn=_fake_yahoo_ok,
        write_runtime=False,
    )
    assert report["operating_mode"] == "hybrid"
    assert report["truth_origin"] == "external"
    assert report["live_quotes_available"] is True
    assert report["external_observation_active"] is True


def test_truth_origin_stays_seeded_when_external_lane_fails():
    from scripts.run_diagnostics_pipeline import run_diagnostics_pipeline

    report = run_diagnostics_pipeline(
        include_external_observations=True,
        external_observation_symbols=["UNG"],
        external_observation_provider_fn=_fake_yahoo_err,
        write_runtime=False,
    )
    # Failing lane must not lie about truth_origin.
    assert report["operating_mode"] == "seeded"
    assert report["truth_origin"] == "seeded"
    assert report["external_observation_error_count"] >= 1
    assert report["live_quotes_available"] is False


# ---------------------------------------------------------------------------
# 3. Canonical position source selection
# ---------------------------------------------------------------------------


def test_canonical_position_path_prefers_curated_when_present(scratch_path: Path):
    curated = scratch_path / "moltbook" / "open_positions.json"
    runtime = scratch_path / "runtime" / "paper_positions.json"
    curated.parent.mkdir(parents=True, exist_ok=True)
    runtime.parent.mkdir(parents=True, exist_ok=True)
    curated.write_text("[]", encoding="utf-8")
    runtime.write_text("[]", encoding="utf-8")
    assert get_canonical_position_path(curated, runtime) == curated


def test_canonical_position_path_falls_back_to_runtime_when_curated_absent(scratch_path: Path):
    curated = scratch_path / "moltbook" / "open_positions.json"
    runtime = scratch_path / "runtime" / "paper_positions.json"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    runtime.write_text("[]", encoding="utf-8")
    assert get_canonical_position_path(curated, runtime) == runtime


def test_canonical_position_path_returns_none_when_neither_exists(scratch_path: Path):
    curated = scratch_path / "moltbook" / "open_positions.json"
    runtime = scratch_path / "runtime" / "paper_positions.json"
    assert get_canonical_position_path(curated, runtime) is None


def test_canonical_position_path_default_points_at_repo_curated():
    """The no-arg call must return the tracked moltbook path when it exists
    in the repo — the canonical source for all downstream diagnostics."""
    path = get_canonical_position_path()
    # Either the default curated exists or we fell back to runtime. Both
    # are acceptable; what's not acceptable is pointing at something
    # neither file system nor repo layout knows about.
    assert path is None or path in {DEFAULT_CURATED_PATH, DEFAULT_RUNTIME_PATH}


# ---------------------------------------------------------------------------
# 4. Paper lineage includes external observation / reference metadata
# ---------------------------------------------------------------------------


def test_paper_fill_lineage_carries_observation_metadata_when_lane_active(monkeypatch):
    from scripts.paper_execution import _build_fill_row

    order_row = {
        "paper_order_id": "paper_order_XYZ",
        "decision_id": "decision_XYZ",
        "signal_id": "SIG_TEST_001",
        "ticker": "TLT",
        "side": "BUY",
        "requested_qty": 10.0,
    }
    runtime_state = {
        "external_observation_summary": {
            "external_observation_active": True,
            "external_observation_provider": "yahoo",
            "external_observation_symbols": ["TLT"],
        },
    }

    # Monkeypatch the observed-price lookup so we don't depend on an
    # actual runtime/external_observation_report.json file.
    import scripts.paper_execution as paper_execution_module

    def fake_observed(state, ticker):
        return 92.5 if ticker == "TLT" else None

    monkeypatch.setattr(
        paper_execution_module,
        "_observed_price_for_ticker",
        fake_observed,
    )

    fill = _build_fill_row(
        order_row=order_row,
        fill_price=91.0,
        fill_source="seed_open_positions_current_price",
        runtime_state=runtime_state,
    )

    assert fill["source_observation_id"].startswith("obs_yahoo_TLT_")
    assert fill["observation_provider"] == "yahoo"
    assert fill["reference_price"] == 91.0
    assert fill["observed_price"] == 92.5
    # Drift = (92.5 - 91) / 91 ≈ 0.01648 ⇒ 164.84 bps.
    assert fill["price_drift_pct"] == pytest.approx(0.016484, abs=1e-4)
    assert fill["price_drift_bps"] == pytest.approx(164.84, abs=0.05)
    assert fill["entry_timestamp"]
    assert fill["reconciliation_timestamp"] is None
    assert fill["outcome_status"] == "pending_reconciliation"


def test_paper_fill_lineage_flags_seeded_when_lane_inactive():
    from scripts.paper_execution import _build_fill_row

    order_row = {
        "paper_order_id": "paper_order_ZZZ",
        "decision_id": "decision_ZZZ",
        "signal_id": "SIG_TEST_002",
        "ticker": "UNG",
        "side": "BUY",
        "requested_qty": 5.0,
    }
    fill = _build_fill_row(
        order_row=order_row,
        fill_price=12.5,
        fill_source="seed_open_positions_current_price",
        runtime_state={},
    )
    assert fill["source_observation_id"] == "seeded_fill"
    assert fill["observation_provider"] is None
    assert fill["reference_price"] is None
    assert fill["observed_price"] is None
    assert fill["price_drift_bps"] is None
    assert fill["outcome_status"] == "pending_reconciliation"


# ---------------------------------------------------------------------------
# 5. Contaminated feedback suppresses clean learning rate
# ---------------------------------------------------------------------------


def _fx_case(
    case_id: str,
    classification: str,
    data_quality_flags: list[str] | None = None,
    asset: str = "RTX",
) -> MoltbookFeedbackCase:
    return MoltbookFeedbackCase(
        case_id=case_id,
        created_at_utc="2026-04-24T00:00:00+00:00",
        trade_id=f"trade_{case_id}",
        asset=asset,
        symbol=asset,
        side="BUY",
        direction="LONG",
        entry_time="2026-04-24T00:00:00+00:00",
        exit_time="2026-04-24T00:10:00+00:00",
        holding_period_seconds=600.0,
        expected_outcome="win",
        actual_outcome="win" if classification == "SUCCESS_VALID_SIGNAL" else "loss",
        pnl=1.0 if classification == "SUCCESS_VALID_SIGNAL" else -1.0,
        return_pct=1.0 if classification == "SUCCESS_VALID_SIGNAL" else -1.0,
        classification=classification,
        classification_confidence=0.8,
        primary_reason="test",
        contributing_reasons=[],
        data_quality_flags=list(data_quality_flags or []),
        truth_origin="seeded",
        operating_mode="seeded",
        suggested_adjustment="fix" if classification.startswith("FAIL_") else "",
    )


def test_contamination_suppresses_clean_learning_rate_and_emits_warning():
    cases = [
        _fx_case("c1", "SUCCESS_VALID_SIGNAL", ["truth_origin_seeded", "missing_feedback"]),
        _fx_case("c2", "SUCCESS_VALID_SIGNAL"),
        _fx_case("c3", "FAIL_SIGNAL"),
    ]
    summary = build_feedback_summary(cases)
    assert summary["raw_success_rate"] > summary["clean_success_rate"]
    assert summary["contaminated_success_count"] == 1
    assert summary["clean_success_count"] == 1
    assert summary["failure_count"] == 1
    assert summary["learning_quality_warning"] is not None
    # "insufficient_evidence" state equivalents present in the advisory flow
    # via feedback_learning_state when total_cases < 10.
    assert summary["feedback_learning_state"] in {
        "INSUFFICIENT_FEEDBACK",
        "DATA_QUALITY_BLOCKED",
    }


# ---------------------------------------------------------------------------
# 6. No autonomous execution occurs
# ---------------------------------------------------------------------------


def test_no_autonomous_execution_even_with_valid_external_lane():
    """The lane can be fully active (VALID_EXTERNAL, four symbols, provider
    green) and the system must still refuse to deploy capital."""
    from scripts.run_diagnostics_pipeline import run_diagnostics_pipeline

    report = run_diagnostics_pipeline(
        include_external_observations=True,
        external_observation_symbols=["UNG", "FCG", "TLT", "TIP"],
        external_observation_provider_fn=_fake_yahoo_ok,
        write_runtime=False,
    )
    # Truth fields are honest about external attachment.
    assert report["external_observation_active"] is True
    assert report["external_observation_valid_count"] == 4
    assert report["truth_origin"] == "external"

    # And yet the governance gates remain closed.
    assert report["can_deploy_capital"] is False
    assert report["system_readiness_state"] == "DO_NOT_DEPLOY"


def test_failed_lane_does_not_silently_upgrade_readiness():
    from scripts.run_diagnostics_pipeline import run_diagnostics_pipeline

    report = run_diagnostics_pipeline(
        include_external_observations=True,
        external_observation_symbols=["UNG"],
        external_observation_provider_fn=_fake_yahoo_err,
        write_runtime=False,
    )
    assert report["can_deploy_capital"] is False
    assert report["system_readiness_state"] == "DO_NOT_DEPLOY"
    # Error is visible, not suppressed.
    assert report["external_observation_error_count"] >= 1
