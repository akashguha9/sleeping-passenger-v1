"""Self-feed proofs: the model feeds itself.

Engine outputs (theme crowding, narrative saturation, tyre grip/age,
risk factors, exposure components) wire the opponent section
automatically with provenance; optimistic caller overrides lose to the
engine-derived values (cross-exam asymmetry); thin derivations warn but
never cap; and the wind-tunnel gate experiment measures whether the
self-fed adaptation cap actually avoids losses in walk-forward replay.
"""

from __future__ import annotations

import copy

import pytest

from src.simulator.exposure_resolver import resolve_exposure
from src.simulator.narrative_tracker import track_narrative
from src.simulator.pipeline import evaluate_candidate_payload
from src.simulator.signal_tyres import score_signal_tyre
from src.simulator.theme_mapper import map_theme
from src.simulator.wind_tunnel import run_gate_experiment
from src.strategy.self_feed import (
    derive_opponent_inputs,
    merge_with_caller,
)
from tests.test_simulator_cherry_pick_pipeline import STRONG_PAYLOAD


def crowded_payload() -> dict:
    """STRONG_PAYLOAD soured into a crowded, saturated, weak-signal
    trade: still strong enough to reach active_watch ungated, but the
    engines' own numbers read exhausted_edge once self-fed."""
    payload = copy.deepcopy(STRONG_PAYLOAD)
    payload["narrative"] = {
        "narrative": "crowded grid trade", "mention_count": 120,
        "origin_count": 24, "independent_origin_count": 20,
        "source_quality": 0.8, "narrative_velocity": 0.35,
        "narrative_acceleration": 0.1,
    }
    payload["theme_assessment"] = {
        **payload["theme_assessment"], "crowding": 0.45,
        "valuation_heat": 0.3,
    }
    payload["signals"] = [{
        "signal_type": "backlog", "raw_strength": 45,
        "signal_age_hours": 100, "source_quality": 0.9,
        "confirmation_multiplier": 1.1,
    }]
    return payload


def _engines():
    narrative = track_narrative(
        narrative="t", mention_count=40, origin_count=14,
        independent_origin_count=12, source_quality=0.8,
        narrative_velocity=0.4, narrative_acceleration=0.2,
        contradiction_count=0,
    )
    theme = map_theme(
        theme="t", source_narrative="t", policy_fit=0.8, macro_fit=0.7,
        sector_momentum=0.6, liquidity_support=0.7, risk_appetite=0.6,
        valuation_heat=0.25, crowding=0.3, regulatory_friction=0.2,
        candidate_sectors=[],
    )
    tyres = [score_signal_tyre(
        signal_type="earnings_beat", raw_strength=75.0,
        signal_age_hours=48.0, reaction_lag_hours=0.0,
        source_quality=0.8, confirmation_multiplier=1.0,
        circuit_decay_multiplier=1.0, track_condition_score=0.6,
    )]
    exposure = resolve_exposure(
        ticker="T", theme="t", revenue_exposure=0.7,
        margin_sensitivity=0.5, backlog_linkage=0.8, customer_linkage=0.5,
        geographic_fit=0.6, policy_fit=0.7, supply_chain_position=0.6,
        weak_evidence_penalty=0.0,
    )
    return narrative, theme, tyres, exposure


# --- Derivation: provenance, honesty about absent sections ---------------------
def test_derivation_carries_provenance_and_full_coverage() -> None:
    narrative, theme, tyres, exposure = _engines()
    derived, provenance, coverage = derive_opponent_inputs(
        narrative=narrative, theme=theme, tyres=tyres, exposure=exposure,
        risk_factors={"high_valuation": 0.4},
        narrative_present=True, theme_present=True, exposure_present=True,
        risk_factors_present=True,
    )
    assert coverage == 1.0
    adaptation = derived["adaptation"]
    assert adaptation["crowding"] == pytest.approx(0.3)
    assert adaptation["repricing_observed"] == pytest.approx(0.25)
    assert adaptation["recognition_age_days"] == pytest.approx(2.0)
    assert provenance["adaptation.crowding"] == "theme_mapper.crowding"
    assert provenance["weaknesses"].startswith("crash_simulator")
    assert derived["weaknesses"] == {"high_valuation": 0.4}
    assert "supply_chain_position" in derived["strengths"]
    assert set(derived["capabilities"]) == {
        "revenue", "margin", "backlog", "customer", "geo", "supply_chain",
    }


def test_absent_sections_derive_nothing() -> None:
    # An absent theme section proves nothing about crowding — deriving
    # optimism from defaults would be fabrication.
    narrative, theme, tyres, exposure = _engines()
    derived, provenance, coverage = derive_opponent_inputs(
        narrative=narrative, theme=theme, tyres=[], exposure=exposure,
        risk_factors={}, narrative_present=False, theme_present=False,
        exposure_present=False, risk_factors_present=False,
    )
    assert coverage == 0.0
    assert "adaptation" not in derived
    assert "crowding" not in derived
    assert "weaknesses" not in derived
    assert "strengths" not in derived
    assert provenance == {}


# --- The cross-exam asymmetry ----------------------------------------------------
def test_conservative_caller_override_wins_unchallenged() -> None:
    derived = {"adaptation": {"crowding": 0.3, "signal_strength": 0.6}}
    merged, challenges = merge_with_caller(
        derived,
        {"adaptation": {"crowding": 0.9, "signal_strength": 0.4}},
        {},
    )
    assert merged["adaptation"]["crowding"] == 0.9  # more conservative
    assert merged["adaptation"]["signal_strength"] == 0.4
    assert challenges == []


def test_optimistic_override_loses_and_is_challenged() -> None:
    derived = {"adaptation": {"signal_strength": 0.5, "crowding": 0.6}}
    provenance = {
        "adaptation.signal_strength": "signal_tyres.effective_signal_strength",
    }
    merged, challenges = merge_with_caller(
        derived,
        {"adaptation": {"signal_strength": 0.95, "crowding": 0.1}},
        provenance,
    )
    assert merged["adaptation"]["signal_strength"] == 0.5
    assert merged["adaptation"]["crowding"] == 0.6
    fields = {c.field_name for c in challenges}
    assert fields == {"adaptation.signal_strength", "adaptation.crowding"}
    challenge = next(
        c for c in challenges
        if c.field_name == "adaptation.signal_strength"
    )
    assert challenge.derived_from == "signal_tyres.effective_signal_strength"
    assert challenge.resolution == "conservative_engine_value_used"


def test_small_optimistic_gap_resolves_conservative_without_challenge() -> None:
    derived = {"adaptation": {"signal_strength": 0.50}}
    merged, challenges = merge_with_caller(
        derived, {"adaptation": {"signal_strength": 0.60}}, {},
    )
    assert merged["adaptation"]["signal_strength"] == 0.50
    assert challenges == []  # gap 0.10 < 0.20 — resolved, not prosecuted


def test_omitted_engine_evidenced_weakness_is_challenged() -> None:
    derived = {"weaknesses": {"customer_concentration": 0.7}}
    merged, challenges = merge_with_caller(
        derived, {"weaknesses": {"geo_concentration": 0.4}}, {},
    )
    assert merged["weaknesses"]["customer_concentration"] == 0.7
    assert merged["weaknesses"]["geo_concentration"] == 0.4
    assert any(
        c.field_name == "weaknesses.customer_concentration"
        for c in challenges
    )


def test_strength_claim_above_physics_is_trimmed() -> None:
    derived = {"strengths": {"supply_chain_position": 0.4}}
    merged, challenges = merge_with_caller(
        derived,
        {"strengths": {"supply_chain_position": 0.9, "founder_vision": 0.8}},
        {},
    )
    assert merged["strengths"]["supply_chain_position"] == 0.4
    # Caller-only judgement no engine computes passes through untouched.
    assert merged["strengths"]["founder_vision"] == 0.8
    assert any(
        c.field_name == "strengths.supply_chain_position" for c in challenges
    )


# --- Pipeline: the model catches what nobody asked about ---------------------------
def test_crowded_trade_capped_without_any_opponent_section() -> None:
    control = evaluate_candidate_payload(
        {**crowded_payload(), "self_feed": {"enabled": False}}
    )
    gated = evaluate_candidate_payload(crowded_payload())

    assert control["decision"]["final_state"] == "active_watch"
    assert control["opponent"] is None

    assert gated["opponent"]["self_feed"]["auto_derived"] is True
    assert gated["opponent"]["self_feed"]["coverage"] == 1.0
    assert gated["opponent"]["adaptation"]["state"] == "exhausted_edge"
    assert gated["decision"]["gate_results"]["adaptation_gate"] is False
    assert "EDGE_EXHAUSTED" in gated["decision"]["reason_codes"]
    assert "OPPONENT_SELF_FED" in gated["decision"]["reason_codes"]
    assert gated["decision"]["final_state"] == "watchlist"


def test_exhaustion_without_measured_signal_warns_but_never_caps() -> None:
    payload = crowded_payload()
    payload["signals"] = []  # no tyres -> signal_strength is a default
    payload["theme_assessment"]["crowding"] = 0.9
    payload["theme_assessment"]["valuation_heat"] = 0.8
    out = evaluate_candidate_payload(payload)
    assert out["opponent"]["adaptation"]["state"] == "exhausted_edge"
    # The OAI explosion on a defaulted signal is an artifact, not a
    # finding: the gate must not cap on it.
    assert out["decision"]["gate_results"]["adaptation_gate"] is True
    assert "SELF_FEED_LOW_COVERAGE" in out["decision"]["reason_codes"]
    assert "EDGE_EXHAUSTED" not in out["decision"]["reason_codes"]


def test_pipeline_challenges_optimistic_caller_section() -> None:
    payload = crowded_payload()
    payload["opponent"] = {
        "adaptation": {
            "signal_strength": 0.95, "crowding": 0.05,
            "narrative_saturation": 0.05, "repricing_observed": 0.0,
        },
    }
    out = evaluate_candidate_payload(payload)
    self_feed = out["opponent"]["self_feed"]
    assert self_feed["auto_derived"] is False
    assert len(self_feed["challenges"]) >= 3
    assert "OPPONENT_OVERRIDE_CHALLENGED" in out["decision"]["reason_codes"]
    # Gaming the opponent section did not rescue the trade: the merged
    # (engine) numbers still read exhausted and the cap still landed.
    assert out["opponent"]["adaptation"]["state"] == "exhausted_edge"
    assert out["decision"]["final_state"] == "watchlist"


def test_pipeline_accepts_more_conservative_caller_unchallenged() -> None:
    payload = copy.deepcopy(STRONG_PAYLOAD)
    payload["opponent"] = {
        "adaptation": {"signal_strength": 0.3, "crowding": 0.8,
                       "narrative_saturation": 0.7,
                       "repricing_observed": 0.6},
    }
    out = evaluate_candidate_payload(payload)
    self_feed = out["opponent"]["self_feed"]
    assert self_feed["challenges"] == []
    merged = self_feed["merged_section"]["adaptation"]
    assert merged["crowding"] == 0.8  # caller's caution honored
    assert (
        "OPPONENT_OVERRIDE_CHALLENGED"
        not in out["decision"]["reason_codes"]
    )


def test_disabled_self_feed_with_caller_section_is_verbatim() -> None:
    payload = copy.deepcopy(STRONG_PAYLOAD)
    payload["self_feed"] = {"enabled": False}
    payload["opponent"] = {
        "adaptation": {"signal_strength": 0.95, "crowding": 0.05},
    }
    out = evaluate_candidate_payload(payload)
    self_feed = out["opponent"]["self_feed"]
    assert self_feed["enabled"] is False
    assert self_feed["challenges"] == []
    assert (
        out["opponent"]["self_feed"]["merged_section"]
        == payload["opponent"]
    )


# --- Wind tunnel: do the new gates avoid losses? ------------------------------------
def _bars() -> list[dict]:
    closes: list[float] = []
    for i in range(50):
        if i <= 35:
            closes.append(100.0 + i)
        elif i <= 40:
            closes.append(135.0 - 3.0 * (i - 35))
        else:
            closes.append(120.0 + 2.0 * (i - 40))
    return [
        {"date": f"bar-{i:03d}", "close": close}
        for i, close in enumerate(closes)
    ]


def test_gate_experiment_shows_cap_avoiding_the_losing_bar() -> None:
    def builder(ticker: str, visible: list[dict]) -> dict:
        payload = (
            copy.deepcopy(STRONG_PAYLOAD)
            if len(visible) % 2 == 0
            else crowded_payload()
        )
        payload["ticker"] = ticker
        return payload

    report = run_gate_experiment(
        ticker="GRIDCO", bars=_bars(), price_provenance="SYNTHETIC",
        horizon_days=5, every_n_bars=5, payload_builder=builder,
    )
    assert report.decision_count == 3
    assert report.divergent_count == 1
    divergent = report.divergent_bars[0]
    assert divergent["gated_state"] == "watchlist"
    assert divergent["ungated_state"] == "active_watch"
    # The exact figures quoted in docs/STRATEGY_ENGINE.md.
    assert divergent["forward_return"] == pytest.approx(-0.111, abs=1e-3)
    assert report.undiverged_cohort.mean_forward_return == pytest.approx(
        0.061, abs=1e-3
    )
    assert report.capped_return_disadvantage > 0
    assert report.gates_helping is True
    assert any("pointing at worse bars" in r for r in report.rationale)
    assert report.advisory_status == "ADVISORY_ONLY"


def test_gate_experiment_is_honest_when_gate_never_fires() -> None:
    def builder(ticker: str, visible: list[dict]) -> dict:
        payload = copy.deepcopy(STRONG_PAYLOAD)
        payload["ticker"] = ticker
        return payload

    report = run_gate_experiment(
        ticker="GRIDCO", bars=_bars(), price_provenance="SYNTHETIC",
        horizon_days=5, every_n_bars=5, payload_builder=builder,
    )
    assert report.divergent_count == 0
    assert report.gates_helping is None
    assert any("insufficient evidence" in r for r in report.rationale)
