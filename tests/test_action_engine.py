import json
import subprocess
import sys
from pathlib import Path

from scripts.action_engine import build_action_report
from scripts.runtime_common import build_runtime_state_from_scm_report_payload
from scripts.signal_conversion_monitor import build_signal_conversion_report


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_build_action_report_from_live_seed_state() -> None:
    report = build_action_report(write_runtime=False)

    assert report["policy_state"] == "RESTRICTED"
    assert report["active_blockers"] == ["GSCE_PHASE_LOCK", "REALM_BIS"]
    assert report["summary_by_action"] == {
        "EXIT_NOW": 2,
        "REDUCE": 1,
        "HOLD": 0,
        "MONITOR": 1,
        "BLOCK_ENTRY": 3,
    }
    assert report["actions"][0] == {
        "ticker": "UNG",
        "action": "EXIT_NOW",
        "reasons": [
            "Current price breached stop_loss",
        ],
        "policy_state": "RESTRICTED",
        "active_blockers": ["GSCE_PHASE_LOCK", "REALM_BIS"],
        "has_open_position": True,
        "position_state": "OPEN",
        "entry_type": "CHAOS",
        "signal_state": "ACTIVE",
        "priority_score": 0.91,
    }
    assert report["actions"][1]["ticker"] == "FCG"
    assert report["actions"][1]["action"] == "EXIT_NOW"
    assert report["actions"][2]["ticker"] == "TLT"
    assert report["actions"][2]["action"] == "MONITOR"
    assert report["actions"][3]["ticker"] == "TIP"
    assert report["actions"][3]["action"] == "REDUCE"


def test_action_engine_cli_json_shape() -> None:
    result = subprocess.run(
        [sys.executable, "scripts\\action_engine.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["summary_by_action"]["BLOCK_ENTRY"] == 3
    assert payload["summary_by_action"]["EXIT_NOW"] == 2


def test_action_engine_summary_cli() -> None:
    result = subprocess.run(
        [sys.executable, "scripts\\action_engine.py", "--summary"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip().splitlines() == [
        "Action Engine",
        "policy_state=RESTRICTED",
        "active_blockers=GSCE_PHASE_LOCK, REALM_BIS",
        "summary=EXIT_NOW=2, REDUCE=1, HOLD=0, MONITOR=1, BLOCK_ENTRY=3",
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
