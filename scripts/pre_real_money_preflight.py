"""
Pre-real-money preflight — one command before you log a real-money trade.

Purpose
-------
Bundle the local-operating-discipline checks (DB integrity, local security,
source refresh, self-test summary, reconciliation queue) into a single
read-only payload.  Run this BEFORE you start a real-money manual trading
day.

Read-only.  No live APIs.  No DB writes.  No broker calls.  No execution
permission.

Safety contract
---------------

    advisory_status        = "ADVISORY_ONLY"
    execution_gate         = "LOCKED"
    broker_api_called      = False
    ai_execution_count     = 0
    execution_permission   = False
    can_execute            = False

Usage
-----
    python scripts/pre_real_money_preflight.py
    python scripts/pre_real_money_preflight.py --json
    python scripts/pre_real_money_preflight.py --db-path runtime/mvp_local.db
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path
from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"

_SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": ADVISORY_STATUS,
    "execution_gate": EXECUTION_GATE_LOCKED,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
}

# Operator-action thresholds. Aligned with the runbook.
UNRECONCILED_WARN_THRESHOLD = 10
UNRECONCILED_BLOCK_THRESHOLD = 25
UNRECONCILED_FULL_REVIEW_THRESHOLD = 50


def _default_db_path() -> Path:
    try:
        try:
            from scripts.persistence import DB_PATH  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            from persistence import DB_PATH  # type: ignore[no-redef]
        return Path(DB_PATH)
    except Exception:
        return Path(__file__).resolve().parents[1] / "runtime" / "mvp_local.db"


def _import_check(modname: str, attr: str):
    """Try importing ``attr`` from ``scripts.<modname>`` then ``<modname>``.
    Returns the callable or None if unavailable.
    """
    try:
        try:
            mod = __import__(f"scripts.{modname}", fromlist=[attr])
        except ImportError:
            mod = __import__(modname, fromlist=[attr])
        return getattr(mod, attr, None)
    except Exception:
        return None


def _safe_call(callable_, *args, **kwargs) -> dict[str, Any] | None:
    """Call ``callable_``; on any exception return None.  The preflight
    must never raise on a subcheck failure — that would block the operator
    from even seeing which subcheck broke."""
    if callable_ is None:
        return None
    try:
        return callable_(*args, **kwargs)
    except Exception as exc:  # pragma: no cover — defensive guard
        return {
            "ok": False,
            "subcheck_error": f"{type(exc).__name__}: {exc}",
        }


def run_preflight(
    db_path: Path | None = None,
    *,
    repo_root: Path | None = None,
    now: _dt.datetime | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run all subchecks and return a single payload."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    path = Path(db_path) if db_path else _default_db_path()
    rroot = (
        Path(repo_root) if repo_root else Path(__file__).resolve().parents[1]
    )

    blocking_issues: list[str] = []
    warnings: list[str] = []

    payload: dict[str, Any] = {
        "report": "pre_real_money_preflight",
        "db_path": str(path),
        "repo_root": str(rroot),
        "ok": False,
        "subchecks": {},
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "operator_action": "",
        "generated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    payload.update(_SAFETY_STAMPS)

    # 1. DB integrity.
    dic_run = _import_check("db_integrity_check", "run_integrity_check")
    dic_result = _safe_call(dic_run, path, now=now)
    if dic_result is None:
        warnings.append("db_integrity_check_unavailable")
    else:
        payload["subchecks"]["db_integrity"] = dic_result
        if dic_result.get("ok") is False:
            blocking_issues.append("db_integrity_failed")

    # 2. Local security.
    lsa_run = _import_check("local_security_audit", "run_security_audit")
    lsa_result = _safe_call(lsa_run, rroot, env=env, now=now)
    if lsa_result is None:
        warnings.append("local_security_audit_unavailable")
    else:
        payload["subchecks"]["local_security"] = lsa_result
        if lsa_result.get("ok") is False:
            blocking_issues.append("local_security_failed")

    # 3. Source refresh.
    sra_run = _import_check("source_refresh_audit", "run_audit")
    sra_result = _safe_call(sra_run, path, now=now, env=env)
    if sra_result is None:
        warnings.append("source_refresh_audit_unavailable")
    else:
        payload["subchecks"]["source_refresh"] = sra_result
        if sra_result.get("ok") is False:
            # Source-refresh failing isn't a hard block, but warn loudly.
            warnings.append("source_refresh_degraded")

    # 4. Self-test summary (compact).
    str_run = _import_check("self_test_report", "build_self_test_summary")
    str_result = _safe_call(str_run, path)
    if str_result is None:
        warnings.append("self_test_summary_unavailable")
    else:
        payload["subchecks"]["self_test_summary"] = str_result

    # 5. Reconciliation queue.
    rq_run = _import_check("reconciliation_queue", "build_queue")
    rq_result = _safe_call(rq_run, path, limit=50, now=now)
    if rq_result is None:
        warnings.append("reconciliation_queue_unavailable")
    else:
        payload["subchecks"]["reconciliation_queue"] = rq_result
        summary = rq_result.get("summary", {}) or {}
        unreconciled = int(summary.get("unreconciled_count") or 0)
        payload["unreconciled_count"] = unreconciled
        if unreconciled >= UNRECONCILED_FULL_REVIEW_THRESHOLD:
            blocking_issues.append("unreconciled_backlog_full_review")
        elif unreconciled >= UNRECONCILED_BLOCK_THRESHOLD:
            blocking_issues.append("unreconciled_backlog_block")
        elif unreconciled >= UNRECONCILED_WARN_THRESHOLD:
            warnings.append("unreconciled_backlog_warn")

    # 6. Signal reactor — diagnostic self-check.
    #
    # Reactor is wired as a *diagnostic* sixth subcheck.  A healthy reactor
    # returning COLD_OBSERVE on a synthetic empty cluster is normal — it
    # contributes no warning.  Two failure modes do matter:
    #   - reactor module unimportable  -> WARNING (advisory layer degraded)
    #   - reactor returns broken safety invariants  -> BLOCKING (the
    #     advisory layer's safety contract is breached, which is exactly
    #     the kind of regression preflight must catch)
    # Existing unreconciled-backlog blocking remains primary and is never
    # weakened by reactor enthusiasm; the reactor cannot unlock execution
    # — it can only fail the safety contract.
    sr_run = _import_check("signal_reactor", "evaluate_signal_reactor")
    if sr_run is None:
        warnings.append("signal_reactor_unavailable")
    else:
        sr_result = _safe_call(sr_run, [])
        if not isinstance(sr_result, dict):
            warnings.append("signal_reactor_unavailable")
        else:
            sr_safety = sr_result.get("safety") or {}
            invariants_ok = (
                sr_result.get("advisory_status") == "ADVISORY_ONLY"
                and sr_result.get("execution_gate") == "LOCKED"
                and sr_safety.get("broker_api_called") is False
                and sr_safety.get("ai_execution_count") == 0
                and sr_safety.get("execution_permission") is False
                and sr_safety.get("can_execute") is False
            )
            payload["subchecks"]["signal_reactor"] = {
                "ok": bool(invariants_ok),
                "reactor_state": str(
                    sr_result.get("signal_reactor_state") or "INSUFFICIENT_DATA"
                ),
                "recommendation": str(sr_result.get("recommendation") or "observe"),
                "safety_invariants_ok": bool(invariants_ok),
                "advisory_status": sr_result.get("advisory_status"),
                "execution_gate": sr_result.get("execution_gate"),
            }
            if not invariants_ok:
                blocking_issues.append("signal_reactor_safety_invariant_failed")

    # 7. Geometry reflection layer — diagnostic seventh subcheck.
    # Same contract as signal_reactor: a healthy module returns an
    # advisory payload with safety stamps intact; a broken safety
    # contract is a blocking regression. The geometry layer itself can
    # never unlock execution.
    geo_run = _import_check(
        "signal_geometry_reflection", "build_signal_geometry_diagnostics"
    )
    if geo_run is None:
        warnings.append("signal_geometry_reflection_unavailable")
    else:
        geo_result = _safe_call(geo_run, [])
        if not isinstance(geo_result, dict):
            warnings.append("signal_geometry_reflection_unavailable")
        else:
            geo_safety = geo_result.get("safety") or {}
            geo_invariants_ok = (
                geo_result.get("advisory_status") == "ADVISORY_ONLY"
                and geo_result.get("execution_gate") == "LOCKED"
                and geo_safety.get("broker_api_called") is False
                and geo_safety.get("ai_execution_count") == 0
                and geo_safety.get("execution_permission") is False
                and geo_safety.get("can_execute") is False
                and geo_safety.get("broker_order_id") == "NONE"
                and geo_safety.get("human_review_required") is True
            )
            payload["subchecks"]["signal_geometry_reflection"] = {
                "ok": bool(geo_invariants_ok),
                "recommendation": str(
                    geo_result.get("recommendation") or "observe"
                ),
                "safety_invariants_ok": bool(geo_invariants_ok),
                "advisory_status": geo_result.get("advisory_status"),
                "execution_gate": geo_result.get("execution_gate"),
                "canonical_truth_source": geo_result.get(
                    "canonical_truth_source"
                ),
                "jsonl_role": geo_result.get("jsonl_role"),
            }
            if not geo_invariants_ok:
                blocking_issues.append(
                    "signal_geometry_reflection_safety_invariant_failed"
                )

    # 8. Complex-systems doctrine layer — diagnostic eighth subcheck.
    # Same contract as the geometry layer: a healthy module returns an
    # advisory payload with safety stamps intact; a broken safety contract
    # is a blocking regression. This layer can never unlock execution.
    cs_run = _import_check(
        "complex_systems_diagnostics", "build_complex_systems_diagnostics"
    )
    if cs_run is None:
        warnings.append("complex_systems_diagnostics_unavailable")
    else:
        cs_result = _safe_call(cs_run, [])
        if not isinstance(cs_result, dict):
            warnings.append("complex_systems_diagnostics_unavailable")
        else:
            cs_safety = cs_result.get("safety") or {}
            cs_invariants_ok = (
                cs_result.get("advisory_status") == "ADVISORY_ONLY"
                and cs_result.get("execution_gate") == "LOCKED"
                and cs_safety.get("broker_api_called") is False
                and cs_safety.get("ai_execution_count") == 0
                and cs_safety.get("execution_permission") is False
                and cs_safety.get("can_execute") is False
                and cs_safety.get("broker_order_id") == "NONE"
                and cs_safety.get("human_review_required") is True
            )
            payload["subchecks"]["complex_systems_diagnostics"] = {
                "ok": bool(cs_invariants_ok),
                "advisory_decision_bias": str(
                    cs_result.get("advisory_decision_bias") or "insufficient_data"
                ),
                "safety_invariants_ok": bool(cs_invariants_ok),
                "advisory_status": cs_result.get("advisory_status"),
                "execution_gate": cs_result.get("execution_gate"),
                "doctrine": cs_result.get("doctrine"),
                "canonical_truth_source": cs_result.get("canonical_truth_source"),
                "jsonl_role": cs_result.get("jsonl_role"),
            }
            if not cs_invariants_ok:
                blocking_issues.append(
                    "complex_systems_diagnostics_safety_invariant_failed"
                )

    payload["ok"] = len(blocking_issues) == 0

    if not payload["ok"]:
        payload["operator_action"] = (
            "BLOCKING ISSUES present (see blocking_issues list). DO NOT "
            "log real-money manual trades today. Fix the underlying "
            "issues and re-run scripts/pre_real_money_preflight.py."
        )
    elif warnings:
        payload["operator_action"] = (
            "Preflight passing with warnings (see warnings list). It is "
            "safe to proceed with discipline, but address each warning "
            "before week's end."
        )
    else:
        payload["operator_action"] = (
            "Preflight clean. Proceed with the daily checklist in "
            "docs/LOCAL_SELF_TEST_RUNBOOK.md."
        )

    return payload


# ---------------------------------------------------------------------------
# Real-money readiness assessment v2 (additive — run_preflight untouched)
# ---------------------------------------------------------------------------

# Allowed operating modes.
MODE_SCALE_BLOCKED = "SCALE_BLOCKED"
MODE_PAPER_ONLY = "PAPER_ONLY"
MODE_TINY_PROBE = "TINY_MANUAL_PROBE_ONLY"
MODE_MANUAL_SMALL = "MANUAL_REAL_MONEY_READY_SMALL_ONLY"
MODE_MANUAL_CALIBRATED = "MANUAL_REAL_MONEY_READY_CALIBRATED"
# Back-compat alias (older callers/tests referenced MODE_MANUAL_READY).
MODE_MANUAL_READY = MODE_MANUAL_SMALL

# This MVP can reach manual real-money readiness but never scaling.
READINESS_MAX = 8.0


def _execution_surface_present() -> bool:
    """True if the advisory contract's no-execution invariants are broken."""
    try:
        try:
            from scripts import advisory_contract as ac
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            import advisory_contract as ac  # type: ignore[no-redef]
        stamps = ac.advisory_safety_stamps()
        if stamps.get("can_execute", False) or stamps.get("broker_api_called", False):
            return True
        if stamps.get("ai_execution_count", 0) not in (0, None):
            return True
        if getattr(ac, "jsonl_is_canonical", False):
            return True
        return False
    except Exception:
        return True


def _advisory_invariants_ok() -> bool:
    return not _execution_surface_present()


def _persistence_score() -> float:
    """1.0 when SQLite is canonical and JSONL is audit-only."""
    try:
        try:
            from scripts import advisory_contract as ac
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            import advisory_contract as ac  # type: ignore[no-redef]
        sqlite_canon = getattr(ac, "sqlite_is_canonical", None)
        jsonl_canon = getattr(ac, "jsonl_is_canonical", None)
        if sqlite_canon is True and jsonl_canon is False:
            return 1.0
        return 0.5
    except Exception:
        return 0.0


def _leverage_governance_active() -> bool:
    try:
        try:
            from scripts.leverage_governance import validate_leverage_policy
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            from leverage_governance import validate_leverage_policy  # type: ignore[no-redef]
        row = validate_leverage_policy(ticker="X", leverage=2.0, exchange="NASDAQ")
        return bool(row.get("breach")) and "jurisdiction_resolution_source" in row
    except Exception:
        return False


def _feedback_loop_available() -> bool:
    try:
        try:
            from scripts.calibration_recommendations import build_recommendation_from_metrics  # noqa: F401
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            from calibration_recommendations import build_recommendation_from_metrics  # noqa: F401
        return True
    except Exception:
        return False


def _backup_score() -> float:
    try:
        try:
            from scripts import backup_local_state  # noqa: F401
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            import backup_local_state  # noqa: F401
        return 1.0
    except Exception:
        return 0.5


def _securities_coverage_score(db_path: Path | None) -> float:
    try:
        try:
            from scripts.securities_master_coverage import build_coverage_report
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            from securities_master_coverage import build_coverage_report  # type: ignore[no-redef]
        rep = build_coverage_report(db_path)
        return float(rep.get("score", 0.0))
    except Exception:
        return 0.0


def _calibration_probe(db_path: Path | None) -> dict:
    """Full calibration metrics from REAL extracted outcomes (provenance-aware)."""
    try:
        try:
            from scripts.score_calibration import build_calibration_metrics_report
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            from score_calibration import build_calibration_metrics_report  # type: ignore[no-redef]
        return build_calibration_metrics_report(db_path)
    except Exception:
        return {"calibration_status": "NO_DATA", "real_n": 0, "paper_n": 0, "n": 0}


def _calibration_score(status: str) -> float:
    return {
        "NO_DATA": 0.0, "FIXTURE_ONLY": 0.0, "LOW_SAMPLE": 0.2,
        "CALIBRATING": 0.5, "CALIBRATED": 0.8, "MIS_CALIBRATED": 0.4,
    }.get(status, 0.0)


def _test_confidence_probe(
    db_path: Path | None = None, *, now: _dt.datetime | None = None
) -> dict[str, Any]:
    """Read a RECORDED test result instead of assuming the suite passes.

    Honesty principle: *unknown is not pass*. The previous gate defaulted
    ``T=1.0`` whenever no test result was handed in — so a never-run suite
    scored identically to a green one. This probe reads
    ``runtime/test_status.json`` (written by ``bootstrap_runtime.py`` / CI):

        {"passing": true, "passed": 812, "failed": 0, "generated_at": "..."}

    Returns ``{"score", "failing", "unverified"}``:
      * fresh + green   -> 1.0, failing=False, unverified=False
      * fresh + red     -> 0.0, failing=True
      * missing / stale -> 0.7, unverified=True (degraded, never silently 1.0)
    """
    now = now or _dt.datetime.now(_dt.timezone.utc)
    try:
        rroot = Path(__file__).resolve().parents[1]
        # Lives under runtime/status/ (a subdir) so it is NOT a top-level
        # runtime/*.json artifact-coherence scans as a pipeline artifact.
        path = rroot / "runtime" / "status" / "test_status.json"
        if not path.exists():
            return {"score": 0.7, "failing": False, "unverified": True}
        data = json.loads(path.read_text(encoding="utf-8"))
        ts = data.get("generated_at")
        if ts:
            try:
                gen = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                if gen.tzinfo is None:
                    gen = gen.replace(tzinfo=_dt.timezone.utc)
                if (now - gen) > _dt.timedelta(days=7):
                    return {"score": 0.7, "failing": False, "unverified": True}
            except Exception:
                pass
        failed = int(data.get("failed", 0) or 0)
        passed = int(data.get("passed", 0) or 0)
        if failed > 0 or data.get("passing") is False:
            return {"score": 0.0, "failing": True, "unverified": False}
        if passed > 0 or data.get("passing") is True:
            return {"score": 1.0, "failing": False, "unverified": False}
        return {"score": 0.7, "failing": False, "unverified": True}
    except Exception:
        return {"score": 0.7, "failing": False, "unverified": True}


def assess_real_money_readiness(
    db_path: Path | None = None,
    *,
    backend_tests_passing: bool | None = None,
    frontend_tests_passing: bool | None = None,
    preflight: dict[str, Any] | None = None,
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    """Dimensional manual real-money readiness gate (v2). Read-only; never
    authorises execution. Hard-capped at READINESS_MAX (8.0) — never scaling."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    blockers: list[str] = []
    warnings: list[str] = []

    exec_surface = _execution_surface_present()
    A = 0.0 if exec_surface else 1.0
    E = 0.0 if exec_surface else 1.0
    P = _persistence_score()
    leverage_active = _leverage_governance_active()
    L = 1.0 if leverage_active else 0.0
    J = _securities_coverage_score(db_path)
    cal = _calibration_probe(db_path)
    cal_status = str(cal.get("calibration_status", "NO_DATA"))
    real_n = int(cal.get("real_n", 0) or 0)
    paper_n = int(cal.get("paper_n", 0) or 0)
    C = _calibration_score(cal_status)
    feedback = _feedback_loop_available()
    F = 1.0 if feedback else 0.0
    # Test confidence: honour explicit caller-supplied results; otherwise probe
    # a recorded status (unknown != pass).
    if backend_tests_passing is None and frontend_tests_passing is None:
        _tc = _test_confidence_probe(db_path, now=now)
        T = _tc["score"]
        tests_failing = _tc["failing"]
        if _tc["unverified"]:
            warnings.append("test_confidence_unverified")
    else:
        tests_failing = (backend_tests_passing is False) or (frontend_tests_passing is False)
        T = 0.0 if tests_failing else 1.0
    B = _backup_score()
    U = 1.0

    checks = {
        "advisory_invariant": A, "no_execution_surface": E, "persistence": P,
        "leverage_governance": L, "jurisdiction_coverage": J, "calibration": C,
        "feedback_loop": F, "test_confidence": T, "backup": B, "ui_clarity": U,
        "calibration_status": cal_status, "real_n": real_n, "paper_n": paper_n,
        "securities_coverage_score": J,
        "backend_tests_passing": backend_tests_passing,
        "frontend_tests_passing": frontend_tests_passing,
    }

    R_raw = 10.0 * (
        0.15 * A + 0.15 * E + 0.10 * P + 0.10 * L + 0.10 * J
        + 0.15 * C + 0.10 * F + 0.10 * T + 0.03 * B + 0.02 * U
    )

    # --- HARD FAIL: any execution surface ---
    if exec_surface:
        blockers.append("execution_surface_present")
        payload = {
            "report": "real_money_readiness", "readiness_score": 0.0,
            "readiness_max": READINESS_MAX, "allowed_mode": MODE_SCALE_BLOCKED,
            "blockers": blockers, "warnings": warnings, "checks": checks,
            "dimensions": {k: checks[k] for k in (
                "advisory_invariant", "no_execution_surface", "persistence",
                "leverage_governance", "jurisdiction_coverage", "calibration",
                "feedback_loop", "test_confidence", "backup", "ui_clarity")},
            "calibration_status": cal_status, "real_n": real_n, "paper_n": paper_n,
            "reason": ("HARD FAIL: execution surface detected (advisory invariants "
                       "broken). Real-money use forbidden."),
            "generated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        payload.update(_SAFETY_STAMPS)
        return payload

    caps: list[float] = [READINESS_MAX]

    if L < 0.8:
        blockers.append("leverage_governance_missing")
        caps.append(5.0)
    if C == 0.0:
        warnings.append("scores_uncalibrated")
        caps.append(6.5)
    if cal_status in {"NO_DATA", "FIXTURE_ONLY", "LOW_SAMPLE"}:
        caps.append(6.5)
    if cal_status == "CALIBRATING":
        caps.append(7.0)
    if cal_status == "CALIBRATED" and real_n < 50:
        # paper-calibrated (real_n<50) -> small-only ceiling
        caps.append(7.0)
        if real_n < 20:
            caps.append(7.0)
    if cal_status == "CALIBRATED" and real_n >= 50:
        caps.append(8.0)
    if cal_status == "MIS_CALIBRATED":
        warnings.append("miscalibrated_review_required")
        caps.append(6.5)
    if tests_failing:
        blockers.append("tests_failing")
        caps.append(6.0)
    if not (preflight if preflight is not None else run_preflight(db_path, now=now)).get("ok", False):
        blockers.append("preflight_blocking_issues")
        caps.append(6.0)
    if J < 0.80:
        warnings.append("securities_coverage_weak")
        caps.append(7.0)
    if not feedback:
        warnings.append("feedback_loop_unavailable")

    R = round(min(R_raw, *caps), 2)

    # --- Allowed mode from R ---
    if R < 6.0:
        allowed = MODE_PAPER_ONLY
    elif R < 7.0:
        allowed = MODE_TINY_PROBE
    elif R < 8.0:
        allowed = MODE_MANUAL_SMALL
    else:
        allowed = MODE_MANUAL_CALIBRATED

    if allowed == MODE_PAPER_ONLY:
        reason = "Paper trading only — blockers present. Human execution required."
    elif allowed == MODE_TINY_PROBE:
        reason = ("Safety holds but scores are not calibrated enough to size from. "
                  "Tiny manual probes only; human execution required.")
    elif allowed == MODE_MANUAL_SMALL:
        reason = ("Manual real-money permitted at SMALL size only (calibration not "
                  "yet real-grade). Position sizing human-controlled; human execution "
                  "required. Not scaling-ready.")
    else:
        reason = ("Real-calibrated on >=50 real outcomes. Manual real-money permitted "
                  "with discipline. Human execution required. Not scaling-ready.")

    payload = {
        "report": "real_money_readiness",
        "readiness_score": R,
        "readiness_raw": round(R_raw, 2),
        "readiness_max": READINESS_MAX,
        "allowed_mode": allowed,
        "blockers": blockers,
        "warnings": warnings,
        "checks": checks,
        "dimensions": {
            "A": A, "E": E, "P": P, "L": L, "J": J,
            "C": C, "F": F, "T": T, "B": B, "U": U,
        },
        "calibration_status": cal_status,
        "real_n": real_n,
        "paper_n": paper_n,
        "reason": reason,
        "generated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    payload.update(_SAFETY_STAMPS)
    return payload


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _render_text(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Pre-Real-Money Preflight")
    lines.append(f"DB: {payload['db_path']}")
    lines.append(f"Repo: {payload['repo_root']}")
    for name, sub in (payload.get("subchecks") or {}).items():
        ok = sub.get("ok") if isinstance(sub, dict) else None
        tag = "PASS" if ok else "FAIL" if ok is False else "INFO"
        lines.append(f"  [{tag}] {name}")
    if payload.get("warnings"):
        lines.append("Warnings: " + ", ".join(payload["warnings"]))
    if payload.get("blocking_issues"):
        lines.append("Blocking issues: " + ", ".join(payload["blocking_issues"]))
    lines.append(f"RESULT: {'PASS' if payload['ok'] else 'FAIL'}")
    lines.append("")
    lines.append("Operator action:")
    lines.append(f"  {payload['operator_action']}")
    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pre_real_money_preflight.py",
        description=(
            "Pre-real-money preflight bundler. Read-only; aggregates the "
            "discipline checks into one decision."
        ),
    )
    p.add_argument("--db-path", type=str, default=None,
                   help="Path to runtime/mvp_local.db (default: persistence).")
    p.add_argument("--repo-root", type=str, default=None,
                   help="Repo root for the security audit (default: parent of scripts/).")
    p.add_argument("--json", action="store_true", help="Emit JSON.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db_path = Path(args.db_path) if args.db_path else _default_db_path()
    repo_root = Path(args.repo_root) if args.repo_root else None
    payload = run_preflight(db_path, repo_root=repo_root)
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2, default=str))
    else:
        print(_render_text(payload))
    return 0 if payload["ok"] else 1


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "UNRECONCILED_WARN_THRESHOLD",
    "UNRECONCILED_BLOCK_THRESHOLD",
    "UNRECONCILED_FULL_REVIEW_THRESHOLD",
    "run_preflight",
]


if __name__ == "__main__":
    raise SystemExit(main())
