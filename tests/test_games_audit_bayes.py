"""Self-auditing probability layer proofs: tempered Bayesian updates,
the Dice Audit Loop, per-game calibration, and pipeline integration.

Doctrine under test: belief moves only as far as the evidence deserves
(zero-trust evidence moves nothing); the model audits its own dice
assumptions against resolved outcomes; thin samples never move
assumptions; severe calibration risk blocks investment-grade actions.
"""

from __future__ import annotations

import copy
import json

import pytest

from src.games.bayesian_update import (
    bayesian_update,
    evidence_trust,
    likelihood_to_ratio,
)
from src.games.dice_audit import (
    audit_d100_buckets,
    audit_dice_profile,
    summarize_game_calibration,
)
from src.simulator.pipeline import evaluate_candidate_payload
from tests.test_simulator_cherry_pick_pipeline import STRONG_PAYLOAD


# --- 6. Bayesian: strong reliable evidence moves posterior up ----------------
def test_strong_reliable_evidence_raises_posterior() -> None:
    result = bayesian_update(
        prior=0.40,
        evidence=[
            {"name": "audited filing", "likelihood_ratio": 4.0,
             "reliability": 0.95, "reality_anchor": 0.9,
             "dice_confidence": 0.95},
        ],
    )
    assert result.posterior > 0.6
    assert result.updates[0].trust > 0.8
    assert "prior 0.400" in result.rationale[0]


# --- 7. Bayesian: low reality anchor / manipulation mutes the update ---------
def test_low_trust_evidence_barely_moves_posterior() -> None:
    loud_but_unearned = bayesian_update(
        prior=0.40,
        evidence=[
            {"name": "viral hype thread", "likelihood_ratio": 8.0,
             "reliability": 0.3, "reality_anchor": 0.1,
             "dice_confidence": 0.5, "manipulation_risk": 0.7},
        ],
    )
    assert loud_but_unearned.posterior < 0.45  # barely moved from 0.40
    assert loud_but_unearned.updates[0].trust < 0.05
    assert any("muted by low trust" in r for r in loud_but_unearned.rationale)


def test_zero_trust_evidence_moves_nothing() -> None:
    result = bayesian_update(
        prior=0.40,
        evidence=[{"name": "pure manipulation", "likelihood_ratio": 20.0,
                   "manipulation_risk": 1.0}],
    )
    assert result.posterior == pytest.approx(0.40, abs=1e-9)
    assert result.updates[0].effective_ratio == pytest.approx(1.0)


def test_opposing_evidence_lowers_posterior_and_lr_is_clamped() -> None:
    down = bayesian_update(
        prior=0.6,
        evidence=[{"name": "refuting filing", "likelihood_ratio": 0.2,
                   "reliability": 0.9, "reality_anchor": 0.9}],
    )
    assert down.posterior < 0.4
    assert likelihood_to_ratio(1.0, 0.0001) <= 20.0
    assert evidence_trust(manipulation_risk=1.0) == 0.0


def test_sequential_updates_compound() -> None:
    result = bayesian_update(
        prior=0.30,
        evidence=[
            {"name": "e1", "likelihood_ratio": 2.0, "reliability": 0.9,
             "reality_anchor": 0.9},
            {"name": "e2", "likelihood_ratio": 2.0, "reliability": 0.9,
             "reality_anchor": 0.9},
        ],
    )
    single = bayesian_update(
        prior=0.30,
        evidence=[{"name": "e1", "likelihood_ratio": 2.0,
                   "reliability": 0.9, "reality_anchor": 0.9}],
    )
    assert result.posterior > single.posterior
    assert result.updates[1].posterior_after == pytest.approx(result.posterior, abs=1e-6)


# --- 1/2/3/4. Dice Audit Loop -------------------------------------------------
def _rows(confidence: float, hit_rate: float, n: int) -> list[dict]:
    hits = round(n * hit_rate)
    return (
        [{"confidence": confidence, "outcome": 1.0}] * hits
        + [{"confidence": confidence, "outcome": 0.0}] * (n - hits)
    )


def test_calibrated_profile_stays_stable() -> None:
    audit = audit_dice_profile(
        _rows(confidence=0.7, hit_rate=0.7, n=40), assumed_profile="precision"
    )
    assert audit.calibration_status == "calibrated"
    assert audit.recommended_adjustment == "keep"
    assert audit.confidence_multiplier == 1.0


def test_overconfident_profile_gets_multiplier_cut() -> None:
    audit = audit_dice_profile(
        _rows(confidence=0.8, hit_rate=0.55, n=40), assumed_profile="precision"
    )
    assert audit.calibration_status == "overconfident"
    assert audit.recommended_adjustment == "downgrade"
    assert audit.confidence_multiplier < 0.6
    assert any("downgrading 'precision'" in n for n in audit.audit_notes)


def test_extreme_gap_is_loaded_suspected() -> None:
    audit = audit_dice_profile(
        _rows(confidence=0.9, hit_rate=0.4, n=40), assumed_profile="d6"
    )
    assert audit.calibration_status == "loaded_suspected"
    assert audit.recommended_adjustment == "cap_confidence"
    assert audit.confidence_multiplier == 0.25
    assert any("who benefits" in n for n in audit.audit_notes)


def test_underconfident_profile_flagged_for_upgrade_review() -> None:
    audit = audit_dice_profile(
        _rows(confidence=0.4, hit_rate=0.65, n=40), assumed_profile="rounded"
    )
    assert audit.calibration_status == "underconfident"
    assert audit.recommended_adjustment == "upgrade"
    assert any("never auto-applied" in n for n in audit.audit_notes)


def test_thin_sample_never_overreacts() -> None:
    audit = audit_dice_profile(
        _rows(confidence=0.9, hit_rate=0.1, n=10), assumed_profile="precision"
    )
    assert audit.calibration_status == "require_more_data"
    assert audit.confidence_multiplier == 1.0
    assert any("thin samples" in n for n in audit.audit_notes)


def test_drift_without_gap_detected_on_tight_profile() -> None:
    # Alternating extreme confidence both ways: gap ~0 but Brier awful.
    rows = (
        [{"confidence": 0.95, "outcome": 0.0}] * 20
        + [{"confidence": 0.05, "outcome": 1.0}] * 20
    )
    audit = audit_dice_profile(rows, assumed_profile="precision")
    assert audit.calibration_status in ("drifted", "loaded_suspected")
    assert audit.confidence_multiplier < 1.0


# --- 5. D100 bucket calibration ------------------------------------------------
def test_d100_bucket_audit_is_deterministic() -> None:
    rows = (
        _rows(confidence=0.1, hit_rate=0.1, n=20)
        + _rows(confidence=0.7, hit_rate=0.5, n=20)
    )
    buckets = audit_d100_buckets(rows)
    assert len(buckets) == 2
    low, high = buckets
    assert low.gap == pytest.approx(0.0, abs=0.05)
    assert high.gap == pytest.approx(0.2, abs=0.05)
    assert audit_d100_buckets(rows) == buckets  # deterministic


# --- Per-game calibration summaries ---------------------------------------------
def _telemetry_row(game: str, predicted: float, outcome: float) -> dict:
    return {
        "predicted_probability": predicted,
        "actual_outcome_placeholder": outcome,
        "calibration_status": "resolved",
        "segments": {"dominant_game": game},
    }


def test_per_game_calibration_summaries() -> None:
    rows = (
        [_telemetry_row("shasn", 0.8, 0.0) for _ in range(12)]
        + [_telemetry_row("pallanguzhi", 0.6, 0.6) for _ in range(12)]
        + [_telemetry_row("ludo", 0.5, 1.0) for _ in range(4)]
    )
    summaries = {s.dominant_game: s for s in summarize_game_calibration(rows)}
    assert summaries["shasn"].recommendation == (
        "treat_game_signals_as_overconfident"
    )
    assert summaries["pallanguzhi"].recommendation == "stable"
    assert summaries["ludo"].recommendation == "require_more_data"
    assert summaries["shasn"].calibration_error > 0.15


def test_dominant_game_is_a_bridge_segment() -> None:
    from src.simulator.calibration_bridge import SEGMENT_KEYS, build_calibration_report

    assert "dominant_game" in SEGMENT_KEYS
    rows = [
        {**_telemetry_row("shasn", 0.8, 0.0), "data_source": "fixture_replay"}
        for _ in range(12)
    ]
    report = build_calibration_report(rows)
    games = {
        s.segment_value for s in report.error_by_segment["dominant_game"]
    }
    assert "shasn" in games


# --- 8/9. Pipeline integration ---------------------------------------------------
def _run(extra: dict | None = None) -> dict:
    payload = copy.deepcopy(STRONG_PAYLOAD)
    if extra:
        payload.update(copy.deepcopy(extra))
    return evaluate_candidate_payload(payload)


def test_pipeline_without_bayes_is_passthrough() -> None:
    out = _run()
    assert out["bayes"] is None
    assert out["decision"]["final_state"] == _run()["decision"]["final_state"]


def test_pipeline_bayes_section_produces_posterior_and_feeds_telemetry() -> None:
    payload = copy.deepcopy(STRONG_PAYLOAD)
    payload.pop("predicted_probability", None)
    payload["bayes"] = {
        "prior": 0.54,  # the prediction-market probability as a PRIOR
        "evidence": [
            {"name": "backlog filing", "likelihood_ratio": 3.0,
             "reliability": 0.9, "reality_anchor": 0.85,
             "dice_confidence": 0.9},
            {"name": "viral thread", "likelihood_ratio": 6.0,
             "reliability": 0.3, "reality_anchor": 0.1,
             "manipulation_risk": 0.6},
        ],
    }
    out = evaluate_candidate_payload(payload)
    bayes = out["bayes"]
    assert 0.54 < bayes["posterior"] < 0.95
    # The viral thread's trust is tiny — its update is nearly neutral.
    viral = bayes["updates"][1]
    assert viral["effective_ratio"] < 1.15
    # Posterior feeds telemetry when no predicted_probability was supplied.
    assert out["telemetry"]["predicted_probability"] == pytest.approx(
        bayes["posterior"], abs=1e-9
    )


def test_caller_predicted_probability_outranks_posterior() -> None:
    payload = copy.deepcopy(STRONG_PAYLOAD)
    payload["bayes"] = {"prior": 0.5, "evidence": []}
    out = evaluate_candidate_payload(payload)
    assert out["telemetry"]["predicted_probability"] == pytest.approx(
        payload["predicted_probability"]
    )


def test_severe_dice_audit_downgrades_investment_action() -> None:
    from src.games.advisory_router import route_advisory_action

    blocked = route_advisory_action(
        final_state="buy_candidate", calibration_risk_severe=True
    )
    assert blocked.action == "Research More"
    assert blocked.downgraded_from == "Paper Trade"
    assert "calibration risk" in blocked.explanation

    # And through the pipeline: a severe audit attached to the games
    # section stamps the decision.
    payload = copy.deepcopy(STRONG_PAYLOAD)
    payload["games"] = {
        "layers": {"company": {"cash_flow_centrality": 0.8,
                               "working_capital_cycles": 0.6,
                               "supply_chain_flow": 0.5}},
        "dice_audits": [
            {"assumed_profile": "precision",
             "calibration_status": "overconfident",
             "confidence_multiplier": 0.4},
        ],
    }
    out = evaluate_candidate_payload(payload)
    assert "DICE_CALIBRATION_RISK" in out["decision"]["reason_codes"]
    # Watch-grade base action is unaffected by the block (only
    # investment-grade actions are gated).
    assert out["advisory_action"]["action"] in (
        "Watch", "Research More",
    )


def test_calibration_report_endpoint_includes_game_summaries(
    tmp_path, monkeypatch
) -> None:
    from scripts import persistence
    from scripts.simulator_api import simulator_calibration_report

    monkeypatch.setattr(persistence, "DB_PATH", tmp_path / "g.db", raising=True)
    report = simulator_calibration_report()
    assert "game_calibration_summaries" in report
    assert report["game_calibration_summaries"] == []
    assert report["advisory_status"] == "ADVISORY_ONLY"


# --- 10. Documentation example matches tested behavior ----------------------------
def test_docs_example_d20_overconfidence_downgrade() -> None:
    """A narrative-heavy d20 source shows repeated overconfidence; the
    audit cuts its multiplier; the router downgrades Buy Candidate."""
    audit = audit_dice_profile(
        _rows(confidence=0.85, hit_rate=0.6, n=40), assumed_profile="d20"
    )
    assert audit.calibration_status == "overconfident"
    assert audit.confidence_multiplier < 0.6

    from src.games.advisory_router import route_advisory_action

    action = route_advisory_action(
        final_state="high_conviction_candidate",
        calibration_risk_severe=True,
    )
    assert action.action == "Research More"
    assert action.downgraded_from == "Buy Candidate"


def test_results_deterministic_and_serializable() -> None:
    payload = copy.deepcopy(STRONG_PAYLOAD)
    payload["bayes"] = {"prior": 0.5, "evidence": [
        {"name": "e", "likelihood_ratio": 2.0, "reliability": 0.8},
    ]}
    first = evaluate_candidate_payload(copy.deepcopy(payload))
    second = evaluate_candidate_payload(copy.deepcopy(payload))
    first["telemetry"].pop("decision_time")
    second["telemetry"].pop("decision_time")
    assert json.dumps(first, sort_keys=True) == json.dumps(
        second, sort_keys=True
    )
