"""Unified MVP readiness report — a single ADVISORY truth surface.

Ties advisory safety locks, doctrine status, chronology detector status,
observation-data provenance counts, market-data source chain, and (optionally)
recorded frontend/demo status into one honest report.

HARD RULES (test-enforced):
    * Never turns a lock green falsely. ``can_deploy_capital`` is always False;
      execution authority is always REVOKED in this report.
    * Says exactly what IS ready and what is BLOCKED.
    * Authorizes no action; imports no action_engine/broker/execution/order code.
    * JSON-emitting and human-readable.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

try:
    from scripts.action_doctrine_status import doctrine_status, is_ratified
    from scripts.chronology_detectors import detector_readiness_summary
    from scripts import chronology_replay_lab as lab
    from scripts import chronology_store as cs
    from scripts import manual_decision_board as mdb
    from scripts.market_data_adapter import market_data_source_chain
    from scripts.narrative_operator_wisdom_filter import (
        evaluate_narrative_operator_wisdom_filter,
    )
except ModuleNotFoundError:  # pragma: no cover - script-path fallback
    from action_doctrine_status import doctrine_status, is_ratified
    from chronology_detectors import detector_readiness_summary
    import chronology_replay_lab as lab
    import chronology_store as cs
    import manual_decision_board as mdb
    from market_data_adapter import market_data_source_chain
    from narrative_operator_wisdom_filter import evaluate_narrative_operator_wisdom_filter


def _observation_counts(db_path: str | None) -> dict[str, int]:
    base = {lab.FORWARD_REAL: 0, lab.HISTORICAL_BACKFILL: 0, lab.SYNTHETIC_TEST: 0}
    if not db_path:
        return base
    conn = cs.get_connection(db_path)
    try:
        cs.init_schema(conn)
        return lab.origin_counts(conn)
    finally:
        conn.close()


def build_mvp_readiness_report(
    db_path: str | None = None,
    frontend_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the readiness report. Advisory-only; never deploys capital."""
    authority = evaluate_narrative_operator_wisdom_filter(None).get("action_authority")
    doctrine = doctrine_status()
    detectors = detector_readiness_summary()
    obs_counts = _observation_counts(db_path)
    forward_real = obs_counts[lab.FORWARD_REAL]
    market = market_data_source_chain()
    board = mdb.build_decision_board([])

    detectors_ready = detectors["implemented_count"] == detectors["total_detectors"]
    board_ready = board["board_state"] == mdb.ADVISORY_DECISION_BOARD_AVAILABLE
    ratified = bool(is_ratified())

    ready_states: list[str] = []
    blocked_states: list[str] = []

    # The deploy lock is never green here.
    blocked_states.append("DO_NOT_DEPLOY")

    if detectors_ready:
        ready_states.append("OBSERVATION_MODE_READY")
    if board_ready:
        ready_states.append("ADVISORY_DECISION_BOARD_READY")

    if not ratified:
        blocked_states.append("BLOCKED_BY_DOCTRINE")
    if forward_real == 0:
        blocked_states.append("BLOCKED_BY_FORWARD_OBSERVATION")

    # Demo readiness only when an explicit recorded status says all green.
    demo_ready = bool(
        frontend_status
        and frontend_status.get("tests_pass")
        and frontend_status.get("build_ok")
        and frontend_status.get("typecheck_ok")
    )
    if demo_ready:
        ready_states.append("DEMO_READY")

    return {
        # Advisory safety — never falsified.
        "advisory_only": True,
        "can_deploy_capital": False,
        "execution_authority": authority,  # REVOKED
        "doctrine": doctrine,
        # Capability surfaces.
        "chronology_detectors": detectors,
        "observation_data_counts": obs_counts,
        "forward_real_observations": forward_real,
        "market_data_source_chain": market,
        "advisory_decision_board": {
            "board_state": board["board_state"],
            "execution_authority": board["execution_authority"],
            "operator_contract": board["operator_contract"],
        },
        "frontend_status": frontend_status or {"status": "UNKNOWN"},
        # Honest summary of what is ready vs blocked.
        "ready_states": ready_states,
        "blocked_states": blocked_states,
        "headline": _headline(ready_states, blocked_states),
        "note": (
            "Advisory truth surface. Locks are never turned green here; "
            "OBSERVATION_MODE / DECISION_BOARD readiness do NOT imply execution "
            "readiness. Forward-observation confidence and doctrine ratification "
            "remain human/observation-gated."
        ),
    }


def _headline(ready: list[str], blocked: list[str]) -> str:
    ready_str = ", ".join(ready) if ready else "none"
    return f"DO_NOT_DEPLOY · READY[{ready_str}] · BLOCKED[{', '.join(blocked)}]"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Unified MVP readiness report (advisory-only).")
    parser.add_argument("--db", default=None, help="Optional chronology SQLite db for observation counts.")
    parser.add_argument("--summary", action="store_true", help="Compact human-readable headline.")
    args = parser.parse_args(argv)
    report = build_mvp_readiness_report(db_path=args.db)
    if args.summary:
        print(report["headline"])
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
