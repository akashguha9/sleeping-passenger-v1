"""Governance verdict — the system-readiness decision, extracted from the
4,996-line ``pipeline_health_report`` god-module.

This is the single most safety-critical pure function in the pipeline: it maps
the SCM review, execution policy, friction, open-position validity, and active
blockers to ``(system_readiness_state, can_deploy_capital)``. Extracting it
isolates that decision behind a tiny, fully-tested seam.

Pure: no I/O, no imports of other repo modules, deterministic. Behaviour is
byte-identical to the prior in-module definition (golden-tested). It cannot
deploy capital — the only ``True`` it returns is the ``READY`` branch, which is
unreachable under the seeded/restricted posture by construction.
"""

from __future__ import annotations

from typing import Any


def determine_system_readiness(
    scm_review: dict[str, Any],
    execution_policy: dict[str, Any],
    friction_report: dict[str, Any],
    open_positions_summary: dict[str, Any],
    active_blockers: list[str],
) -> tuple[str, bool]:
    critical_blockers = {"GSCE_PHASE_LOCK", "REALM_BIS"}
    friction_band = friction_report.get("friction_band", "HIGH_FRICTION")
    scm_rate = float(scm_review.get("scm_rate", 0.0))
    policy_state = str(execution_policy.get("policy_state", "UNKNOWN")).upper()

    if not open_positions_summary.get("valid", False):
        return "NOT_READY", False

    if (
        policy_state in {"RESTRICTED", "BLOCKED", "DO_NOT_DEPLOY", "NOT_READY"}
        and (
            friction_band == "HIGH_FRICTION"
            or scm_rate < 0.30
            or bool(critical_blockers.intersection(active_blockers))
        )
    ):
        return "DO_NOT_DEPLOY", False

    if friction_band == "HIGH_FRICTION" or policy_state in {"RESTRICTED", "BLOCKED"}:
        return "NOT_READY", False

    if (
        not execution_policy.get("allow_new_risk", False)
        or friction_band == "MEDIUM_FRICTION"
        or scm_review.get("scm_state") == "LOW_CONVERSION"
    ):
        return "LIMITED_DEPLOY", False

    return "READY", True
