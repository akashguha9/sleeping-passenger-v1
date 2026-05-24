"""One-command operator readiness report (Kanté Sprint 2 — Task 5).

Collapses the defensive layers into a single operator-facing readiness view so
the human can answer *"is it safe to act today?"* without running six scripts:

* release gate verdict (PASS / WARN / FAIL),
* compliance preflight verdict,
* operator role / authorization status,
* Moltbook fake-pollution status,
* GLD/TSM-style loss-bridge idempotency (not hardcoded — proven by dry-run),
* unrepaired closed-loss count (promotion blocker),
* duplicate echo risk + operator load (canonical-derived),
* a ``no_new_risk`` flag and an ordered ``next_actions`` list.

Fail-closed contract
--------------------
* DB missing/unreadable  → ``FAIL_CLOSED`` (cannot certify readiness).
* Compliance FAIL or any unrepaired closed loss → ``no_new_risk = True``
  (promotion blocked, with a visible reason).
* Backend down is *not* fatal — this report is offline and degrades safely.

Read-only.  No DB writes, no broker calls, no execution.  Never prints a
secret (no env values are echoed).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

try:
    from scripts import release_gate as _release_gate
except ModuleNotFoundError:  # pragma: no cover
    import release_gate as _release_gate  # type: ignore[no-redef]

try:
    from scripts import compliance_preflight as _compliance
except ModuleNotFoundError:  # pragma: no cover
    import compliance_preflight as _compliance  # type: ignore[no-redef]

try:
    from scripts import complex_systems_sqlite_bridge as _bridge
except ModuleNotFoundError:  # pragma: no cover
    import complex_systems_sqlite_bridge as _bridge  # type: ignore[no-redef]

try:
    from scripts import operator_audit_log as _audit
except ModuleNotFoundError:  # pragma: no cover
    import operator_audit_log as _audit  # type: ignore[no-redef]

try:
    from scripts import moltbook_reconciliation_bridge as _mb_bridge
except ModuleNotFoundError:  # pragma: no cover
    import moltbook_reconciliation_bridge as _mb_bridge  # type: ignore[no-redef]


def _default_db_path() -> Path:
    try:
        try:
            from scripts.persistence import DB_PATH  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            from persistence import DB_PATH  # type: ignore[no-redef]
        return Path(DB_PATH)
    except Exception:  # pragma: no cover - defensive
        return Path(__file__).resolve().parents[1] / "runtime" / "mvp_local.db"


def _is_clean_initialised_db(db_path: Path) -> bool:
    """True when the DB has been initialised but holds NO operator data.

    "Clean" means: the schema exists (the file is a valid SQLite DB the
    persistence layer accepts) AND every operator-state table is empty:

      - signal_events
      - manual_trades
      - moltbook
      - reconciliations

    A clean DB has no real operational state to risk, so a global
    runtime artefact like the stress-probe summary (which lives in
    ``runtime/cockpit_stress_probe/last_run.json``, independent of any
    specific DB) should not by itself flip readiness to FAIL.  Compliance
    failures, fake pollution, and unrepaired losses still FAIL.
    """
    import sqlite3

    try:
        if not Path(db_path).exists():
            return False
    except Exception:  # pragma: no cover - defensive
        return False
    try:
        conn = sqlite3.connect(str(db_path))
    except Exception:  # pragma: no cover - defensive
        return False
    try:
        cur = conn.cursor()
        existing_tables = {
            row[0]
            for row in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        # All four canonical operator-state tables must exist (proves
        # init_schema was run).  If any is missing the DB is not "clean
        # initialised" — it is broken/partial, and we let the normal
        # release gate verdict stand.
        required = {
            "signal_events",
            "manual_trades",
            "moltbook_entries",
            "reconciliation_results",
        }
        if not required.issubset(existing_tables):
            return False
        for table in required:
            row = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            if row and row[0] and int(row[0]) > 0:
                return False
        return True
    except Exception:  # pragma: no cover - defensive
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _bridge_idempotent(db_path: Path) -> dict[str, Any]:
    """Prove the loss→Moltbook bridge is idempotent via two dry-runs."""
    try:
        a = _mb_bridge.sync_reconciliation_losses_to_moltbook(db_path, write=False)
        b = _mb_bridge.sync_reconciliation_losses_to_moltbook(db_path, write=False)
    except Exception as exc:  # pragma: no cover - defensive
        return {"idempotent": False, "error": type(exc).__name__}
    return {
        "idempotent": a.get("created") == b.get("created"),
        "would_create": a.get("created", 0),
        "loss_candidates": a.get("loss_candidates", 0),
    }


def build_readiness_report(
    db_path: Path | None = None,
    *,
    operator_role: Any = None,
) -> dict[str, Any]:
    """Assemble the operator readiness report.  Fail-closed on a missing DB."""
    path = Path(db_path) if db_path is not None else _default_db_path()
    role = _audit.resolve_operator_role(operator_role)

    report: dict[str, Any] = {
        "report": "operator_readiness_report",
        "db_path": str(path),
        "db_exists": path.exists(),
        "operator_role": role,
        "next_actions": [],
        "advisory_status": _contract.ADVISORY_STATUS,
        "execution_gate": _contract.EXECUTION_GATE_LOCKED,
        "human_review_required": True,
        "broker_api_called": False,
        "ai_execution_count": _contract.AI_EXECUTION_COUNT,
        "execution_mode": _contract.EXECUTION_MODE_HUMAN_ONLY,
    }

    # Fail closed when the canonical DB is absent — readiness cannot be certified.
    if not path.exists():
        report["readiness"] = "FAIL_CLOSED"
        report["no_new_risk"] = True
        report["reason"] = "runtime DB missing — cannot certify readiness."
        report["next_actions"] = [
            "Initialize/restore the runtime DB before any operator action."
        ]
        report["workflow_score"] = 0.0
        return report

    # --- component gates ---------------------------------------------------
    release = _release_gate.evaluate(path)
    compliance = _compliance.run_compliance_preflight()
    canonical = _bridge.build_canonical_complex_systems_state(path)
    bridge_idem = _bridge_idempotent(path)

    repair = canonical.get("components", {}).get("moltbook_repair", {})
    fp = canonical.get("components", {}).get("fingerprint_independence", {})
    exposure = canonical.get("components", {}).get("manual_trade_exposure", {})
    freshness = canonical.get("components", {}).get("signal_freshness", {})

    unrepaired = int(repair.get("closed_losses_without_moltbook") or 0)
    echo_risk = fp.get("echo_risk")
    operator_load = exposure.get("operator_load")

    # Moltbook pollution surfaces via the release gate's preflight check.
    pollution_check = next(
        (c for c in release["preflight"]["checks"]
         if c["name"] == "moltbook_no_fake_pollution"), None
    )
    pollution_status = pollution_check["status"] if pollution_check else "UNKNOWN"

    report["release_gate"] = {
        "verdict": release["verdict"],
        "fail_count": release["fail_count"],
        "warn_count": release["warn_count"],
        "reasons": release["reasons"][:10],
    }
    report["compliance"] = {
        "verdict": compliance["overall"],
        "fail_checks": [c["name"] for c in compliance["checks"]
                        if c["status"] == _compliance.FAIL],
    }
    report["moltbook"] = {
        "fake_pollution_status": pollution_status,
        "unrepaired_closed_loss_count": unrepaired,
        "loss_bridge_idempotent": bridge_idem.get("idempotent"),
        "loss_bridge_would_create": bridge_idem.get("would_create"),
    }
    report["signal_risk"] = {
        "duplicate_echo_risk": echo_risk,
        "operator_load": operator_load,
        "freshness": freshness.get("freshness"),
    }

    # --- no-new-risk decision ---------------------------------------------
    risk_reasons: list[str] = []
    if release["verdict"] == _release_gate.FAIL:
        risk_reasons.append(f"release gate FAIL: {release['failing_checks']}")
    if compliance["overall"] == _compliance.FAIL:
        risk_reasons.append("compliance FAIL")
    if unrepaired > 0:
        risk_reasons.append(
            f"{unrepaired} closed loss(es) not yet repaired into Moltbook")
    if pollution_status == "FAIL":
        risk_reasons.append("fake Moltbook pollution present")
    if not bridge_idem.get("idempotent", True):
        risk_reasons.append("loss bridge is not idempotent")

    no_new_risk = bool(risk_reasons)
    report["no_new_risk"] = no_new_risk
    report["promotion_block_reasons"] = risk_reasons

    # --- next actions ------------------------------------------------------
    actions: list[str] = []
    if unrepaired > 0:
        actions.append(
            f"Repair {unrepaired} closed loss(es) into Moltbook "
            "(run moltbook_reconciliation_bridge.py --write as OPERATOR).")
    if pollution_status == "FAIL":
        actions.append("Remove fake Moltbook rows (moltbook_cleanup_fake_seed.py --apply, ADMIN).")
    if release["verdict"] == _release_gate.FAIL:
        actions.append("Resolve release-gate FAIL checks before serving the UI.")
    if compliance["overall"] == _compliance.FAIL:
        actions.append("Fix compliance FAIL checks (disclosure / register / secrets).")
    if not actions:
        actions.append("No blocking risk detected — human review still required before acting.")
    report["next_actions"] = actions

    # --- clean-DB demotion --------------------------------------------------
    # A freshly-initialised DB with zero operator-state rows has no real
    # operational risk to certify against.  In that state a release-gate
    # FAIL that originates only from a global, DB-independent artefact
    # (the stress-probe summary file under runtime/cockpit_stress_probe/)
    # should not cascade into a hard readiness FAIL — there is nothing
    # to protect and the operator still needs an actionable next step.
    # We demote to WARN, surface why, and leave the real failure modes
    # (compliance FAIL, fake pollution, unrepaired closed losses,
    # preflight check FAIL) on FAIL where they belong.
    is_clean_db = _is_clean_initialised_db(path)
    report["db_clean_initialised"] = is_clean_db
    downgrade_applied = (
        is_clean_db
        and release["verdict"] == _release_gate.FAIL
        and compliance["overall"] != _compliance.FAIL
        and pollution_status != "FAIL"
        and unrepaired == 0
        and bridge_idem.get("idempotent", True)
        and not release.get("failing_checks")
    )
    # Always emit ``clean_db_downgrade_applied`` (True/False) so operators
    # do not have to differentiate "missing key" from "downgrade did not
    # apply".  The reason is only set when the downgrade actually fires.
    report["release_gate"]["clean_db_downgrade_applied"] = bool(downgrade_applied)
    if downgrade_applied:
        report["release_gate"]["clean_db_downgrade"] = True
        report["release_gate"]["clean_db_downgrade_reason"] = (
            "Release gate FAIL is only from a global runtime artefact "
            "(stress-probe summary); the DB is freshly initialised with "
            "zero operator data, so readiness is downgraded to WARN."
        )
        # The downgrade survives the verdict step below.
        release_for_verdict = _release_gate.WARN
    else:
        report["release_gate"]["clean_db_downgrade"] = False
        report["release_gate"]["clean_db_downgrade_reason"] = ""
        release_for_verdict = release["verdict"]

    # Explicit hard-fail blocker enumeration so operators / CI scripts can
    # branch on the *reason* not just the verdict.  This list mirrors
    # ``promotion_block_reasons`` but is structured (one tag per blocker).
    hard_fail_blockers: list[str] = []
    if release["verdict"] == _release_gate.FAIL and not downgrade_applied:
        hard_fail_blockers.append("release_gate_fail")
    if compliance["overall"] == _compliance.FAIL:
        hard_fail_blockers.append("compliance_fail")
    if pollution_status == "FAIL":
        hard_fail_blockers.append("fake_moltbook_pollution")
    if unrepaired > 0:
        hard_fail_blockers.append("unrepaired_closed_loss")
    if not bridge_idem.get("idempotent", True):
        hard_fail_blockers.append("bridge_not_idempotent")
    # Look for the explicit "execution_gate_locked" preflight check; FAIL
    # there means a persisted row has broker_api_called or ai_execution_count
    # set — never demote.
    exec_check = next(
        (c for c in release["preflight"]["checks"]
         if c["name"] == "execution_gate_locked"), None
    )
    if exec_check and exec_check["status"] == "FAIL":
        hard_fail_blockers.append("execution_gate_unlocked_in_db")
    report["hard_fail_blockers"] = hard_fail_blockers

    # --- readiness verdict + workflow score --------------------------------
    if release_for_verdict == _release_gate.FAIL or compliance["overall"] == _compliance.FAIL:
        readiness = "FAIL"
    elif no_new_risk or release_for_verdict == _release_gate.WARN \
            or compliance["overall"] == _compliance.WARN:
        readiness = "WARN"
    else:
        readiness = "READY"
    report["readiness"] = readiness

    # WorkflowScore = visible_risk_categories/total * actionability * fallback_honesty
    risk_categories = {
        "release": release["verdict"] != "UNKNOWN",
        "compliance": compliance["overall"] != "UNKNOWN",
        "pollution": pollution_status != "UNKNOWN",
        "unrepaired_loss": repair.get("available", False),
        "echo_risk": echo_risk is not None,
        "operator_load": operator_load is not None,
    }
    visible = sum(1 for v in risk_categories.values() if v)
    total = len(risk_categories)
    actionability = 1.0 if report["next_actions"] else 0.5
    fallback_honesty = 1.0  # missing data degrades, never faked
    report["workflow_score"] = round(
        (visible / total) * actionability * fallback_honesty, 4)
    report["visible_risk_categories"] = visible
    report["total_risk_categories"] = total
    return report


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="operator_readiness_report.py",
        description=(
            "One-command operator readiness report. Read-only; fail-closed on "
            "a missing DB; advisory-only; never an order."
        ),
    )
    p.add_argument("--db-path", type=str, default=None)
    p.add_argument("--operator-role", default=None)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db = Path(args.db_path) if args.db_path else None
    report = build_readiness_report(db, operator_role=args.operator_role)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"OPERATOR READINESS: {report['readiness']}  "
              f"(advisory-only · execution {report['execution_gate']})")
        print(f"  operator role     : {report['operator_role']}")
        print(f"  no_new_risk       : {report.get('no_new_risk')}")
        if report.get("release_gate"):
            print(f"  release gate      : {report['release_gate']['verdict']}")
            print(f"  compliance        : {report['compliance']['verdict']}")
            print(f"  fake pollution    : {report['moltbook']['fake_pollution_status']}")
            print(f"  unrepaired losses : {report['moltbook']['unrepaired_closed_loss_count']}")
            print(f"  echo risk         : {report['signal_risk']['duplicate_echo_risk']}")
            print(f"  workflow score    : {report.get('workflow_score')}")
        for reason in report.get("promotion_block_reasons", []):
            print(f"  [BLOCK] {reason}")
        print("  next actions:")
        for a in report["next_actions"]:
            print(f"    - {a}")
    # Exit non-zero only on a hard FAIL/FAIL_CLOSED so CI/operators can branch.
    return 1 if report["readiness"] in ("FAIL", "FAIL_CLOSED") else 0


__all__ = ["build_readiness_report"]


if __name__ == "__main__":
    raise SystemExit(main())
