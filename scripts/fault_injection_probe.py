"""Fault-injection / resilience probe (Kanté Sprint 2 — Task 9).

Press resistance: inject each known fault and prove the advisory layer degrades
to a *safe* state, never to an execution instruction.  Formally::

    Resilience = faults_handled_safely / faults_injected
    Safe   = {WAIT, REVIEW, INSUFFICIENT_DATA, FAIL_CLOSED, WARN, PASS, READY,
              FAIL, DENY, OK}
    Unsafe = {BUY, EXECUTE, SILENT_PASS, AUTO_TRADE, place_order, ...}
    Requirement:  P(output ∈ Unsafe | fault) = 0

A fault is *handled safely* when, after injection:
  * no unhandled exception escapes (a fail-closed ``PermissionError`` is
    expected and counts as safe),
  * the observed state is a recognised safe/neutral state,
  * the serialized output contains no execution token and no leaked secret.

All work happens on caller-supplied temp paths / in memory.  Never touches the
operator's runtime DB; never a broker call; never the network.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

try:
    from scripts import persistence as _persistence
except ModuleNotFoundError:  # pragma: no cover
    import persistence as _persistence  # type: ignore[no-redef]

try:
    from scripts import complex_systems_sqlite_bridge as _bridge
    from scripts import reactor_canonical_inputs as _rci
    from scripts import operator_readiness_report as _orr
    from scripts import model_signal_normalizer as _norm
    from scripts import config_contract as _cfg
    from scripts import operator_audit_log as _audit
    from scripts import local_deploy_preflight as _preflight
except ModuleNotFoundError:  # pragma: no cover
    import complex_systems_sqlite_bridge as _bridge  # type: ignore[no-redef]
    import reactor_canonical_inputs as _rci  # type: ignore[no-redef]
    import operator_readiness_report as _orr  # type: ignore[no-redef]
    import model_signal_normalizer as _norm  # type: ignore[no-redef]
    import config_contract as _cfg  # type: ignore[no-redef]
    import operator_audit_log as _audit  # type: ignore[no-redef]
    import local_deploy_preflight as _preflight  # type: ignore[no-redef]

SAFE_STATES = {
    "WAIT", "REVIEW", "INSUFFICIENT_DATA", "FAIL_CLOSED", "WARN", "PASS",
    "READY", "FAIL", "DENY", "OK", "HUMAN_REVIEW_ONLY", "AVOID",
}
# Execution markers that must NEVER appear in any fault output.
_UNSAFE_MARKERS = tuple(set(_contract.FORBIDDEN_EXECUTION_TOKENS) | {
    "auto_trade", "auto-trade", "\"buy\"", "'buy'", "execute_trade",
    "silent_pass",
})

FAULTS = (
    "missing_db", "locked_db", "malformed_model_report", "missing_env",
    "backend_down", "empty_moltbook", "polluted_moltbook",
    "missing_duplicate_fingerprints", "missing_signal_cell_index",
    "invalid_operator_role", "unknown_config_var", "corrupt_json_export",
)


def _blob_has_unsafe(blob: str) -> list[str]:
    low = blob.lower()
    return [m for m in _UNSAFE_MARKERS if m.lower() in low]


def _result(fault: str, *, state: str, handled: bool, note: str,
            unsafe: list[str] | None = None) -> dict[str, Any]:
    return {
        "fault": fault,
        "observed_state": state,
        "handled_safely": bool(handled),
        "unsafe_markers": unsafe or [],
        "note": note,
    }


def _classify(fault: str, state: Any, blob: str, *, note: str) -> dict[str, Any]:
    state_str = str(state or "").upper()
    unsafe = _blob_has_unsafe(blob)
    handled = (state_str in SAFE_STATES) and not unsafe
    return _result(fault, state=state_str or "UNKNOWN", handled=handled,
                   note=note, unsafe=unsafe)


def _empty_db(tmp: Path) -> Path:
    """A real SQLite file with NO MVP tables (simulates missing schema/tables)."""
    p = tmp / "empty.db"
    sqlite3.connect(str(p)).close()
    return p


def _corrupt_db(tmp: Path) -> Path:
    """A non-SQLite file (simulates a locked/corrupt/unreadable DB)."""
    p = tmp / "corrupt.db"
    p.write_bytes(b"this is not a sqlite database \x00\x01\x02")
    return p


def _seeded_db(tmp: Path, *, polluted: bool = False) -> Path:
    p = tmp / "seeded.db"
    _persistence.init_schema(p)
    if polluted:
        _persistence.insert_moltbook_entry(
            "MB_FAKE", "FABRIC_SPY_1", "SPY", "Persistence above 0.8", "ai",
            "reflect", "No trade", "", "outcome", "trade_loss", "lesson",
            "", "", "", "2026-05-21T00:00:00+00:00", db_path=p,
        )
    return p


def run_fault(fault: str, tmp: Path) -> dict[str, Any]:
    """Inject one fault and classify the resulting state.  Never raises."""
    try:
        if fault == "missing_db":
            r = _orr.build_readiness_report(tmp / "nope.db")
            return _classify(fault, r["readiness"], json.dumps(r),
                             note="readiness fails closed on missing DB.")

        if fault == "locked_db":
            db = _corrupt_db(tmp)
            r = _bridge.build_canonical_complex_systems_state(db)
            return _classify(fault, r.get("state"), json.dumps(r),
                             note="unreadable DB degrades to INSUFFICIENT.")

        if fault == "malformed_model_report":
            r = _norm.normalize_model_report({"garbage": object().__class__.__name__})
            return _classify(fault, r["advisory_status"], json.dumps(r),
                             note="malformed model report → INSUFFICIENT/REVIEW.")

        if fault == "missing_env":
            r = _cfg.evaluate(env={})
            return _classify(fault, r["overall"], json.dumps(r),
                             note="empty env → WARN, never an execution flag.")

        if fault == "backend_down":
            import os
            os.environ["MVP_BACKEND_HEALTH_URL"] = "http://127.0.0.1:1/health"
            c = _preflight.check_backend_health(timeout=0.05)
            return _classify(fault, c["status"], json.dumps(c),
                             note="backend probe → WARN, not fatal.")

        if fault == "empty_moltbook":
            db = _seeded_db(tmp)
            r = _orr.build_readiness_report(db)
            return _classify(fault, r["readiness"], json.dumps(r),
                             note="empty Moltbook → no execution instruction.")

        if fault == "polluted_moltbook":
            db = _seeded_db(tmp, polluted=True)
            r = _orr.build_readiness_report(db)
            return _classify(fault, r["readiness"], json.dumps(r),
                             note="fake pollution → FAIL/no_new_risk, fail closed.")

        if fault in ("missing_duplicate_fingerprints", "missing_signal_cell_index"):
            db = _empty_db(tmp)
            r = _rci.build_reactor_canonical_inputs(db)
            return _classify(fault, r["routing_readiness"], json.dumps(r),
                             note="missing canonical table → INSUFFICIENT routing.")

        if fault == "invalid_operator_role":
            try:
                _audit.enforce("run_moltbook_bridge", role="superhacker",
                               resource="x", audit_path=tmp / "audit.jsonl")
                return _result(fault, state="UNSAFE", handled=False,
                               note="invalid role was allowed (regression!)")
            except PermissionError:
                return _result(fault, state="DENY", handled=True,
                               note="invalid role fails closed to denial.")

        if fault == "unknown_config_var":
            r = _cfg.evaluate(env={"SOME_UNKNOWN_HARMLESS_VAR": "1"})
            return _classify(fault, r["overall"], json.dumps(r),
                             note="benign unknown var ignored; no FAIL escalation.")

        if fault == "corrupt_json_export":
            # Feed non-list / non-dict garbage to the model normalizer batch.
            r = _norm.normalize_model_reports("}{ not json")
            return _classify(fault, r["advisory_status"], json.dumps(r),
                             note="corrupt export → INSUFFICIENT, never executes.")
    except Exception as exc:  # pragma: no cover - any escape is a failure
        return _result(fault, state="EXCEPTION", handled=False,
                       note=f"unhandled {type(exc).__name__}: {exc}")
    return _result(fault, state="UNKNOWN", handled=False, note="unknown fault.")


def run_probe(tmp_dir: Path | None = None) -> dict[str, Any]:
    """Inject every fault; compute the resilience score."""
    own = tmp_dir is None
    base = Path(tmp_dir) if tmp_dir else Path(tempfile.mkdtemp(prefix="mvp-fault-"))
    results = [run_fault(f, base) for f in FAULTS]
    handled = sum(1 for r in results if r["handled_safely"])
    any_unsafe = any(r["unsafe_markers"] for r in results)
    return {
        "report": "fault_injection_probe",
        "used_temp_dir": own,
        "faults_injected": len(FAULTS),
        "faults_handled_safely": handled,
        "resilience": round(handled / len(FAULTS), 4) if FAULTS else 0.0,
        "any_unsafe_output": any_unsafe,
        "results": results,
        "safe_states": sorted(SAFE_STATES),
        **_contract.advisory_safety_stamps(),
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fault_injection_probe.py",
        description=(
            "Inject faults; prove safe degradation (no execution under fault). "
            "Temp paths only; never touches the runtime DB; never a broker call."
        ),
    )
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = run_probe()
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"Fault-injection probe: resilience={report['resilience']} "
              f"({report['faults_handled_safely']}/{report['faults_injected']})")
        print(f"  any unsafe output: {report['any_unsafe_output']}")
        for r in report["results"]:
            flag = "OK" if r["handled_safely"] else "FAIL"
            print(f"  [{flag:>4}] {r['fault']:<30} -> {r['observed_state']}")
    # Fail closed: non-zero if anything was not handled safely.
    return 0 if (report["faults_handled_safely"] == report["faults_injected"]
                 and not report["any_unsafe_output"]) else 1


__all__ = ["FAULTS", "SAFE_STATES", "run_fault", "run_probe"]


if __name__ == "__main__":
    raise SystemExit(main())
