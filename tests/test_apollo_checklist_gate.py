from __future__ import annotations

from scripts.core.apollo_checklist_gate import ApolloChecklistGate


def test_apollo_checklist_gate_pass_fail() -> None:
    gate = ApolloChecklistGate(
        {
            "minimum_source_count": 2,
            "chaos_threshold": 0.75,
            "durability_threshold": 0.65,
            "evidence_quality_threshold": 0.60,
        }
    )
    passed = gate.evaluate(
        {
            "source_count": 2,
            "data_truth_origin": "x",
            "license_boundary": "y",
            "context_profile": {"a": 1},
            "risk_state": "STABLE",
            "chaos_state": "CALM",
            "chaos_score": 0.2,
            "durability_score": 0.8,
            "execution_mode": "PAPER_ONLY",
            "real_execution_allowed": False,
            "real_execution_requested": False,
            "evidence_quality_score": 0.8,
            "adapter_status": "AVAILABLE",
            "abort_alarm_codes": [],
            "murcielago_validation_passed": True,
        }
    )
    assert passed["checklist_clearance"] == "PASS"
    failed = gate.evaluate({})
    assert failed["checklist_clearance"] == "FAIL"
    assert failed["max_allowed_action"] == "REJECT"
