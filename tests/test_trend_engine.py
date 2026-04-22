import json
import subprocess
import sys
from pathlib import Path

from scripts.trend_engine import build_trend_report


REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_SNAPSHOT_LOG = REPO_ROOT / "tests" / "fixtures" / "system_snapshots_seed.jsonl"


def test_trend_report_from_seed_snapshot_log() -> None:
    # Use the committed deterministic seed so the test never depends on
    # whatever happens to be in the gitignored logs/system_snapshots.jsonl
    # on the developer's machine.
    report = build_trend_report(log_path=SEED_SNAPSHOT_LOG, write_runtime=False)

    assert report["snapshot_count"] >= 3
    assert report["scm_trend"]["label"] in {"DETERIORATING", "FLAT", "IMPROVING"}
    assert report["chaos_trend"]["label"] in {"DETERIORATING", "FLAT", "IMPROVING"}
    assert report["watchlist_conversion_trend"]["label"] in {"DETERIORATING", "FLAT", "IMPROVING"}
    assert report["policy_improvement_trend"]["label"] in {"DETERIORATING", "FLAT", "IMPROVING"}


def test_trend_report_from_scratch_log() -> None:
    scratch_dir = REPO_ROOT / "tests" / "_tmp_runtime"
    log_path = scratch_dir / "trend_engine_snapshots.jsonl"
    scratch_dir.mkdir(exist_ok=True)
    log_path.write_text(
        "\n".join(
            [
                '{"timestamp":"2026-04-18T12:00:00+00:00","scm_rate":0.2,"scm_state":"LOW_CONVERSION","blockers_active":["GSCE_PHASE_LOCK"],"policy_state":"RESTRICTED","clean_entries":1,"chaos_entries":2,"signals_above_threshold":6,"watchlist_count":3,"chaos_count":2}',
                '{"timestamp":"2026-04-19T12:00:00+00:00","scm_rate":0.25,"scm_state":"LOW_CONVERSION","blockers_active":["GSCE_PHASE_LOCK"],"policy_state":"LIMITED_DEPLOY","clean_entries":2,"chaos_entries":1,"signals_above_threshold":6,"watchlist_count":2,"chaos_count":1}',
                '{"timestamp":"2026-04-20T12:00:00+00:00","scm_rate":0.35,"scm_state":"PARTIAL_CONVERSION","blockers_active":[],"policy_state":"READY","clean_entries":3,"chaos_entries":0,"signals_above_threshold":6,"watchlist_count":1,"chaos_count":0}'
            ]
        ),
        encoding="utf-8",
    )

    try:
        report = build_trend_report(log_path=log_path, write_runtime=False)
        assert report["scm_trend"]["label"] == "IMPROVING"
        assert report["chaos_trend"]["label"] == "IMPROVING"
        assert report["watchlist_conversion_trend"]["label"] == "IMPROVING"
        assert report["policy_improvement_trend"]["label"] == "IMPROVING"
    finally:
        if log_path.exists():
            log_path.unlink()
        if scratch_dir.exists() and not any(scratch_dir.iterdir()):
            scratch_dir.rmdir()


def test_trend_engine_summary_cli() -> None:
    # Point the CLI at the committed seed so the test passes even when
    # logs/system_snapshots.jsonl is absent (fresh clone) or contains
    # unrelated runtime history.
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "trend_engine.py"),
            "--summary",
            "--no-write",
            "--log-path",
            str(SEED_SNAPSHOT_LOG),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    lines = result.stdout.strip().splitlines()
    assert lines[0] == "Trend Engine"
    assert lines[1].startswith("snapshot_count=")
    assert lines[2].startswith("scm_trend=")
    assert lines[3].startswith("chaos_trend=")
    assert lines[4].startswith("watchlist_conversion_trend=")
    assert lines[5].startswith("policy_improvement_trend=")


def test_trend_report_tracks_clean_ready_pending_trigger_persistence() -> None:
    scratch_dir = REPO_ROOT / "tests" / "_tmp_runtime"
    log_path = scratch_dir / "trend_engine_clean_ready_snapshots.jsonl"
    scratch_dir.mkdir(exist_ok=True)
    log_path.write_text(
        "\n".join(
            [
                '{"timestamp":"2026-04-18T12:00:00+00:00","scm_rate":0.2,"scm_state":"LOW_CONVERSION","blockers_active":["GSCE_PHASE_LOCK"],"policy_state":"RESTRICTED","allow_new_risk":false,"clean_entries":1,"chaos_entries":2,"signals_above_threshold":6,"watchlist_count":3,"chaos_count":2,"clean_ready_pending_trigger_count":0,"clean_ready_pending_trigger_names":[],"transition_review_candidate_count":0,"transition_review_candidate_names":[],"entry_review_candidate_count":0,"entry_review_candidate_names":[]}',
                '{"timestamp":"2026-04-19T12:00:00+00:00","scm_rate":0.25,"scm_state":"LOW_CONVERSION","blockers_active":["REALM_BIS"],"policy_state":"RESTRICTED","allow_new_risk":false,"clean_entries":2,"chaos_entries":2,"signals_above_threshold":6,"watchlist_count":2,"chaos_count":2,"clean_ready_pending_trigger_count":1,"clean_ready_pending_trigger_names":["RTX"],"transition_review_candidate_count":1,"transition_review_candidate_names":["RTX"],"entry_review_candidate_count":0,"entry_review_candidate_names":[]}',
                '{"timestamp":"2026-04-20T12:00:00+00:00","scm_rate":0.25,"scm_state":"LOW_CONVERSION","blockers_active":["REALM_BIS"],"policy_state":"RESTRICTED","allow_new_risk":false,"clean_entries":2,"chaos_entries":2,"signals_above_threshold":6,"watchlist_count":2,"chaos_count":2,"clean_ready_pending_trigger_count":2,"clean_ready_pending_trigger_names":["RTX","ZIM"],"transition_review_candidate_count":2,"transition_review_candidate_names":["RTX","ZIM"],"entry_review_candidate_count":0,"entry_review_candidate_names":[]}'
            ]
        ),
        encoding="utf-8",
    )

    try:
        report = build_trend_report(log_path=log_path, write_runtime=False)
        assert report["clean_ready_pending_trigger_trend_label"] == "CLEAN_READY_PENDING_TRIGGER_WORSENING"
        assert report["clean_ready_pending_trigger_persistence"]["current_names"] == ["RTX", "ZIM"]
        assert report["clean_ready_pending_transition_streak"] == {
            "current_count": 2,
            "current_names": ["RTX", "ZIM"],
            "persistent_names": [
                {"ticker": "RTX", "consecutive_snapshots": 2},
                {"ticker": "ZIM", "consecutive_snapshots": 1},
            ],
        }
        assert report["transition_pressure_state"] == "TRANSITIONING"
        assert report["transition_readiness_state"] == "ADVANCING"
        assert report["packet_transition_state"] == "TRANSITION_REVIEW_READY"
        assert report["packet_entry_state"] == "NONE"
        assert report["transition_review_candidate_streak"] == {
            "current_count": 2,
            "current_names": ["RTX", "ZIM"],
            "consecutive_snapshots": 2,
        }
        assert report["entry_review_candidate_streak"] == {
            "current_count": 0,
            "current_names": [],
            "consecutive_snapshots": 0,
        }
        assert report["clean_ready_pending_trigger_persistence"]["persistent_names"][0] == {
            "ticker": "RTX",
            "consecutive_snapshots": 2,
        }
    finally:
        if log_path.exists():
            log_path.unlink()
        if scratch_dir.exists() and not any(scratch_dir.iterdir()):
            scratch_dir.rmdir()


def test_trend_report_tracks_blocked_promotable_transition_streak() -> None:
    scratch_dir = REPO_ROOT / "tests" / "_tmp_runtime"
    log_path = scratch_dir / "trend_engine_blocked_transition_snapshots.jsonl"
    scratch_dir.mkdir(exist_ok=True)
    log_path.write_text(
        "\n".join(
            [
                '{"timestamp":"2026-04-18T12:00:00+00:00","scm_rate":0.2,"scm_state":"LOW_CONVERSION","blockers_active":["GSCE_PHASE_LOCK","REALM_BIS"],"policy_state":"RESTRICTED","allow_new_risk":false,"clean_entries":1,"chaos_entries":2,"signals_above_threshold":6,"watchlist_count":3,"chaos_count":2,"blocked_promotable_candidate_count":1,"blocked_promotable_candidate_names":["RTX"],"transition_review_candidate_count":0,"transition_review_candidate_names":[],"entry_review_candidate_count":0,"entry_review_candidate_names":[]}',
                '{"timestamp":"2026-04-19T12:00:00+00:00","scm_rate":0.2,"scm_state":"LOW_CONVERSION","blockers_active":["GSCE_PHASE_LOCK","REALM_BIS"],"policy_state":"RESTRICTED","allow_new_risk":false,"clean_entries":1,"chaos_entries":2,"signals_above_threshold":6,"watchlist_count":3,"chaos_count":2,"blocked_promotable_candidate_count":2,"blocked_promotable_candidate_names":["RTX","ZIM"],"transition_review_candidate_count":0,"transition_review_candidate_names":[],"entry_review_candidate_count":0,"entry_review_candidate_names":[]}',
                '{"timestamp":"2026-04-20T12:00:00+00:00","scm_rate":0.2,"scm_state":"LOW_CONVERSION","blockers_active":["GSCE_PHASE_LOCK","REALM_BIS"],"policy_state":"RESTRICTED","allow_new_risk":false,"clean_entries":1,"chaos_entries":2,"signals_above_threshold":6,"watchlist_count":3,"chaos_count":2,"blocked_promotable_candidate_count":2,"blocked_promotable_candidate_names":["RTX","ZIM"],"transition_review_candidate_count":0,"transition_review_candidate_names":[],"entry_review_candidate_count":0,"entry_review_candidate_names":[]}'
            ]
        ),
        encoding="utf-8",
    )

    try:
        report = build_trend_report(log_path=log_path, write_runtime=False)
        assert report["blocked_promotable_transition_streak"] == {
            "current_count": 2,
            "current_names": ["RTX", "ZIM"],
            "persistent_names": [
                {"ticker": "RTX", "consecutive_snapshots": 3},
                {"ticker": "ZIM", "consecutive_snapshots": 2},
            ],
        }
        assert report["transition_pressure_state"] == "STUCK_BLOCKED"
        assert report["transition_readiness_state"] == "BLOCKED"
        assert report["packet_transition_state"] == "NONE"
        assert report["packet_entry_state"] == "NONE"
    finally:
        if log_path.exists():
            log_path.unlink()
        if scratch_dir.exists() and not any(scratch_dir.iterdir()):
            scratch_dir.rmdir()


def test_trend_report_tracks_clean_entry_eligible_persistence() -> None:
    scratch_dir = REPO_ROOT / "tests" / "_tmp_runtime"
    log_path = scratch_dir / "trend_engine_clean_entry_eligible_snapshots.jsonl"
    scratch_dir.mkdir(exist_ok=True)
    log_path.write_text(
        "\n".join(
            [
                '{"timestamp":"2026-04-18T12:00:00+00:00","scm_rate":0.2,"scm_state":"LOW_CONVERSION","blockers_active":["GSCE_PHASE_LOCK","REALM_BIS"],"policy_state":"RESTRICTED","allow_new_risk":false,"clean_entries":1,"chaos_entries":2,"signals_above_threshold":6,"watchlist_count":3,"chaos_count":2,"clean_entry_eligible_count":0,"clean_entry_eligible_names":[],"entry_review_candidate_count":0,"entry_review_candidate_names":[],"transition_review_candidate_count":0,"transition_review_candidate_names":[]}',
                '{"timestamp":"2026-04-19T12:00:00+00:00","scm_rate":0.25,"scm_state":"LOW_CONVERSION","blockers_active":[],"policy_state":"REVIEW_READY","allow_new_risk":true,"clean_entries":2,"chaos_entries":2,"signals_above_threshold":6,"watchlist_count":1,"chaos_count":2,"clean_entry_eligible_count":1,"clean_entry_eligible_names":["RTX"],"entry_review_candidate_count":1,"entry_review_candidate_names":["RTX"],"transition_review_candidate_count":0,"transition_review_candidate_names":[]}',
                '{"timestamp":"2026-04-20T12:00:00+00:00","scm_rate":0.25,"scm_state":"LOW_CONVERSION","blockers_active":[],"policy_state":"REVIEW_READY","allow_new_risk":true,"clean_entries":2,"chaos_entries":2,"signals_above_threshold":6,"watchlist_count":1,"chaos_count":2,"clean_entry_eligible_count":2,"clean_entry_eligible_names":["RTX","ZIM"],"entry_review_candidate_count":2,"entry_review_candidate_names":["RTX","ZIM"],"transition_review_candidate_count":0,"transition_review_candidate_names":[]}'
            ]
        ),
        encoding="utf-8",
    )

    try:
        report = build_trend_report(log_path=log_path, write_runtime=False)
        assert report["clean_entry_eligible_trend_label"] == "CLEAN_ENTRY_ELIGIBLE_WORSENING"
        assert report["clean_entry_eligible_persistence"]["current_names"] == ["RTX", "ZIM"]
        assert report["clean_entry_eligible_transition_streak"] == {
            "current_count": 2,
            "current_names": ["RTX", "ZIM"],
            "persistent_names": [
                {"ticker": "RTX", "consecutive_snapshots": 2},
                {"ticker": "ZIM", "consecutive_snapshots": 1},
            ],
        }
        assert report["transition_pressure_state"] == "READY_BUT_UNTRIGGERED"
        assert report["transition_readiness_state"] == "ENTRY_REVIEW_READY"
        assert report["packet_transition_state"] == "NONE"
        assert report["packet_entry_state"] == "ENTRY_REVIEW_READY"
        assert report["entry_review_candidate_streak"] == {
            "current_count": 2,
            "current_names": ["RTX", "ZIM"],
            "consecutive_snapshots": 2,
        }
        assert report["transition_review_candidate_streak"] == {
            "current_count": 0,
            "current_names": [],
            "consecutive_snapshots": 0,
        }
        assert report["fully_cleared_candidate_streak"] == {
            "current_count": 2,
            "current_names": ["RTX", "ZIM"],
            "consecutive_snapshots": 2,
        }
    finally:
        if log_path.exists():
            log_path.unlink()
        if scratch_dir.exists() and not any(scratch_dir.iterdir()):
            scratch_dir.rmdir()


def test_trend_report_groups_transition_persistence_by_scenario() -> None:
    scratch_dir = REPO_ROOT / "tests" / "_tmp_runtime"
    log_path = scratch_dir / "trend_engine_scenario_snapshots.jsonl"
    scratch_dir.mkdir(exist_ok=True)
    log_path.write_text(
        "\n".join(
            [
                '{"timestamp":"2026-04-18T09:00:00+00:00","scenario":"LIVE","scm_rate":0.2,"scm_state":"LOW_CONVERSION","blockers_active":["GSCE_PHASE_LOCK","REALM_BIS"],"policy_state":"RESTRICTED","allow_new_risk":false,"clean_entries":1,"chaos_entries":2,"signals_above_threshold":6,"watchlist_count":3,"chaos_count":2,"blocked_promotable_candidate_count":2,"blocked_promotable_candidate_names":["RTX","ZIM"],"clean_ready_pending_trigger_count":0,"clean_ready_pending_trigger_names":[],"clean_entry_eligible_count":0,"clean_entry_eligible_names":[],"transition_review_candidate_count":0,"transition_review_candidate_names":[],"entry_review_candidate_count":0,"entry_review_candidate_names":[]}',
                '{"timestamp":"2026-04-19T09:00:00+00:00","scenario":"LIVE","scm_rate":0.2,"scm_state":"LOW_CONVERSION","blockers_active":["GSCE_PHASE_LOCK","REALM_BIS"],"policy_state":"RESTRICTED","allow_new_risk":false,"clean_entries":1,"chaos_entries":2,"signals_above_threshold":6,"watchlist_count":3,"chaos_count":2,"blocked_promotable_candidate_count":2,"blocked_promotable_candidate_names":["RTX","ZIM"],"clean_ready_pending_trigger_count":0,"clean_ready_pending_trigger_names":[],"clean_entry_eligible_count":0,"clean_entry_eligible_names":[],"transition_review_candidate_count":0,"transition_review_candidate_names":[],"entry_review_candidate_count":0,"entry_review_candidate_names":[]}',
                '{"timestamp":"2026-04-18T10:00:00+00:00","scenario":"GSCE_CLEAR","scm_rate":0.2,"scm_state":"LOW_CONVERSION","blockers_active":["REALM_BIS"],"policy_state":"RESTRICTED","allow_new_risk":false,"clean_entries":1,"chaos_entries":2,"signals_above_threshold":6,"watchlist_count":3,"chaos_count":2,"blocked_promotable_candidate_count":0,"blocked_promotable_candidate_names":[],"clean_ready_pending_trigger_count":2,"clean_ready_pending_trigger_names":["RTX","ZIM"],"clean_entry_eligible_count":0,"clean_entry_eligible_names":[],"transition_review_candidate_count":2,"transition_review_candidate_names":["RTX","ZIM"],"entry_review_candidate_count":0,"entry_review_candidate_names":[]}',
                '{"timestamp":"2026-04-19T10:00:00+00:00","scenario":"GSCE_CLEAR","scm_rate":0.2,"scm_state":"LOW_CONVERSION","blockers_active":["REALM_BIS"],"policy_state":"RESTRICTED","allow_new_risk":false,"clean_entries":1,"chaos_entries":2,"signals_above_threshold":6,"watchlist_count":3,"chaos_count":2,"blocked_promotable_candidate_count":0,"blocked_promotable_candidate_names":[],"clean_ready_pending_trigger_count":2,"clean_ready_pending_trigger_names":["RTX","ZIM"],"clean_entry_eligible_count":0,"clean_entry_eligible_names":[],"transition_review_candidate_count":2,"transition_review_candidate_names":["RTX","ZIM"],"entry_review_candidate_count":0,"entry_review_candidate_names":[]}',
                '{"timestamp":"2026-04-18T11:00:00+00:00","scenario":"REALM_BIS_CLEAR","scm_rate":0.2,"scm_state":"LOW_CONVERSION","blockers_active":["GSCE_PHASE_LOCK"],"policy_state":"RESTRICTED","allow_new_risk":false,"clean_entries":1,"chaos_entries":2,"signals_above_threshold":6,"watchlist_count":3,"chaos_count":2,"blocked_promotable_candidate_count":2,"blocked_promotable_candidate_names":["RTX","ZIM"],"clean_ready_pending_trigger_count":0,"clean_ready_pending_trigger_names":[],"clean_entry_eligible_count":0,"clean_entry_eligible_names":[],"transition_review_candidate_count":0,"transition_review_candidate_names":[],"entry_review_candidate_count":0,"entry_review_candidate_names":[]}',
                '{"timestamp":"2026-04-18T12:00:00+00:00","scenario":"ALL_CLEAR","scm_rate":0.2,"scm_state":"LOW_CONVERSION","blockers_active":[],"policy_state":"REVIEW_READY","allow_new_risk":true,"clean_entries":1,"chaos_entries":2,"signals_above_threshold":6,"watchlist_count":3,"chaos_count":2,"blocked_promotable_candidate_count":0,"blocked_promotable_candidate_names":[],"clean_ready_pending_trigger_count":0,"clean_ready_pending_trigger_names":[],"clean_entry_eligible_count":2,"clean_entry_eligible_names":["RTX","ZIM"],"transition_review_candidate_count":0,"transition_review_candidate_names":[],"entry_review_candidate_count":2,"entry_review_candidate_names":["RTX","ZIM"]}',
                '{"timestamp":"2026-04-19T12:00:00+00:00","scenario":"ALL_CLEAR","scm_rate":0.2,"scm_state":"LOW_CONVERSION","blockers_active":[],"policy_state":"REVIEW_READY","allow_new_risk":true,"clean_entries":1,"chaos_entries":2,"signals_above_threshold":6,"watchlist_count":3,"chaos_count":2,"blocked_promotable_candidate_count":0,"blocked_promotable_candidate_names":[],"clean_ready_pending_trigger_count":0,"clean_ready_pending_trigger_names":[],"clean_entry_eligible_count":2,"clean_entry_eligible_names":["RTX","ZIM"],"transition_review_candidate_count":0,"transition_review_candidate_names":[],"entry_review_candidate_count":2,"entry_review_candidate_names":["RTX","ZIM"]}'
            ]
        ),
        encoding="utf-8",
    )

    try:
        report = build_trend_report(log_path=log_path, write_runtime=False)
        assert report["scenario_scope"] == "LIVE"
        assert report["snapshot_count"] == 2
        assert report["transition_pressure_state"] == "STUCK_BLOCKED"
        assert report["transition_readiness_state"] == "BLOCKED"
        assert report["packet_transition_state"] == "NONE"
        assert report["packet_entry_state"] == "NONE"
        assert report["scenario_transition_trends"]["LIVE"]["blocked_promotable_transition_streak"] == {
            "current_count": 2,
            "current_names": ["RTX", "ZIM"],
            "persistent_names": [
                {"ticker": "RTX", "consecutive_snapshots": 2},
                {"ticker": "ZIM", "consecutive_snapshots": 2},
            ],
        }
        assert report["scenario_transition_trends"]["GSCE_CLEAR"]["transition_review_candidate_streak"] == {
            "current_count": 2,
            "current_names": ["RTX", "ZIM"],
            "consecutive_snapshots": 2,
        }
        assert report["scenario_transition_trends"]["GSCE_CLEAR"]["packet_transition_state"] == "TRANSITION_REVIEW_READY"
        assert report["scenario_transition_trends"]["GSCE_CLEAR"]["transition_readiness_state"] == "ADVANCING"
        assert report["scenario_transition_trends"]["REALM_BIS_CLEAR"]["transition_pressure_state"] == "STUCK_BLOCKED"
        assert report["scenario_transition_trends"]["REALM_BIS_CLEAR"]["packet_transition_state"] == "NONE"
        assert report["scenario_transition_trends"]["ALL_CLEAR"]["entry_review_candidate_streak"] == {
            "current_count": 2,
            "current_names": ["RTX", "ZIM"],
            "consecutive_snapshots": 2,
        }
        assert report["scenario_transition_trends"]["ALL_CLEAR"]["packet_entry_state"] == "ENTRY_REVIEW_READY"
        assert report["scenario_transition_trends"]["ALL_CLEAR"]["transition_readiness_state"] == "ENTRY_REVIEW_READY"

        all_clear_report = build_trend_report(
            log_path=log_path,
            write_runtime=False,
            scenario_scope="ALL_CLEAR",
        )
        assert all_clear_report["scenario_scope"] == "ALL_CLEAR"
        assert all_clear_report["snapshot_count"] == 2
        assert all_clear_report["transition_pressure_state"] == "READY_BUT_UNTRIGGERED"
        assert all_clear_report["transition_readiness_state"] == "ENTRY_REVIEW_READY"
        assert all_clear_report["packet_entry_state"] == "ENTRY_REVIEW_READY"
    finally:
        if log_path.exists():
            log_path.unlink()
        if scratch_dir.exists() and not any(scratch_dir.iterdir()):
            scratch_dir.rmdir()
