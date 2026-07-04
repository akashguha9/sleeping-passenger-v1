import json
import subprocess
import sys
from pathlib import Path

from scripts.action_engine import build_action_report
from scripts.runtime_common import build_runtime_state_from_scm_report_payload
from scripts.signal_conversion_monitor import build_signal_conversion_report


REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_build_action_report_from_live_seed_state() -> None:
    # Close-the-Loop sprint (2026-07-04, forensic audit SP-001): the moltbook
    # ledger is no longer the DEFAULT position source — it is passed here as
    # an EXPLICIT legacy fixture so the stop-breach/EXIT_NOW mechanics stay
    # covered.  Default-source behavior (canonical holdings truth gate,
    # fail-closed) is covered by test_action_engine_canonical_source.py.
    report = build_action_report(
        write_runtime=False,
        open_positions_path=REPO_ROOT / "moltbook" / "open_positions.json",
    )
    assert report["position_source"]["source"] == "EXPLICIT_PATH"

    assert report["policy_state"] == "RESTRICTED"
    assert report["active_blockers"] == ["GSCE_PHASE_LOCK", "REALM_BIS"]
    assert report["summary_by_action"] == {
        "EXIT_NOW": 2,
        "REDUCE": 1,
        "HOLD": 0,
        "MONITOR": 1,
        "BLOCK_ENTRY": 3,
    }
    assert report["execution_governance_summary"]["human_execution_required_count"] == 7
    first = report["actions"][0]
    assert first["ticker"] == "UNG"
    assert first["signal_id"].startswith("SIG_")
    assert first["action"] == "EXIT_NOW"
    assert first["reasons"] == ["Current price breached stop_loss"]
    assert first["policy_state"] == "RESTRICTED"
    assert first["active_blockers"] == ["GSCE_PHASE_LOCK", "REALM_BIS"]
    assert first["has_open_position"] is True
    assert first["position_state"] == "OPEN"
    assert first["entry_type"] == "CHAOS"
    assert first["signal_state"] == "ACTIVE"
    assert first["priority_score"] == 0.91
    assert first["execution_governance"]["suggestion_only"] is True
    assert first["execution_governance"]["human_execution_required"] is True
    assert first["execution_governance"]["approval_state"] == "PENDING_HUMAN_APPROVAL"
    assert first["execution_governance"]["fpeg"]["fpeg_state"] in {
        "pass",
        "review_only",
        "insufficient_reasoning",
    }
    assert first["experience_mode_advisory"] == {
        "recommendation_surface_profile": "trainer",
        "degraded_mode_required": True,
        "confidence_downgrade_required": True,
        "advisory_reason": "surface=trainer; seeded_trainer_surface; premium_blocked_by_gaps; degraded_mode_required; confidence_downgraded",
    }
    assert report["actions"][1]["ticker"] == "FCG"
    assert report["actions"][1]["action"] == "EXIT_NOW"
    assert report["actions"][2]["ticker"] == "TLT"
    assert report["actions"][2]["action"] == "MONITOR"
    assert report["actions"][3]["ticker"] == "TIP"
    assert report["actions"][3]["action"] == "REDUCE"


def test_action_engine_cli_json_shape() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "action_engine.py")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    # Close-the-Loop sprint (2026-07-04): the default source is the canonical
    # holdings truth gate.  The old expectation EXIT_NOW == 2 was produced by
    # phantom moltbook rows (forensic audit SP-001).  Under the hermetic test
    # env the holdings truth is absent, so the engine fails closed: no
    # position-driven exits, and the source/status are stamped in the report.
    assert payload["summary_by_action"]["BLOCK_ENTRY"] == 3
    assert payload["summary_by_action"]["EXIT_NOW"] == 0
    assert payload["position_source"]["source"] == "verified_current_holdings"
    assert payload["position_source"]["status"] == "HOLDINGS_TRUTH_MISSING"


def test_action_engine_summary_cli() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "action_engine.py"), "--summary"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    # Close-the-Loop sprint (2026-07-04): fail-closed default source — the
    # legacy EXIT_NOW=2/REDUCE=1 line came from phantom moltbook positions.
    assert result.stdout.strip().splitlines() == [
        "Action Engine",
        "policy_state=RESTRICTED",
        "active_blockers=GSCE_PHASE_LOCK, REALM_BIS",
        "summary=EXIT_NOW=0, REDUCE=0, HOLD=0, MONITOR=4, BLOCK_ENTRY=3",
    ]


def test_build_action_report_from_simulated_gsce_clear_state() -> None:
    runtime_state = build_runtime_state_from_scm_report_payload(
        build_signal_conversion_report(simulate_gsce_clear=True)
    )
    report = build_action_report(runtime_state=runtime_state, write_runtime=False)
    rows = {row["ticker"]: row for row in report["actions"]}

    assert report["policy_state"] == "RESTRICTED"
    assert report["active_blockers"] == ["REALM_BIS"]
    assert rows["RTX"]["action"] == "MONITOR"
    assert rows["RTX"]["reasons"] == [
        "Promotable clean candidate advanced to CLEAN_READY_PENDING_TRIGGER after GSCE_PHASE_LOCK cleared; policy still forbids new risk"
    ]
    assert rows["ZIM"]["action"] == "MONITOR"
    assert rows["GLD"]["action"] == "MONITOR"


def test_build_action_report_from_simulated_all_clear_state() -> None:
    runtime_state = build_runtime_state_from_scm_report_payload(
        build_signal_conversion_report(simulate_all_clear=True)
    )
    report = build_action_report(runtime_state=runtime_state, write_runtime=False)
    rows = {row["ticker"]: row for row in report["actions"]}

    assert report["policy_state"] == "REVIEW_READY"
    assert report["active_blockers"] == []
    assert report["summary_by_action"]["REVIEW_FOR_ENTRY"] == 2
    assert rows["RTX"]["action"] == "REVIEW_FOR_ENTRY"
    assert rows["RTX"]["reasons"] == [
        "Promotable clean candidate is fully gate-cleared and ready for entry review"
    ]
    assert rows["ZIM"]["action"] == "REVIEW_FOR_ENTRY"
    assert rows["GLD"]["action"] == "MONITOR"


def test_action_report_adds_advisory_annotations_without_changing_decisions(
    scratch_path: Path,
) -> None:
    runtime_state = build_runtime_state_from_scm_report_payload(build_signal_conversion_report())
    experience_path = scratch_path / "experience_mode_report.json"
    controller_path = scratch_path / "complexity_ladder_controller.json"

    _write_json(
        experience_path,
        {
            "trainer_mode_metadata": {
                "trainer_mode_active": False,
                "recommended_surface_profile": "utility",
            },
            "readiness_ladder": {
                "recommended_surface_profile": "utility",
            },
            "utility_resilience_layer": {
                "degraded_mode_required": True,
                "confidence_downgrade_required": True,
            },
        },
    )
    _write_json(
        controller_path,
        {
            "operator_surface_recommendation": "utility",
            "degraded_mode_annotations_required": True,
            "controller_reasoning": [
                "jet_readiness_below_threshold",
                "degraded_mode_annotations_required",
            ],
        },
    )

    baseline = build_action_report(runtime_state=runtime_state, write_runtime=False)
    annotated = build_action_report(
        runtime_state=runtime_state,
        write_runtime=False,
        experience_mode_report_path=experience_path,
        complexity_ladder_controller_path=controller_path,
    )

    assert baseline["summary_by_action"] == annotated["summary_by_action"]
    baseline_decisions = [
        (row["ticker"], row["action"], row["reasons"], row["priority_score"])
        for row in baseline["actions"]
    ]
    annotated_decisions = [
        (row["ticker"], row["action"], row["reasons"], row["priority_score"])
        for row in annotated["actions"]
    ]
    assert baseline_decisions == annotated_decisions
    assert all("experience_mode_advisory" not in row for row in baseline["actions"])
    assert all("experience_mode_advisory" in row for row in annotated["actions"])
    assert annotated["actions"][0]["experience_mode_advisory"] == {
        "recommendation_surface_profile": "utility",
        "degraded_mode_required": True,
        "confidence_downgrade_required": True,
        "advisory_reason": "surface=utility; premium_not_ready; degraded_mode_required; confidence_downgraded",
    }


def test_action_report_omits_advisory_annotations_when_artifacts_missing(
    scratch_path: Path,
) -> None:
    runtime_state = build_runtime_state_from_scm_report_payload(build_signal_conversion_report())
    report = build_action_report(
        runtime_state=runtime_state,
        write_runtime=False,
        experience_mode_report_path=scratch_path / "missing_experience_mode_report.json",
        complexity_ladder_controller_path=scratch_path / "missing_complexity_ladder_controller.json",
    )

    assert all("experience_mode_advisory" not in row for row in report["actions"])
