"""Risk convergence proofs: the doubt committee.

Doubts are deduplicated like signals (root causes, not echoes),
adjudicated families are excluded (no double jeopardy), and only
independent doubts that arrive together become a gate — conservative
only.
"""

from __future__ import annotations

import copy
import json

import pytest

from src.simulator.pipeline import evaluate_candidate_payload
from src.simulator.risk_convergence import (
    collect_findings,
    converge_risk,
)
from tests.test_edge_lifecycle import golden_section
from tests.test_simulator_cherry_pick_pipeline import STRONG_PAYLOAD


def echo_payload_with_challenged_override() -> dict:
    """Two independent doubt families on one payload: redundant signal
    evidence + a challenged optimistic override."""
    payload = copy.deepcopy(STRONG_PAYLOAD)
    payload["signals"] = STRONG_PAYLOAD["signals"] + [
        {"signal_type": "backlog", "raw_strength": 60,
         "signal_age_hours": 30, "source_quality": 0.7},
        {"signal_type": "backlog", "raw_strength": 55,
         "signal_age_hours": 40, "source_quality": 0.6},
    ]
    payload["opponent"] = {"adaptation": {
        "signal_strength": 0.99, "crowding": 0.01,
        "narrative_saturation": 0.01, "repricing_observed": 0.0,
    }}
    return payload


# --- Committee rules (unit level) -----------------------------------------------
def test_two_independent_families_cap_buy_candidate() -> None:
    report = converge_risk(
        reason_codes=["SIGNAL_REDUNDANCY_HIGH",
                      "OPPONENT_OVERRIDE_CHALLENGED"],
        final_state="buy_candidate",
    )
    assert report.family_count == 2
    assert report.cap_applied == "active_watch"


def test_three_families_cap_at_watchlist() -> None:
    report = converge_risk(
        reason_codes=["SIGNAL_REDUNDANCY_HIGH",
                      "OPPONENT_OVERRIDE_CHALLENGED",
                      "DICE_CALIBRATION_RISK"],
        final_state="buy_candidate",
    )
    assert report.family_count == 3
    assert report.cap_applied == "watchlist"


def test_one_family_warns_but_never_gates() -> None:
    report = converge_risk(
        reason_codes=["SIGNAL_REDUNDANCY_HIGH"],
        final_state="high_conviction_candidate",
    )
    assert report.family_count == 1
    assert report.cap_applied == ""
    assert any("a question, not a verdict" in r for r in report.rationale)


def test_echoes_within_a_family_count_once() -> None:
    # Two integrity findings are one disease, not two.
    report = converge_risk(
        reason_codes=["OPPONENT_OVERRIDE_CHALLENGED",
                      "LOADED_DICE_SUSPECTED"],
        final_state="buy_candidate",
    )
    assert report.finding_count == 2
    assert report.family_count == 1
    assert report.suppressed_echoes == 1
    assert report.cap_applied == ""
    assert any("root causes, not echoes" in r for r in report.rationale)


def test_adjudicated_family_is_excluded_no_double_jeopardy() -> None:
    # EDGE_EXHAUSTED already capped via the adaptation gate: the
    # crowding-side findings were adjudicated and must not recount.
    report = converge_risk(
        reason_codes=["EDGE_EXHAUSTED", "SIGNAL_REDUNDANCY_HIGH"],
        final_state="watchlist",
        opponent={"weapon_map": {"overused": True}},
    )
    assert report.adjudicated_families == ["adaptation_pressure"]
    assert report.families == ["evidence_quality"]
    assert report.cap_applied == ""


def test_cap_is_conservative_only_never_raises() -> None:
    report = converge_risk(
        reason_codes=["SIGNAL_REDUNDANCY_HIGH",
                      "OPPONENT_OVERRIDE_CHALLENGED",
                      "DICE_CALIBRATION_RISK"],
        final_state="archive",
    )
    assert report.family_count == 3
    assert report.cap_applied == ""  # already below the cap target
    assert any("already at or below" in r for r in report.rationale)


def test_informational_codes_are_not_doubts() -> None:
    report = converge_risk(
        reason_codes=["OPPONENT_SELF_FED", "CONSENT_EVIDENCE_ABSENT",
                      "LIVE_UNDERPRICED_ACCELERATION"],
        final_state="buy_candidate",
    )
    assert report.finding_count == 0
    assert report.cap_applied == ""
    assert any("committee is idle" in r for r in report.rationale)


# --- Layer-report findings ------------------------------------------------------
def test_layer_findings_are_collected_with_sources() -> None:
    findings = collect_findings(
        [],
        opponent={
            "adaptation": {"state": "crowded_edge"},
            "weapon_map": {"overused": True},
        },
        lifecycle={
            "expiry": {"status": "marginal", "days_to_expiry": 6.0},
            "capacity": {"fake_exponential": True},
            "hedge": {"over_hedged": True},
            "arbitrage": {"gap_unsupported": True},
        },
    )
    by_code = {f.code: f for f in findings}
    assert by_code["CROWDED_EDGE_WARN"].family == "adaptation_pressure"
    assert by_code["WEAPON_OVERUSED"].family == "adaptation_pressure"
    assert by_code["EXPIRY_MARGINAL"].family == "timing_decay"
    assert by_code["FAKE_EXPONENTIAL"].family == "structural_fragility"
    assert by_code["OVER_HEDGED"].family == "structural_fragility"
    assert by_code["GAP_UNSUPPORTED"].family == "evidence_quality"
    assert all(f.source and f.detail for f in findings)


# --- Pipeline integration ----------------------------------------------------------
def test_clean_payload_reports_an_idle_committee() -> None:
    out = evaluate_candidate_payload(copy.deepcopy(STRONG_PAYLOAD))
    report = out["risk_convergence"]
    assert report["finding_count"] == 0
    assert report["cap_applied"] == ""
    assert "convergence_gate" not in out["decision"]["gate_results"]
    assert "RISK_CONVERGENCE_CAP" not in out["decision"]["reason_codes"]


def test_two_families_warn_without_capping_at_active_watch() -> None:
    out = evaluate_candidate_payload(echo_payload_with_challenged_override())
    report = out["risk_convergence"]
    assert report["families"] == ["evidence_quality", "integrity_gaming"]
    # The cap target equals the current state: threshold met, nothing
    # to cap — the committee says so instead of stamping noise.
    assert out["decision"]["final_state"] == "active_watch"
    assert report["cap_applied"] == ""
    assert out["decision"]["gate_results"]["convergence_gate"] is True
    assert any("already at or below" in r for r in report["rationale"])


def test_three_families_cap_the_pipeline_verdict() -> None:
    payload = echo_payload_with_challenged_override()
    payload["lifecycle"] = golden_section()  # fragile golden: 3rd family
    out = evaluate_candidate_payload(payload)
    report = out["risk_convergence"]
    assert report["families"] == [
        "evidence_quality", "integrity_gaming", "structural_fragility",
    ]
    assert report["cap_applied"] == "watchlist"
    assert out["decision"]["final_state"] == "watchlist"
    assert "RISK_CONVERGENCE_CAP" in out["decision"]["reason_codes"]
    assert out["decision"]["gate_results"]["convergence_gate"] is False
    # The advisory router sees the post-cap state, never the pre-cap one.
    assert out["advisory_action"]["action"] not in (
        "Buy Candidate", "Hold",
    )


def test_convergence_report_always_in_output_and_serializable() -> None:
    out = evaluate_candidate_payload(copy.deepcopy(STRONG_PAYLOAD))
    assert json.dumps(out["risk_convergence"])
    assert out["risk_convergence"]["advisory_status"] == "ADVISORY_ONLY"


def test_committee_is_deterministic() -> None:
    first = evaluate_candidate_payload(
        echo_payload_with_challenged_override()
    )["risk_convergence"]
    second = evaluate_candidate_payload(
        echo_payload_with_challenged_override()
    )["risk_convergence"]
    assert first == second
