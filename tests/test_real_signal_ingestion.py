from __future__ import annotations

from scripts.action_engine import build_action_report
from scripts.pipeline_health_report import (
    build_pipeline_health_report,
    format_pipeline_health_summary,
)
from scripts.runtime_common import build_runtime_state_from_scm_report_payload
from scripts.signal_conversion_monitor import build_signal_conversion_report


def _external_gamma_signal() -> list[dict]:
    return [
        {
            "signal_id": "SIG_POLY_GAMMA_TEST_001",
            "ticker": "PM_GAMMA_TEST",
            "ce_score": 0.6,
            "priority_score": 0.6,
            "status": "WATCHLIST",
            "conversion_state": "NOT_EXECUTED",
            "blocker_attribution": "NONE",
            "promotable_clean_candidate": False,
            "watchlist_tier": "STANDARD",
            "candidate_conversion_state": "NOT_EXECUTED",
            "pre_entry_state": "NONE",
            "source_name": "polymarket_gamma",
            "signal_origin": "external",
            "origin_label": "polymarket_gamma_public_market",
            "condition_id": "0xgamma",
            "question": "Will gamma integration stay read only?",
        }
    ]


def test_external_gamma_signal_merges_into_signal_pipeline() -> None:
    scm_report = build_signal_conversion_report(
        external_signal_inputs=_external_gamma_signal(),
        include_external_signal_inputs=False,
    )

    assert scm_report["external_signal_inputs_count"] == 1
    assert scm_report["signal_summary"]["signal_count_total"] == 9
    assert scm_report["signal_summary"]["signals_above_ce_threshold"] == 8
    assert scm_report["signal_summary"]["status_counts_above_threshold"] == {
        "EXECUTED_CLEAN": 2,
        "EXECUTED_CHAOS": 2,
        "WATCHLIST": 4,
    }
    rows_by_ticker = {
        row["ticker"]: row
        for row in scm_report["per_signal_attribution"]
    }
    assert rows_by_ticker["PM_GAMMA_TEST"]["source_name"] == "polymarket_gamma"
    assert rows_by_ticker["PM_GAMMA_TEST"]["signal_origin"] == "external"
    assert rows_by_ticker["PM_GAMMA_TEST"]["status"] == "WATCHLIST"

    runtime_state = build_runtime_state_from_scm_report_payload(scm_report)
    action_report = build_action_report(runtime_state=runtime_state, write_runtime=False)
    action_rows = {row["ticker"]: row for row in action_report["actions"]}

    # External row exists in seeded runtime; canonical permission still
    # downgrades to ADVISORY_ONLY because evidence ledger has no
    # outcome-labelled records and policy/calibration gates remain shut.
    assert action_rows["PM_GAMMA_TEST"]["action"] == "ADVISORY_ONLY"
    assert action_rows["PM_GAMMA_TEST"]["raw_action_signal"] == "BLOCK_ENTRY"
    assert action_rows["PM_GAMMA_TEST"]["execution_status"] == "DIAGNOSTIC_ONLY"
    assert action_rows["PM_GAMMA_TEST"]["execution_governance"]["suggestion_only"] is True
    assert action_rows["PM_GAMMA_TEST"]["execution_governance"]["human_execution_required"] is True


def test_pipeline_health_report_exposes_seeded_vs_external_signal_counts() -> None:
    scm_report = build_signal_conversion_report(
        external_signal_inputs=_external_gamma_signal(),
        include_external_signal_inputs=False,
    )
    runtime_state = build_runtime_state_from_scm_report_payload(scm_report)
    action_report = build_action_report(runtime_state=runtime_state, write_runtime=False)
    health_report = build_pipeline_health_report(
        include_tests=False,
        write_runtime=False,
        runtime_state=runtime_state,
        action_report=action_report,
    )

    assert health_report["signal_source_summary"] == {
        "total_signal_count": 8,
        "seeded_signal_count": 7,
        "external_signal_count": 1,
        "unknown_signal_count": 0,
        "source_counts": {
            "signal_ledger": 7,
            "polymarket_gamma": 1,
        },
        "external_signal_tickers": ["PM_GAMMA_TEST"],
    }

    summary_lines = format_pipeline_health_summary(health_report).splitlines()
    assert "signal_sources=seeded=7, external=1" in summary_lines
