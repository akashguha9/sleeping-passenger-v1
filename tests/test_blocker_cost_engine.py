import json
import subprocess
import sys
from pathlib import Path

from scripts.blocker_cost_engine import build_blocker_cost_report


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_blocker_cost_report_from_live_seed_state() -> None:
    report = build_blocker_cost_report(write_runtime=False)

    assert report == {
        "active_blockers": ["GSCE_PHASE_LOCK", "REALM_BIS"],
        "weights": {
            "GSCE_PHASE_LOCK": 3.0,
            "REALM_BIS": 4.0,
            "CHAOS_ENTRY": 1.5,
            "WATCHLIST_STAGNATION": 1.0,
        },
        "components": [
            {"name": "GSCE_PHASE_LOCK", "count": 1, "unit_weight": 3.0, "score": 3.0},
            {"name": "REALM_BIS", "count": 1, "unit_weight": 4.0, "score": 4.0},
            {"name": "CHAOS_ENTRY", "count": 2, "unit_weight": 1.5, "score": 3.0},
            {"name": "WATCHLIST_STAGNATION", "count": 3, "unit_weight": 1.0, "score": 3.0},
        ],
        "total_system_friction_score": 13.0,
        "friction_band": "HIGH_FRICTION",
    }


def test_blocker_cost_engine_cli_json_shape() -> None:
    result = subprocess.run(
        [sys.executable, "scripts\\blocker_cost_engine.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["friction_band"] == "HIGH_FRICTION"
    assert payload["total_system_friction_score"] == 13.0


def test_blocker_cost_engine_summary_cli() -> None:
    result = subprocess.run(
        [sys.executable, "scripts\\blocker_cost_engine.py", "--summary"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip().splitlines() == [
        "Blocker Cost Engine",
        "friction_band=HIGH_FRICTION",
        "total_system_friction_score=13.0",
        "active_blockers=GSCE_PHASE_LOCK, REALM_BIS",
    ]
