from __future__ import annotations

from scripts.core.apollo_abort_guard import ApolloAbortGuard


def test_apollo_abort_guard_alarms() -> None:
    guard = ApolloAbortGuard({"chaos_threshold": 0.75, "durability_threshold": 0.65})
    report = guard.evaluate(
        {
            "data_truth_origin": "",
            "license_boundary": "",
            "chaos_state": "DIABLO",
            "real_execution_requested": True,
            "execution_mode": "LIVE",
            "risk_state": "UNSTABLE",
        }
    )
    codes = {alarm["code"] for alarm in report["alarms"]}
    assert "A1201_DATA_ORIGIN_MISSING" in codes
    assert "A1202_LICENSE_BOUNDARY_MISSING" in codes
    assert report["apollo_clearance"] == "ABORT"
    assert report["real_execution_allowed"] is False
