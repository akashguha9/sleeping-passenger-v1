"""Plumbing case study v4: calibrated architecture, honest readiness."""

from __future__ import annotations

import json

from src.alpha.plumbing_case_study import build_plumbing_case_study_v4

_REQUIRED_NODE_FIELDS = (
    "casino_score",
    "food_chain_score",
    "residual_utility_class",
    "blind_test_differential",
    "embedded_proof_class",
    "triangulation_class",
    "raw_event_probability",
    "calibrated_event_probability_status",
    "calibration_gate_tier",
    "evidence_bundle_id",
    "advisory_verdict",
    "why_not_higher",
    "next_evidence_to_collect",
)


def test_v4_extends_v3_with_calibrated_architecture() -> None:
    case_study = build_plumbing_case_study_v4()
    assert case_study["version"] == "v4"
    for key in (
        "calibration_summary",
        "reliability",
        "operator_checklist",
        "node_reports",
        "readiness_statement",
    ):
        assert key in case_study


def test_all_three_node_reports_complete() -> None:
    reports = build_plumbing_case_study_v4()["node_reports"]
    for node_id in ("plumbers_contractors", "valves", "smart_leak_sensors"):
        assert node_id in reports
        for field in _REQUIRED_NODE_FIELDS:
            assert field in reports[node_id], (node_id, field)


def test_calibration_honestly_unavailable_on_empty_journal() -> None:
    case_study = build_plumbing_case_study_v4()
    assert case_study["calibration_summary"]["method"] == "insufficient_data"
    assert case_study["calibration_summary"]["calibration_available"] is False
    for report in case_study["node_reports"].values():
        assert report["calibrated_event_probability_status"] == "insufficient_data"
        assert report["calibration_gate_tier"] == "uncalibrated"


def test_readiness_statement_refuses_to_overstate() -> None:
    statement = build_plumbing_case_study_v4()["readiness_statement"]
    assert "research-grade" in statement
    assert "Not fully calibrated" in statement
    assert "resolved advisory outcome" in statement


def test_evidence_bundles_are_deterministic_and_distinct() -> None:
    first = build_plumbing_case_study_v4()["node_reports"]
    second = build_plumbing_case_study_v4()["node_reports"]
    ids_first = [report["evidence_bundle_id"] for report in first.values()]
    ids_second = [report["evidence_bundle_id"] for report in second.values()]
    assert ids_first == ids_second
    assert len(set(ids_first)) == len(ids_first)  # one bundle per node


def test_operator_checklist_points_at_the_data_gap() -> None:
    checklist = build_plumbing_case_study_v4()["operator_checklist"]
    assert checklist["records_needed"] == 50
    assert checklist["next_actions"]


def test_v4_json_safe_no_execution_language() -> None:
    case_study = build_plumbing_case_study_v4()
    text = json.dumps(case_study).lower()
    for forbidden in ("guaranteed return", "place order", "broker api", "buy now"):
        assert forbidden not in text
    assert json.loads(json.dumps(case_study)) is not None
