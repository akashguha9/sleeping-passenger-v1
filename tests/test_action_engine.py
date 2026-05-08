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
    report = build_action_report(write_runtime=False)

    assert report["policy_state"] == "RESTRICTED"
    assert report["active_blockers"] == ["GSCE_PHASE_LOCK", "REALM_BIS"]
    # Under the canonical permission contract, seeded mode forces every
    # row's executable ``action`` to ADVISORY_ONLY. The legacy decision
    # is preserved on each row as ``raw_action_signal``.
    assert report["canonical_action_permission"] == "BLOCK_CAPITAL"
    assert report["execution_status"] == "DIAGNOSTIC_ONLY"
    assert report["canonical_block_capital"] is True
    assert report["summary_by_action"]["ADVISORY_ONLY"] == 7
    assert report["execution_governance_summary"]["human_execution_required_count"] == 7
    first = report["actions"][0]
    assert first["ticker"] == "UNG"
    assert first["signal_id"].startswith("SIG_")
    assert first["action"] == "ADVISORY_ONLY"
    assert first["raw_action_signal"] == "EXIT_NOW"
    assert first["execution_status"] == "DIAGNOSTIC_ONLY"
    assert first["canonical_block_capital"] is True
    assert first["action_executable"] is False
    assert first["reasons"] == ["Current price breached stop_loss"]
    assert "canonical_block_capital=BLOCK_CAPITAL" in first["canonical_advisory_note"]
    assert "raw_action_signal=EXIT_NOW" in first["canonical_advisory_note"]
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
    assert report["actions"][1]["raw_action_signal"] == "EXIT_NOW"
    assert report["actions"][1]["action"] == "ADVISORY_ONLY"
    assert report["actions"][2]["ticker"] == "TLT"
    assert report["actions"][2]["raw_action_signal"] == "MONITOR"
    assert report["actions"][2]["action"] == "ADVISORY_ONLY"
    assert report["actions"][3]["ticker"] == "TIP"
    assert report["actions"][3]["raw_action_signal"] == "REDUCE"
    assert report["actions"][3]["action"] == "ADVISORY_ONLY"
    assert "capital deployment" in report["forbidden_use"]
    assert any(reason for reason in report["canonical_veto_reasons"])


def test_action_engine_cli_json_shape() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "action_engine.py")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    # Under canonical BLOCK_CAPITAL, every action row is downgraded to
    # ADVISORY_ONLY but keeps its diagnostic signal.
    assert payload["canonical_action_permission"] == "BLOCK_CAPITAL"
    assert payload["execution_status"] == "DIAGNOSTIC_ONLY"
    assert payload["summary_by_action"]["ADVISORY_ONLY"] == 7
    raw_signals = [row["raw_action_signal"] for row in payload["actions"]]
    assert raw_signals.count("EXIT_NOW") == 2
    assert raw_signals.count("BLOCK_ENTRY") == 3


def test_action_engine_summary_cli() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "action_engine.py"), "--summary"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    lines = result.stdout.strip().splitlines()
    assert lines[0] == "Action Engine"
    assert lines[1] == "policy_state=RESTRICTED"
    assert lines[2] == "active_blockers=GSCE_PHASE_LOCK, REALM_BIS"
    assert lines[3] == "canonical_action_permission=BLOCK_CAPITAL"
    assert lines[4] == "execution_status=DIAGNOSTIC_ONLY"
    assert lines[5].startswith("veto_reasons=[")
    assert "NO_EXTERNAL_TRUTH" in lines[5]
    assert lines[6].startswith("forbidden_use=")
    assert "capital deployment" in lines[6]
    assert lines[7].startswith("summary=")
    assert "ADVISORY_ONLY=7" in lines[7]


def test_build_action_report_from_simulated_gsce_clear_state() -> None:
    runtime_state = build_runtime_state_from_scm_report_payload(
        build_signal_conversion_report(simulate_gsce_clear=True)
    )
    report = build_action_report(runtime_state=runtime_state, write_runtime=False)
    rows = {row["ticker"]: row for row in report["actions"]}

    assert report["policy_state"] == "RESTRICTED"
    assert report["active_blockers"] == ["REALM_BIS"]
    assert report["canonical_action_permission"] == "BLOCK_CAPITAL"
    # Raw diagnostic signal preserved; visible action downgraded.
    assert rows["RTX"]["raw_action_signal"] == "MONITOR"
    assert rows["RTX"]["action"] == "ADVISORY_ONLY"
    assert "Promotable clean candidate advanced to CLEAN_READY_PENDING_TRIGGER after GSCE_PHASE_LOCK cleared; policy still forbids new risk" in rows["RTX"]["reasons"]
    assert rows["ZIM"]["raw_action_signal"] == "MONITOR"
    assert rows["ZIM"]["action"] == "ADVISORY_ONLY"
    assert rows["GLD"]["raw_action_signal"] == "MONITOR"
    assert rows["GLD"]["action"] == "ADVISORY_ONLY"


def test_build_action_report_from_simulated_all_clear_state() -> None:
    runtime_state = build_runtime_state_from_scm_report_payload(
        build_signal_conversion_report(simulate_all_clear=True)
    )
    report = build_action_report(runtime_state=runtime_state, write_runtime=False)
    rows = {row["ticker"]: row for row in report["actions"]}

    assert report["policy_state"] == "REVIEW_READY"
    assert report["active_blockers"] == []
    # Even in the simulated all-clear state, seeded truth_origin and
    # missing external evidence force BLOCK_CAPITAL → ADVISORY_ONLY.
    assert report["canonical_action_permission"] == "BLOCK_CAPITAL"
    assert report["execution_status"] == "DIAGNOSTIC_ONLY"
    assert rows["RTX"]["raw_action_signal"] == "REVIEW_FOR_ENTRY"
    assert rows["RTX"]["action"] == "ADVISORY_ONLY"
    assert rows["ZIM"]["raw_action_signal"] == "REVIEW_FOR_ENTRY"
    assert rows["ZIM"]["action"] == "ADVISORY_ONLY"
    assert rows["GLD"]["raw_action_signal"] == "MONITOR"
    assert rows["GLD"]["action"] == "ADVISORY_ONLY"


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
