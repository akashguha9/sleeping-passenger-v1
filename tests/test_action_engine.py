import json
import subprocess
import sys
from pathlib import Path

from scripts.action_engine import build_action_report


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
