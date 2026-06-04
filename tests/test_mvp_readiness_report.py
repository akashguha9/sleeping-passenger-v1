"""Unified MVP readiness report — advisory truth surface (Phase 5)."""

import ast
import json
from pathlib import Path

from scripts import mvp_readiness_report as mvp
from scripts import chronology_store as cs
from scripts import chronology_replay_lab as lab

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def test_report_never_turns_locks_green() -> None:
    r = mvp.build_mvp_readiness_report()
    assert r["can_deploy_capital"] is False
    assert r["execution_authority"] == "REVOKED"
    assert r["advisory_only"] is True
    assert "DO_NOT_DEPLOY" in r["blocked_states"]


def test_report_reports_observation_and_board_ready_but_blocked_states() -> None:
    r = mvp.build_mvp_readiness_report()
    assert "OBSERVATION_MODE_READY" in r["ready_states"]
    assert "ADVISORY_DECISION_BOARD_READY" in r["ready_states"]
    # Doctrine unratified + no forward observations -> both blockers present.
    assert "BLOCKED_BY_DOCTRINE" in r["blocked_states"]
    assert "BLOCKED_BY_FORWARD_OBSERVATION" in r["blocked_states"]
    assert "DEMO_READY" not in r["ready_states"]


def test_report_counts_forward_observations_from_db(tmp_path) -> None:
    conn = cs.get_connection(tmp_path / "m.db")
    cs.init_schema(conn)
    cs.log_signal_candidate(conn, {
        "candidate_id": "c1", "ticker": "AAA", "first_seen_ts": "t", "source": "x",
        "payload_json": json.dumps({"data_origin": "FORWARD_REAL"}),
    })
    conn.close()
    r = mvp.build_mvp_readiness_report(db_path=str(tmp_path / "m.db"))
    assert r["forward_real_observations"] == 1
    # With a forward-real row present, that specific blocker lifts.
    assert "BLOCKED_BY_FORWARD_OBSERVATION" not in r["blocked_states"]


def test_demo_ready_only_when_recorded_status_all_green() -> None:
    r = mvp.build_mvp_readiness_report(
        frontend_status={"tests_pass": True, "build_ok": True, "typecheck_ok": True}
    )
    assert "DEMO_READY" in r["ready_states"]
    r2 = mvp.build_mvp_readiness_report(frontend_status={"tests_pass": True})
    assert "DEMO_READY" not in r2["ready_states"]


def test_report_is_json_serializable_and_has_no_forbidden_terms() -> None:
    blob = json.dumps(mvp.build_mvp_readiness_report()).upper()
    for term in ("BUY", "SELL", "BROKER_ROUTE", "PLACE_ORDER"):
        assert term not in blob


def test_no_execution_or_broker_imports() -> None:
    tree = ast.parse((SCRIPTS / "mvp_readiness_report.py").read_text(encoding="utf-8-sig"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    joined = " ".join(imported).lower()
    for bad in ("action_engine", "broker", "execution_governance", "paper_execution", "order"):
        assert bad not in joined
