"""Golden tests for the extracted governance verdict (god-module seam).

Pins every branch of determine_system_readiness so the extraction from
pipeline_health_report is provably byte-identical, and asserts the extracted
module and the re-export point to the SAME object (no divergence).
"""

from scripts import governance_verdict
from scripts.governance_verdict import determine_system_readiness
from scripts import pipeline_health_report


def test_reexport_is_same_object() -> None:
    # pipeline_health_report.determine_system_readiness must be the extracted one.
    assert pipeline_health_report.determine_system_readiness is determine_system_readiness


def _call(**over):
    scm = over.get("scm", {"scm_rate": 0.5, "scm_state": "HIGH_CONVERSION"})
    policy = over.get("policy", {"policy_state": "OPEN", "allow_new_risk": True})
    friction = over.get("friction", {"friction_band": "LOW_FRICTION"})
    positions = over.get("positions", {"valid": True})
    blockers = over.get("blockers", [])
    return determine_system_readiness(scm, policy, friction, positions, blockers)


def test_invalid_positions_not_ready() -> None:
    assert _call(positions={"valid": False}) == ("NOT_READY", False)


def test_seeded_restricted_high_friction_is_do_not_deploy() -> None:
    # The live seeded posture: RESTRICTED + HIGH_FRICTION -> DO_NOT_DEPLOY/false.
    assert _call(
        policy={"policy_state": "RESTRICTED", "allow_new_risk": False},
        friction={"friction_band": "HIGH_FRICTION"},
        scm={"scm_rate": 0.42, "scm_state": "LOW_CONVERSION"},
    ) == ("DO_NOT_DEPLOY", False)


def test_restricted_with_critical_blocker_is_do_not_deploy() -> None:
    assert _call(
        policy={"policy_state": "RESTRICTED", "allow_new_risk": False},
        friction={"friction_band": "LOW_FRICTION"},
        scm={"scm_rate": 0.9, "scm_state": "HIGH_CONVERSION"},
        blockers=["GSCE_PHASE_LOCK"],
    ) == ("DO_NOT_DEPLOY", False)


def test_high_friction_alone_is_not_ready() -> None:
    assert _call(
        policy={"policy_state": "OPEN", "allow_new_risk": True},
        friction={"friction_band": "HIGH_FRICTION"},
    ) == ("NOT_READY", False)


def test_blocked_policy_is_not_ready() -> None:
    assert _call(policy={"policy_state": "BLOCKED", "allow_new_risk": True}) == ("NOT_READY", False)


def test_limited_deploy_branch() -> None:
    assert _call(
        policy={"policy_state": "OPEN", "allow_new_risk": False},
        friction={"friction_band": "LOW_FRICTION"},
    ) == ("LIMITED_DEPLOY", False)
    assert _call(friction={"friction_band": "MEDIUM_FRICTION"}) == ("LIMITED_DEPLOY", False)
    assert _call(scm={"scm_rate": 0.9, "scm_state": "LOW_CONVERSION"}) == ("LIMITED_DEPLOY", False)


def test_ready_branch_is_the_only_true() -> None:
    assert _call() == ("READY", True)


def test_defaults_fail_closed() -> None:
    # Empty inputs -> invalid positions -> NOT_READY (never deploys).
    assert determine_system_readiness({}, {}, {}, {}, []) == ("NOT_READY", False)
