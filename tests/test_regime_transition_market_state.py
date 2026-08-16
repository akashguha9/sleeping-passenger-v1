"""Tests — regime-transition CES + market state engine.

Covers the sprint testing matrix:
- contract equivalence: same event/rules, different deadline, different
  threshold, ambiguous match, missing resolution criteria (fail-closed);
- market quality: healthy, stale, low-liquidity/wide-spread, missing data;
- probability dynamics: velocity, acceleration, insufficient history;
- divergence dynamics: momentum states incl. information fracture/opposing;
- PMDS: research-trigger stamp, CES blocking, missing-component honesty.
"""
from __future__ import annotations

import pytest

from scripts.prediction_market_semantic_pairing import (
    AMBIGUOUS_MATCH,
    SAME_EVENT_DIFFERENT_THRESHOLD,
    SAME_EVENT_SAME_RESOLUTION,
)
from scripts.regime_transition_contract_equivalence_score import (
    ContractSpec,
    GATE_BLOCKED,
    GATE_DIRECT,
    GATE_INSUFFICIENT,
    GATE_PENALIZED,
    divergence_comparison_allowed,
    score_contract_equivalence,
)
from scripts.regime_transition_market_state_engine import (
    CONSENSUS_SHIFT,
    CONVERGING,
    INFORMATION_FRACTURE,
    INSUFFICIENT_HISTORY,
    OK,
    OPPOSING,
    STABLE,
    UNKNOWN,
    divergence_dynamics,
    prediction_market_divergence_score,
    probability_dynamics,
    venue_quality_score,
)


def _spec(**kw):
    defaults = dict(venue="kalshi", title="Fed cuts rates by June",
                    deadline="2026-06-30", threshold_value=0.25,
                    threshold_unit="pct", resolution_source="FOMC statement",
                    jurisdiction="US")
    defaults.update(kw)
    return ContractSpec(**defaults)


class TestContractEquivalence:
    def test_same_event_same_rules_direct_comparison(self):
        v = score_contract_equivalence(
            _spec(), _spec(venue="polymarket"),
            pairing_classification=SAME_EVENT_SAME_RESOLUTION)
        assert v["ces"] == 100.0
        assert v["gate"] == GATE_DIRECT
        assert divergence_comparison_allowed(v)

    def test_same_title_different_deadline_penalized_or_blocked(self):
        v = score_contract_equivalence(
            _spec(), _spec(venue="polymarket", deadline="2026-09-30"),
            pairing_classification=SAME_EVENT_SAME_RESOLUTION)
        assert v["ces"] < 90.0
        assert v["gate"] in (GATE_PENALIZED, GATE_BLOCKED)
        assert v["dimension_credits"]["deadline"] == 0.0

    def test_same_event_different_threshold_downgraded(self):
        v = score_contract_equivalence(
            _spec(), _spec(venue="polymarket", threshold_value=0.50),
            pairing_classification=SAME_EVENT_DIFFERENT_THRESHOLD)
        assert v["ces"] < 90.0
        assert v["dimension_credits"]["threshold"] == 0.0

    def test_ambiguous_match_blocked(self):
        v = score_contract_equivalence(
            _spec(resolution_source=None, jurisdiction=None),
            _spec(venue="polymarket", resolution_source=None,
                  jurisdiction=None, deadline="2026-07-15",
                  threshold_value=0.75),
            pairing_classification=AMBIGUOUS_MATCH)
        assert v["gate"] == GATE_BLOCKED
        assert not divergence_comparison_allowed(v)

    def test_missing_resolution_criteria_fails_closed_not_zero(self):
        a = ContractSpec(venue="kalshi", title="x")
        b = ContractSpec(venue="polymarket", title="x")
        v = score_contract_equivalence(a, b, pairing_classification=None)
        assert v["gate"] == GATE_INSUFFICIENT
        assert v["ces"] is None  # unknown, never a fake zero
        assert v["metadata_coverage"] == 0.0
        assert not divergence_comparison_allowed(v)

    def test_unknown_dimensions_reported_not_scored(self):
        v = score_contract_equivalence(
            _spec(jurisdiction=None), _spec(venue="polymarket",
                                            jurisdiction=None),
            pairing_classification=SAME_EVENT_SAME_RESOLUTION)
        assert "jurisdiction" in v["unknown_dimensions"]
        assert v["metadata_coverage"] < 1.0


class TestVenueQuality:
    def test_deep_fresh_market_scores_high(self):
        q = venue_quality_score({"volume_usd": 2_000_000, "bid": 0.55,
                                 "ask": 0.56, "depth_usd": 250_000,
                                 "last_trade_age_days": 0})
        assert q["status"] == OK
        assert q["score"] > 75

    def test_stale_market_penalized_and_flagged(self):
        q = venue_quality_score({"volume_usd": 2_000_000, "bid": 0.55,
                                 "ask": 0.56, "depth_usd": 250_000,
                                 "last_trade_age_days": 12})
        assert q["stale"] is True
        assert q["score"] < 90

    def test_thin_wide_market_scores_low(self):
        q = venue_quality_score({"volume_usd": 300, "bid": 0.40,
                                 "ask": 0.55, "depth_usd": 50,
                                 "last_trade_age_days": 1})
        assert q["status"] == OK
        assert q["score"] < 50

    def test_missing_microstructure_is_unknown_not_zero(self):
        q = venue_quality_score({"volume_usd": 1000})
        assert q["status"] == UNKNOWN
        assert q["score"] is None
        assert "spread" in q["missing"]


class TestProbabilityDynamics:
    def test_velocity_and_acceleration(self):
        d = probability_dynamics([(0, 0.35), (1, 0.40), (2, 0.55)])
        assert d["status"] == OK
        assert d["velocity"] == pytest.approx(0.15)
        assert d["acceleration"] == pytest.approx(0.10)

    def test_single_point_insufficient(self):
        d = probability_dynamics([(0, 0.5)])
        assert d["status"] == INSUFFICIENT_HISTORY
        assert d["velocity"] is None

    def test_out_of_range_probabilities_dropped(self):
        d = probability_dynamics([(0, 1.7), (1, -0.2)])
        assert d["status"] == INSUFFICIENT_HISTORY


class TestDivergenceDynamics:
    def test_information_fracture_one_venue_moves(self):
        d = divergence_dynamics([(0, 0.32), (1, 0.38), (2, 0.47)],
                                [(0, 0.31), (1, 0.32), (2, 0.32)])
        assert d["momentum_state"] == INFORMATION_FRACTURE
        assert d["divergence_velocity"] > 0

    def test_opposing_movement(self):
        d = divergence_dynamics([(0, 0.50), (1, 0.56)],
                                [(0, 0.50), (1, 0.42)])
        assert d["momentum_state"] == OPPOSING

    def test_converging_gap_shrinks(self):
        d = divergence_dynamics([(0, 0.40), (1, 0.50)],
                                [(0, 0.70), (1, 0.60)])
        assert d["momentum_state"] in (CONVERGING, OPPOSING)
        assert d["divergence_velocity"] < 0

    def test_consensus_shift_both_move_same_direction(self):
        d = divergence_dynamics([(0, 0.40), (1, 0.50)],
                                [(0, 0.42), (1, 0.52)])
        assert d["momentum_state"] == CONSENSUS_SHIFT

    def test_stable_flat_markets(self):
        d = divergence_dynamics([(0, 0.40), (1, 0.401)],
                                [(0, 0.42), (1, 0.421)])
        assert d["momentum_state"] == STABLE

    def test_one_market_unavailable_insufficient(self):
        d = divergence_dynamics([(0, 0.40), (1, 0.50)], [])
        assert d["status"] == INSUFFICIENT_HISTORY


class TestPMDS:
    def _ces_ok(self):
        return score_contract_equivalence(
            _spec(), _spec(venue="polymarket"),
            pairing_classification=SAME_EVENT_SAME_RESOLUTION)

    def _quality(self):
        return venue_quality_score({"volume_usd": 2_000_000, "bid": 0.55,
                                    "ask": 0.56, "depth_usd": 250_000,
                                    "last_trade_age_days": 0})

    def test_high_quality_real_divergence_triggers_research(self):
        div = divergence_dynamics([(0, 0.32), (1, 0.45), (2, 0.61)],
                                  [(0, 0.31), (1, 0.33), (2, 0.34)])
        p = prediction_market_divergence_score(
            ces_verdict=self._ces_ok(), divergence=div,
            quality_a=self._quality(), quality_b=self._quality())
        assert p["status"] == OK
        assert p["pmds"] > 40
        assert p["signal_class"] == "RESEARCH_TRIGGER_ONLY"
        assert p["experimental"] is True
        assert "lead_lag" in p["missing_components"]  # not assumed, learned

    def test_blocked_ces_blocks_pmds(self):
        bad_ces = score_contract_equivalence(
            _spec(resolution_source=None, jurisdiction=None),
            _spec(venue="polymarket", deadline="2026-09-30",
                  threshold_value=0.9, resolution_source=None,
                  jurisdiction=None),
            pairing_classification=AMBIGUOUS_MATCH)
        div = divergence_dynamics([(0, 0.3), (1, 0.5)], [(0, 0.3), (1, 0.3)])
        p = prediction_market_divergence_score(
            ces_verdict=bad_ces, divergence=div,
            quality_a=self._quality(), quality_b=self._quality())
        assert p["status"] == "BLOCKED_BY_CES"
        assert p["pmds"] is None

    def test_unknown_quality_reported_missing_never_faked(self):
        div = divergence_dynamics([(0, 0.32), (1, 0.45)],
                                  [(0, 0.31), (1, 0.33)])
        p = prediction_market_divergence_score(
            ces_verdict=self._ces_ok(), divergence=div,
            quality_a={"status": UNKNOWN, "score": None},
            quality_b=self._quality())
        if p["status"] == OK:
            assert "market_quality" in p["missing_components"]
        else:
            assert p["pmds"] is None

    def test_forbidden_language_absent(self):
        div = divergence_dynamics([(0, 0.32), (1, 0.45), (2, 0.61)],
                                  [(0, 0.31), (1, 0.33), (2, 0.34)])
        p = prediction_market_divergence_score(
            ces_verdict=self._ces_ok(), divergence=div,
            quality_a=self._quality(), quality_b=self._quality())
        text = str(p).lower()
        for word in ("buy", "sell", "execute", "arbitrage"):
            assert word not in text
