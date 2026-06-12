"""Lifecycle attribution + calibration ledger proofs.

The verdict must name its own causes (kill switches, verdict-critical
penalties, cosmetic inputs), measure its own fragility, and leave a
falsifiable prediction record that resolution data can score later.
"""

from __future__ import annotations

import copy
import json

import pytest

from src.simulator.pipeline import evaluate_candidate_payload
from src.strategy.lifecycle_attribution import (
    LEDGER_MIN_RECORDS,
    attribute_lifecycle_verdict,
    entry_from_lifecycle,
    resolve_entry,
    summarize_ledger,
)
from tests.test_edge_lifecycle import golden_section
from tests.test_simulator_cherry_pick_pipeline import STRONG_PAYLOAD


def saturating_section() -> dict:
    section = golden_section()
    section["capacity"] = {
        "current_scale": 0.8, "market_penetration": 0.9,
        "tam_evidence": 0.5,
    }
    section["arbitrage"]["priced_belief"] = 0.75
    return section


def decayed_section() -> dict:
    section = golden_section()
    section["live_edge"] = 0.15  # below threshold 0.2
    return section


@pytest.fixture(scope="module")
def golden_attribution():
    return attribute_lifecycle_verdict(golden_section())


@pytest.fixture(scope="module")
def saturating_attribution():
    return attribute_lifecycle_verdict(saturating_section())


@pytest.fixture(scope="module")
def decayed_attribution():
    return attribute_lifecycle_verdict(decayed_section())


def _perturbation(report, name):
    return next(p for p in report.perturbations if p.name == name)


# --- Verdict-critical and kill-switch attribution -------------------------------
def test_decay_ablation_flips_an_expired_verdict(decayed_attribution) -> None:
    # Restoring the live edge (ablating decay) or halving the threshold
    # un-expires the thesis: both are VERDICT_CRITICAL.
    assert decayed_attribution.baseline_verdict == "decayed_below_threshold"
    assert "restore_live_edge" in decayed_attribution.verdict_critical
    assert "lower_threshold" in decayed_attribution.verdict_critical


def test_half_life_cannot_rescue_a_sub_threshold_edge(
    decayed_attribution,
) -> None:
    # t_expiry = h.log2(E0/T) is zero whenever E0 <= T, regardless of h:
    # extending the half-life of an already-dead edge changes nothing.
    probe = _perturbation(decayed_attribution, "extend_half_life")
    assert probe.classification == "COSMETIC"
    assert probe.perturbed_verdict == "decayed_below_threshold"


def test_capacity_penalty_is_verdict_critical_when_saturating(
    saturating_attribution,
) -> None:
    assert saturating_attribution.baseline_verdict == "saturating_compounder"
    assert (
        "remove_capacity_penalty"
        in saturating_attribution.verdict_critical
    )


def test_crowding_is_cosmetic_when_nothing_rides_on_it(
    saturating_attribution,
) -> None:
    probe = _perturbation(saturating_attribution, "remove_crowding")
    assert probe.classification == "COSMETIC"


def test_golden_state_kill_switches(golden_attribution) -> None:
    # The assumptions that must hold for the golden verdict: the belief
    # gap stays open, the ceiling does not collapse, convergence stays
    # credible, and the hedge does not eat the edge.
    assert golden_attribution.baseline_verdict == (
        "live_underpriced_acceleration"
    )
    assert set(golden_attribution.kill_switches) == {
        "close_belief_gap", "shrink_carrying_capacity",
        "weaken_convergence", "raise_hedge_cost",
    }


def test_hedge_cost_can_kill_a_good_thesis(golden_attribution) -> None:
    # Survival before upside: raising the hedge cost above the thesis
    # edge over-hedges the position and demotes the golden state.
    probe = _perturbation(golden_attribution, "raise_hedge_cost")
    assert probe.classification == "KILL_SWITCH"
    assert probe.rank_delta < 0


def test_weak_convergence_kills_fragile_arbitrage(golden_attribution) -> None:
    probe = _perturbation(golden_attribution, "weaken_convergence")
    assert probe.classification == "KILL_SWITCH"
    assert probe.perturbed_verdict == "potential_without_catalyst"


def test_break_risk_is_an_unsupported_verdict_weight(
    golden_attribution,
) -> None:
    # Honest audit finding: break risk moves the arbitrage net edge but
    # never the verdict — it is cosmetic at every tested operating
    # point, and the rationale names cosmetic weights as unsupported.
    probe = _perturbation(golden_attribution, "remove_break_risk")
    assert probe.classification == "COSMETIC"
    assert any("unsupported" in r for r in golden_attribution.rationale)


# --- Fragility and concentration ---------------------------------------------------
def test_fragility_is_flip_share_and_rises_with_flips(
    golden_attribution, saturating_attribution,
) -> None:
    flips = sum(
        1 for p in golden_attribution.perturbations
        if p.perturbed_verdict != p.baseline_verdict
    )
    assert golden_attribution.fragility == pytest.approx(
        flips / len(golden_attribution.perturbations)
    )
    # The golden fixture has four kill switches; the saturating one
    # flips on fewer twists — fragility orders accordingly.
    assert golden_attribution.fragility > saturating_attribution.fragility


def test_concentration_risk_is_max_rank_shift(decayed_attribution) -> None:
    # restore_live_edge jumps decayed (rank 0) to golden (rank 4):
    # concentration risk = 4/4 = 1.0 — one assumption controls the
    # entire verdict range.
    assert decayed_attribution.concentration_risk == pytest.approx(1.0)


def test_attribution_is_deterministic_and_serializable() -> None:
    first = attribute_lifecycle_verdict(golden_section()).to_dict()
    second = attribute_lifecycle_verdict(golden_section()).to_dict()
    assert first == second
    assert json.dumps(first)


# --- Pipeline integration ------------------------------------------------------------
def test_pipeline_attaches_attribution_and_fragility_stamp() -> None:
    payload = copy.deepcopy(STRONG_PAYLOAD)
    payload["lifecycle"] = golden_section()
    out = evaluate_candidate_payload(payload)
    attribution = out["lifecycle"]["attribution"]
    assert attribution["baseline_verdict"] == "live_underpriced_acceleration"
    assert "raise_hedge_cost" in attribution["kill_switches"]
    # 4/16 kill switches >= 0.25 -> the golden state is stamped fragile
    # (warn-only: the final state is untouched).
    assert "LIFECYCLE_FRAGILE" in out["decision"]["reason_codes"]
    assert out["decision"]["final_state"] == "active_watch"


def test_pipeline_without_lifecycle_still_passthrough() -> None:
    out = evaluate_candidate_payload(copy.deepcopy(STRONG_PAYLOAD))
    assert out["lifecycle"] is None
    assert "LIFECYCLE_FRAGILE" not in out["decision"]["reason_codes"]


# --- Calibration ledger -----------------------------------------------------------------
def _pipeline_lifecycle() -> dict:
    payload = copy.deepcopy(STRONG_PAYLOAD)
    payload["lifecycle"] = golden_section()
    return evaluate_candidate_payload(payload)["lifecycle"]


def test_entry_built_from_pipeline_lifecycle_output() -> None:
    lifecycle = _pipeline_lifecycle()
    entry = entry_from_lifecycle(
        lifecycle, entry_id="t1", ticker="gridco",
        data_tier="synthetic_fixture", expected_convergence_days=45,
        narrative_phase="accelerating", crowding=0.3,
    )
    assert entry.ticker == "GRIDCO"
    assert entry.verdict_at_entry == "live_underpriced_acceleration"
    assert entry.predicted_days_to_expiry > 0
    assert entry.k_estimated > 0
    assert entry.fragility_at_entry == pytest.approx(0.25)
    assert "raise_hedge_cost" in entry.kill_switches
    assert json.dumps(entry.to_dict())


def _resolved(entry=None, **overrides):
    entry = entry or entry_from_lifecycle(
        _pipeline_lifecycle(), entry_id="t1", ticker="GRIDCO",
        expected_convergence_days=45,
    )
    resolution = dict(
        resolved_after_days=60, realized_edge=0.4,
        actual_edge_death_day=30, converged=False,
        k_realized=0.5, drawdown_avoided=0.1, upside_sacrificed=0.05,
        verdict_at_exit="priced_in",
        narrative_phase_at_resolution="crowded",
    )
    resolution.update(overrides)
    return resolve_entry(entry, **resolution)


def test_calibration_and_expiry_errors() -> None:
    record = _resolved()
    entry = record.entry
    assert record.calibration_error == pytest.approx(
        abs(entry.predicted_edge - 0.4), abs=1e-4
    )
    assert record.expiry_error == pytest.approx(
        abs(entry.predicted_days_to_expiry - 30), abs=1e-2
    )
    # Mission test: the edge died (day 30) before the thesis resolved
    # (day 60) — the expiry clock was the binding constraint.
    assert record.expired_before_resolution is True
    assert any("DIED before resolution" in r for r in record.rationale)


def test_convergence_score_is_signed_overconfidence() -> None:
    entry = entry_from_lifecycle(
        _pipeline_lifecycle(), entry_id="t2", ticker="GRIDCO",
    )
    missed = _resolved(entry=entry, converged=False)
    hit = _resolved(entry=entry, converged=True,
                    actual_convergence_day=40)
    assert missed.convergence_score == pytest.approx(
        entry.convergence_probability
    )  # P − 0: pure overconfidence
    assert hit.convergence_score == pytest.approx(
        entry.convergence_probability - 1.0
    )  # negative: underconfident


def test_k_error_and_hedge_effectiveness() -> None:
    record = _resolved(k_realized=0.5, drawdown_avoided=0.1,
                       upside_sacrificed=0.05)
    entry = record.entry
    assert record.k_error == pytest.approx(
        abs(entry.k_estimated - 0.5) / 0.5, abs=1e-3
    )
    expected = 0.1 / (0.05 + entry.hedge_cost)
    assert record.hedge_effectiveness == pytest.approx(expected, abs=1e-3)
    assert any("cost more than it protected" in r
               for r in record.rationale)  # effectiveness < 1


def test_unobserved_outcomes_stay_none_not_fine() -> None:
    record = _resolved(actual_edge_death_day=None, k_realized=None)
    assert record.expiry_error is None
    assert record.k_error is None
    assert record.expired_before_resolution is False
    assert any("not observed" in r for r in record.rationale)


def test_ledger_summary_is_honest_about_thin_synthetic_data() -> None:
    records = [_resolved() for _ in range(3)]
    summary = summarize_ledger(records)
    assert summary["count"] == 3 < LEDGER_MIN_RECORDS
    assert summary["status"] == "require_more_data"
    assert summary["data_tier"] == "synthetic_fixture"
    assert summary["mean_calibration_error"] is not None
    assert any("plumbing" in r for r in summary["rationale"])
    assert json.dumps(summary)


def test_one_synthetic_row_keeps_the_whole_summary_synthetic() -> None:
    lifecycle = _pipeline_lifecycle()
    synthetic = entry_from_lifecycle(
        lifecycle, entry_id="s", ticker="A", data_tier="synthetic_fixture",
    )
    backtest = entry_from_lifecycle(
        lifecycle, entry_id="b", ticker="B", data_tier="backtest_replay",
    )
    records = [
        _resolved(entry=synthetic),
        _resolved(entry=backtest),
    ]
    summary = summarize_ledger(records)
    assert summary["data_tier"] == "synthetic_fixture"


def test_no_duplicate_behavior_with_counterfactual_wind_tunnel() -> None:
    # The lifecycle attributor is a pure-section instrument: it must
    # work with no pipeline, no payload, and no adaptation-gate
    # machinery — the counterfactual wind tunnel's territory.
    report = attribute_lifecycle_verdict(golden_section())
    assert report.baseline_verdict == "live_underpriced_acceleration"
    assert len(report.perturbations) == 16
    assert report.advisory_status == "ADVISORY_ONLY"
