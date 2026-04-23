from __future__ import annotations

from scripts.action_engine import build_action_report
from scripts.perception_control import build_perception_control_report
from scripts.run_diagnostics_pipeline import run_diagnostics_pipeline
from scripts.runtime_common import build_runtime_state_from_scm_report_payload
from scripts.signal_conversion_monitor import build_signal_conversion_report
from scripts.signal_refinery import build_signal_refinery_report


def test_deprivation_filter_suppresses_weak_low_attachment_signal() -> None:
    runtime_state = {
        "per_signal_attribution": [
            {
                "ticker": "NOI",
                "status": "WATCHLIST",
                "ce_score": 0.21,
                "watchlist_tier": "STANDARD",
                "pre_entry_state": "NONE",
                "blocker_attribution": "GSCE_PHASE_LOCK",
            }
        ]
    }

    report = build_perception_control_report(runtime_state=runtime_state, write_runtime=False)
    row = report["signals"][0]

    assert row["deprivation_pass"] is False
    assert row["visibility_state"] == "SUPPRESSED"
    assert "weak_asset_attachment" in row["deprivation_reason_codes"]
    assert row["noise_classification"] == "weak_attachment"


def test_high_quality_signals_receive_higher_lux_and_resurfacing_priority() -> None:
    runtime_state = {
        "per_signal_attribution": [
            {
                "signal_id": "SIG_2026_04_20_101",
                "ticker": "STR",
                "status": "WATCHLIST",
                "ce_score": 0.82,
                "watchlist_tier": "PROMOTABLE",
                "pre_entry_state": "CLEAN_ENTRY_ELIGIBLE",
                "blocker_attribution": "NONE",
            },
            {
                "signal_id": "SIG_2026_04_20_102",
                "ticker": "WEK",
                "status": "WATCHLIST",
                "ce_score": 0.46,
                "watchlist_tier": "STANDARD",
                "pre_entry_state": "NONE",
                "blocker_attribution": "GSCE_PHASE_LOCK",
            },
        ]
    }
    signal_refinery_report = {
        "validation_engine": {
            "signals": [
                {
                    "signal_id": "SIG_2026_04_20_101",
                    "ticker": "STR",
                    "validation_score": 0.84,
                    "validation_state": "VALIDATED",
                    "light_score": 0.79,
                    "temporal_position": 0.46,
                    "source_quality_score": 0.76,
                    "blocker_clearance_score": 1.0,
                },
                {
                    "signal_id": "SIG_2026_04_20_102",
                    "ticker": "WEK",
                    "validation_score": 0.41,
                    "validation_state": "NEEDS_CONFIRMATION",
                    "light_score": 0.31,
                    "temporal_position": 0.79,
                    "source_quality_score": 0.48,
                    "blocker_clearance_score": 0.0,
                },
            ]
        },
        "launch_control": {
            "launch_rows": [
                {"ticker": "STR", "launch_state": "REVIEW_READY"},
                {"ticker": "WEK", "launch_state": "OBSERVE"},
            ]
        },
    }

    report = build_perception_control_report(
        runtime_state=runtime_state,
        signal_refinery_report=signal_refinery_report,
        write_runtime=False,
    )
    rows = {row["ticker"]: row for row in report["signals"]}

    assert rows["STR"]["signal_lux"] > rows["WEK"]["signal_lux"]
    assert rows["STR"]["resurfacing_priority"] > rows["WEK"]["resurfacing_priority"]
    assert rows["STR"]["exposure_timing_state"] in {"IMMEDIATE", "NEAR_TERM"}


def test_gravity_mode_rejects_weak_narrative_candidate_before_stronger_structural_one() -> None:
    runtime_state = {
        "per_signal_attribution": [
            {
                "signal_id": "SIG_2026_04_21_201",
                "ticker": "STR",
                "status": "WATCHLIST",
                "ce_score": 0.8,
                "watchlist_tier": "PROMOTABLE",
                "pre_entry_state": "CLEAN_ENTRY_ELIGIBLE",
                "blocker_attribution": "NONE",
            },
            {
                "signal_id": "SIG_2026_04_21_202",
                "ticker": "NAR",
                "status": "WATCHLIST",
                "ce_score": 0.59,
                "watchlist_tier": "STANDARD",
                "pre_entry_state": "NONE",
                "blocker_attribution": "NONE",
            },
        ]
    }
    signal_refinery_report = {
        "validation_engine": {
            "signals": [
                {
                    "signal_id": "SIG_2026_04_21_201",
                    "ticker": "STR",
                    "validation_score": 0.81,
                    "validation_state": "VALIDATED",
                    "light_score": 0.73,
                    "temporal_position": 0.48,
                    "source_quality_score": 0.71,
                    "blocker_clearance_score": 1.0,
                },
                {
                    "signal_id": "SIG_2026_04_21_202",
                    "ticker": "NAR",
                    "validation_score": 0.39,
                    "validation_state": "INVALIDATED",
                    "light_score": 0.34,
                    "temporal_position": 0.68,
                    "source_quality_score": 0.52,
                    "blocker_clearance_score": 1.0,
                    "late_obviousness_flag": True,
                },
            ]
        },
        "launch_control": {
            "launch_rows": [
                {"ticker": "STR", "launch_state": "REVIEW_READY"},
                {"ticker": "NAR", "launch_state": "BLOCKED_VALIDATION"},
            ]
        },
    }

    report = build_perception_control_report(
        runtime_state=runtime_state,
        signal_refinery_report=signal_refinery_report,
        write_runtime=False,
    )
    rows = {row["ticker"]: row for row in report["signals"]}

    assert rows["STR"]["gravity_pass"] is True
    assert rows["NAR"]["gravity_pass"] is False
    assert rows["STR"]["survival_score"] > rows["NAR"]["survival_score"]
    assert any(
        reason in rows["NAR"]["gravity_failure_reasons"]
        for reason in ("weak_explainability", "launch_control_blocked_validation", "weak_spectrum_narrative")
    )


def test_action_engine_contract_stays_review_ready_for_all_clear_strong_candidates() -> None:
    runtime_state = build_runtime_state_from_scm_report_payload(
        build_signal_conversion_report(simulate_all_clear=True)
    )
    signal_refinery_report = build_signal_refinery_report(
        runtime_state=runtime_state,
        write_runtime=False,
    )
    perception_control_report = build_perception_control_report(
        runtime_state=runtime_state,
        signal_refinery_report=signal_refinery_report,
        write_runtime=False,
    )

    report = build_action_report(
        runtime_state=runtime_state,
        signal_refinery_report=signal_refinery_report,
        perception_control_report=perception_control_report,
        write_runtime=False,
    )
    rows = {row["ticker"]: row for row in report["actions"]}

    assert report["summary_by_action"]["REVIEW_FOR_ENTRY"] == 2
    assert rows["RTX"]["action"] == "REVIEW_FOR_ENTRY"
    assert rows["RTX"]["gravity_pass"] is True
    assert rows["RTX"]["perception_control_state"] == "SURVIVED_CONSTRAINT"


def test_diagnostics_pipeline_exposes_perception_control_schema() -> None:
    payload = run_diagnostics_pipeline(write_runtime=False)

    assert payload["perception_control_state"] == payload["perception_control"]["perception_control_state"]
    assert payload["perception_control"]["noise_suppression_ratio"] == 0.429
    assert payload["perception_control"]["gravity_rejection_count"] == 2
    assert payload["perception_control"]["dominant_spectrum_class"] == "structural"
    first = payload["perception_control"]["signals"][0]
    assert {
        "deprivation_pass",
        "signal_lux",
        "gravity_pass",
        "survival_score",
        "action_visibility_priority",
        "exposure_timing_state",
    }.issubset(first.keys())
