"""Operator readiness checklist — the human checks before paper calibration.

KANTE_OPERATOR_READINESS_CHECKLIST
==================================

Kanté Ceiling Push II, Workstream C.  A closed paper trade is only
calibration-worthy once a human has recorded the thesis, the invalidation,
the benchmark, the prices, the exit reason, the signal link, the evidence
snapshot, the verified outcome math, a Moltbook record, and confirmed the
DIABLO/veto state.  This module makes that discipline a visible, scored
checklist instead of an implicit hope.

Hard safety contract
--------------------
* Pure — no I/O.  Importing has no side effects.
* The checklist NEVER grants execution permission.  ``real-money sizing
  prohibited`` is itself one of the required checks, and the output carries
  ``real_money_sizing_impact = PROHIBITED`` unconditionally.
* A perfect checklist yields ``READY_FOR_PAPER_CALIBRATION`` — which is a
  *paper-calibration* readiness verdict only, never execution readiness.

Maths
-----
    checklist_completion_rate = passed_checks / total_checks

    BLOCKED                    if rate < 0.60
    REVIEW_REQUIRED            if 0.60 <= rate < 0.90
    READY_FOR_PAPER_CALIBRATION if rate >= 0.90
"""
from __future__ import annotations

import argparse
import json
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

LABEL_BLOCKED = "BLOCKED"
LABEL_REVIEW_REQUIRED = "REVIEW_REQUIRED"
LABEL_READY = "READY_FOR_PAPER_CALIBRATION"

REAL_MONEY_SIZING_IMPACT = "PROHIBITED"
_PROOF = "OPERATOR_READINESS_CHECKLIST_PAPER_ONLY"

# The ordered checklist.  ``real_money_sizing_prohibited`` is a *confirmation*
# check, not a toggle — it must be explicitly acknowledged True, but the output
# stamp is PROHIBITED regardless of what the operator passes in.
CHECKLIST_KEYS: tuple[str, ...] = (
    "thesis_recorded",
    "invalidation_recorded",
    "benchmark_recorded",
    "entry_price_recorded",
    "exit_price_recorded",
    "exit_reason_recorded",
    "signal_id_linked",
    "external_evidence_snapshot_linked",
    "outcome_math_verified",
    "moltbook_record_available",
    "diablo_veto_state_checked",
    "real_money_sizing_prohibited",
)

# Non-negotiable checks.  Even a high completion rate cannot reach
# READY_FOR_PAPER_CALIBRATION while any of these is missing — a closed paper
# trade with no recorded invalidation, no verified outcome math, or no
# real-money-prohibited confirmation is never calibration-worthy.
CRITICAL_CHECKS: tuple[str, ...] = (
    "invalidation_recorded",
    "outcome_math_verified",
    "real_money_sizing_prohibited",
)


def _readiness_label(rate: float, critical_ok: bool) -> str:
    if rate < 0.60:
        return LABEL_BLOCKED
    if rate < 0.90 or not critical_ok:
        return LABEL_REVIEW_REQUIRED
    return LABEL_READY


def build_operator_checklist(checks: dict[str, Any] | None = None) -> dict[str, Any]:
    """Score the operator readiness checklist (pure).  Never raises.

    Unknown keys are ignored; missing keys count as not-passed.  Truthiness is
    strict: only ``True`` (or a truthy non-empty value) counts as passed.
    """
    checks = dict(checks or {})
    results: dict[str, bool] = {}
    for key in CHECKLIST_KEYS:
        results[key] = bool(checks.get(key))

    total_checks = len(CHECKLIST_KEYS)
    passed_checks = sum(1 for v in results.values() if v)
    missing_checks = [k for k, v in results.items() if not v]

    checklist_completion_rate = passed_checks / float(total_checks)
    critical_ok = all(results.get(k) for k in CRITICAL_CHECKS)
    missing_critical = [k for k in CRITICAL_CHECKS if not results.get(k)]
    label = _readiness_label(checklist_completion_rate, critical_ok)

    out: dict[str, Any] = {
        "report": "operator_readiness_checklist",
        "checks": results,
        "total_checks": total_checks,
        "passed_checks": passed_checks,
        "missing_checks": missing_checks,
        "missing_critical_checks": missing_critical,
        "checklist_completion_rate": round(checklist_completion_rate, 6),
        "readiness_label": label,
        # The checklist can NEVER grant execution — these are constant.
        "execution_permission_granted": False,
        "operator_execution_required": True,
        "real_money_sizing_impact": REAL_MONEY_SIZING_IMPACT,
        "real_money_weight_allowed": False,
        "proof_status": _PROOF,
    }
    out.update(_contract.advisory_safety_stamps())
    out["advisory_only"] = True
    out["human_execution_required"] = True
    out["execution_permission_granted"] = False
    out["real_money_sizing_impact"] = REAL_MONEY_SIZING_IMPACT
    out["real_money_weight_allowed"] = False
    out["proof_status"] = _PROOF
    return out


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="operator_readiness_checklist.py",
        description=(
            "Score the human operator checklist required before a paper trade "
            "is marked calibration-worthy. Pure; advisory-only; grants no "
            "execution; real-money sizing PROHIBITED."
        ),
    )
    p.add_argument(
        "--checks-json",
        default=None,
        help="JSON object of {check_key: bool}; default = empty (all blocked)",
    )
    p.add_argument("--json", action="store_true", help="print the JSON report")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    checks: dict[str, Any] = {}
    if args.checks_json:
        try:
            checks = json.loads(args.checks_json)
        except json.JSONDecodeError:
            print("[ERROR] --checks-json is not valid JSON")
            return 1
    report = build_operator_checklist(checks)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("operator_readiness_checklist")
        print(f"  readiness_label : {report['readiness_label']}")
        print(
            f"  completion      : {report['passed_checks']}/{report['total_checks']} "
            f"({report['checklist_completion_rate']})"
        )
        if report["missing_checks"]:
            print(f"  missing         : {', '.join(report['missing_checks'])}")
        print(f"  execution perm  : {report['execution_permission_granted']}")
        print(f"  real-money      : {report['real_money_sizing_impact']}")
    return 0


__all__ = [
    "LABEL_BLOCKED",
    "LABEL_REVIEW_REQUIRED",
    "LABEL_READY",
    "CHECKLIST_KEYS",
    "CRITICAL_CHECKS",
    "build_operator_checklist",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
