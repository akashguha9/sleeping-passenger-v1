"""Tests for the Role-Adjusted Contribution Rating (RACR / "Kanté Index") sprint.

Covers: role contracts + weight immutability, RACR calculation + anti-gaming
caps, contribution-event ledger (diminishing returns, severe penalties),
context difficulty, lens ablation + Shapley bounds + interactions, the signal
bridge (fail-closed + parent linkage), the leakage-safe calibration harness
(look-ahead / future / immutability guards, no auto-promotion), reliability +
fault injection + scenario mutation, optional-engine profiles, five-score
separation + empirical firewall, persistence, and the no-execution invariants.
"""
from __future__ import annotations

import math
import tempfile
from pathlib import Path

import pytest

from scripts.simulation_intelligence import role_contracts as rc
from scripts.simulation_intelligence import contribution_ledger as cl
from scripts.simulation_intelligence import context_difficulty as ctx
from scripts.simulation_intelligence import ablation as ablation_mod
from scripts.simulation_intelligence import racr as racr_mod
from scripts.simulation_intelligence.racr import DimensionEvidence as DE
from scripts.simulation_intelligence import signal_bridge as sb
from scripts.simulation_intelligence import calibration_harness as chm
from scripts.simulation_intelligence import reliability as rel
from scripts.simulation_intelligence import engine_validation as ev
from scripts.simulation_intelligence import champion_challenger as cc
from scripts.simulation_intelligence import role_rating_service as svc
from scripts.simulation_intelligence.contracts import SimulationRequest, MarketObservation


def _obs(**kw):
    d = dict(
        ticker="TST", market="IN", data_cutoff="2026-07-15",
        returns=[0.01, -0.02, 0.015, -0.01, 0.02, -0.03, 0.01, 0.0, -0.012, 0.02, -0.04, 0.02],
        volumes=[1e6] * 12, volatility=0.028, spread_bps=8.0, adv_usd=5e7,
        source_count=3, narrative_sources=["a", "b", "c"], freshness_status="FRESH")
    d.update(kw)
    return MarketObservation(**d)


def _req(**kw):
    return SimulationRequest(ticker="TST", market="IN", observation=_obs(), seed=42, **kw)


# ---------------------------------------------------------------------------
# Role contracts
# ---------------------------------------------------------------------------
def test_registry_has_all_components():
    ids = rc.component_ids()
    assert len(ids) == 18
    for lens in ("physics", "chemistry", "biology", "racing", "chess", "poker"):
        assert f"lens.{lens}" in ids
    for c in ("council", "risk_engine", "calibration", "evidence_provenance",
              "scenario_generator", "stress_testing", "replay", "operator_frontend",
              "signal_reactor", "signal_bridge", "adapter.stockfish", "adapter.copasi"):
        assert c in ids


def test_role_weights_are_immutable():
    w = rc.get_contract("risk_engine").dimension_weights
    w["risk_interception"] = 999.0
    # Mutating the returned copy must NOT affect the contract.
    assert rc.get_contract("risk_engine").dimension_weights["risk_interception"] != 999.0


def test_role_weights_are_role_specific():
    risk = rc.get_contract("risk_engine").dimension_weights
    frontend = rc.get_contract("operator_frontend").dimension_weights
    assert risk["risk_interception"] > risk["operator_usefulness"]
    assert frontend["operator_usefulness"] > frontend["risk_interception"]


def test_every_contract_forbids_execution():
    for c in rc.all_contracts():
        joined = " ".join(c.forbidden_mandates).lower()
        assert "broker order" in joined or "execute a trade" in joined


def test_registry_report_advisory_stamped():
    r = rc.registry_report()
    assert r["execution_gate"] == "LOCKED"
    assert r["broker_api_called"] is False
    assert r["ai_execution_count"] == 0


# ---------------------------------------------------------------------------
# Contribution-event ledger
# ---------------------------------------------------------------------------
def test_diminishing_returns_on_repeated_events():
    one = cl.score_events([cl.make_event("council", "R", "minority_warning_preserved", ordinal=0)])
    five = cl.score_events([cl.make_event("council", "R", "minority_warning_preserved", ordinal=i)
                            for i in range(5)])
    # 5 identical events are worth far less than 5x one event.
    assert five.positive_points < 3.5 * one.positive_points
    assert five.diminished_count == 4


def test_severe_integrity_event_penalises():
    s = cl.score_events([cl.make_event("council", "R", "leakage_detected")])
    assert s.severe_count == 1
    assert s.severe_penalty > 0
    assert s.net_points < 0


def test_positive_and_negative_taxonomies_disjoint_directions():
    pos = set(cl.positive_event_types())
    neg = set(cl.negative_event_types())
    assert pos.isdisjoint(neg)
    assert cl.SEVERE_EVENT_TYPES.issubset(neg)


def test_events_derived_from_run_are_grounded():
    council = {"run_id": "R1", "risk_block_engaged": True, "risk_block_reason": "tail",
               "tail_warnings": ["[POKER] ruin"], "minority_warnings": ["[X] view"],
               "aggregation_explanation": ["evidence dedup: 5/8 unique (duplication 0.37)"],
               "missing_data_warnings": [], "freshness_status": "FRESH",
               "simulation_only": True, "evidence_label": "SIMULATED_ONLY"}
    events = cl.derive_events_from_run(council, None, 0.5)
    assert any(e.event_type == "risk_block_overrode_aggregate" for e in events)
    assert any(e.event_type == "duplicate_evidence_removed" for e in events)
    # every event cites concrete evidence
    assert all(e.evidence for e in events)


# ---------------------------------------------------------------------------
# Context difficulty
# ---------------------------------------------------------------------------
def test_context_difficulty_bounded_and_higher_for_stale_missing():
    easy = ctx.score_context(_obs(freshness_status="FRESH", source_count=4))
    hard = ctx.score_context(_obs(freshness_status="STALE", source_count=0,
                                  missing_fields=["price", "returns", "volatility"]))
    assert 0.0 <= easy.score <= 1.0
    assert hard.score > easy.score


# ---------------------------------------------------------------------------
# RACR engine + anti-gaming
# ---------------------------------------------------------------------------
def _strong_evidence():
    return [
        DE("role_fidelity", 8.5, "MEASURED", 0.9, 40, "tests"),
        DE("coverage", 8.4, "DERIVED", 0.8, 30, "ablation"),
        DE("decision_influence", 7.8, "DERIVED", 0.8, 20, "ablation"),
        DE("uncertainty_handling", 8.0, "DERIVED", 0.8, 15, "council"),
        DE("evidence_quality", 8.2, "DERIVED", 0.8, 20, "provenance"),
        DE("adversarial_resilience", 8.0, "MEASURED", 0.85, 17, "probe"),
        DE("runtime_reach", 9.4, "MEASURED", 0.95, 10, "runtime"),
        DE("regression_resistance", 8.0, "MEASURED", 0.8, 45, "pytest"),
        DE("context_difficulty", 7.5, "DERIVED", 0.7, 10, "context"),
        DE("collaboration", 7.8, "DERIVED", 0.7, 10, "ablation"),
        DE("information_efficiency", 7.5, "PROXY", 0.6, 8, "heuristic"),
    ]


def test_racr_supported_scores_reasonably():
    r = racr_mod.score_component("lens.racing", _strong_evidence(), runtime_reached=True)
    assert 6.5 <= r.role_adjusted_performance <= r.honest_ceiling
    assert r.support == "SUPPORTED"


def test_racr_orphaned_component_capped():
    r = racr_mod.score_component("lens.racing", _strong_evidence(), runtime_reached=False)
    assert r.role_adjusted_performance <= 4.0
    assert any("runtime-reached" in c for c in r.caps_applied)


def test_racr_unsupported_capped_low_confidence():
    r = racr_mod.score_component("lens.racing", [], runtime_reached=True)
    assert r.support == "UNSUPPORTED"
    assert r.role_adjusted_performance <= 5.0
    assert r.rating_confidence <= 0.4


def test_racr_severe_event_materially_cuts():
    led = cl.score_events([cl.make_event("lens.racing", "R", "simulated_presented_as_measured")])
    r = racr_mod.score_component("lens.racing", _strong_evidence(), ledger=led, runtime_reached=True)
    assert r.severe_events == 1
    assert r.role_adjusted_performance < 6.0


def test_racr_never_exceeds_honest_ceiling():
    ev = [DE(d, 10.0, "MEASURED", 1.0, 100, "x") for d in racr_mod.__dict__ and
          [x for x in ("role_fidelity", "coverage", "decision_influence",
                       "uncertainty_handling", "evidence_quality", "runtime_reach",
                       "regression_resistance", "adversarial_resilience",
                       "context_difficulty", "collaboration", "information_efficiency")]]
    r = racr_mod.score_component("lens.racing", ev, runtime_reached=True)
    assert r.role_adjusted_performance <= r.honest_ceiling


def test_low_sample_labelled():
    ev = [DE("role_fidelity", 9.0, "MEASURED", 0.9, 1, "x"),
          DE("runtime_reach", 9.0, "MEASURED", 0.9, 1, "x")]
    r = racr_mod.score_component("council", ev, runtime_reached=True)
    assert r.support in ("LOW_SAMPLE", "UNSUPPORTED")


def test_five_scores_separate_and_empirical_firewalled():
    ratings = [racr_mod.score_component("council", _strong_evidence(), runtime_reached=True)
               for _ in range(3)]
    fs = racr_mod.five_scores(ratings, empirical_validation_score=1.5, empirical_sample_size=0)
    # empirical stays low regardless of role excellence
    assert fs["empirical_validation"] == 1.5
    assert fs["whole_mvp_maturity"] <= 8.0
    # the five are distinct keys, never collapsed
    for k in ("role_adjusted_performance", "engineering_quality", "decision_utility",
              "empirical_validation", "whole_mvp_maturity"):
        assert k in fs


# ---------------------------------------------------------------------------
# Ablation + marginal contribution
# ---------------------------------------------------------------------------
def test_ablation_runs_end_to_end_exact_shapley():
    res = ablation_mod.run_ablation(_req()).to_dict()
    assert res["shapley_exact"] is True
    assert res["coalition_evaluations"] == 64  # 2^6
    assert len(res["lens_contributions"]) == 6
    assert len(res["interactions"]) == 15  # C(6,2)


def test_ablation_shapley_bounded():
    res = ablation_mod.run_ablation(_req()).to_dict()
    for c in res["lens_contributions"]:
        assert -1.0 <= c["shapley_value"] <= 1.0


def test_ablation_deterministic():
    a = ablation_mod.run_ablation(_req()).to_dict()
    b = ablation_mod.run_ablation(_req()).to_dict()
    assert [c["shapley_value"] for c in a["lens_contributions"]] == \
           [c["shapley_value"] for c in b["lens_contributions"]]


# ---------------------------------------------------------------------------
# Signal bridge (Priority 1)
# ---------------------------------------------------------------------------
def _bars(n=25, exch="NSE", cur="INR"):
    return [{"date": f"2026-06-{d:02d}", "close": 100 + math.sin(d) * 3,
             "adjusted_close": 100 + math.sin(d) * 3, "volume": 1e6,
             "exchange": exch, "currency": cur} for d in range(1, n + 1)]


def test_bridge_reconstructs_and_links_parent():
    r = sb.build_observation_from_bars("RELIANCE.NS", _bars(), market="IN",
                                       session_date="2026-06-27", parent_signal_id="SIG_9")
    assert r.ok
    assert r.parent_signal_id == "SIG_9"
    assert len(r.observation.returns) >= 2
    assert r.observation.freshness_status == "FRESH"


def test_bridge_fails_closed_without_session_date():
    r = sb.build_observation_from_bars("X", _bars(), market="IN")
    assert r.observation.freshness_status == "UNKNOWN"


def test_bridge_fails_closed_on_empty_bars():
    r = sb.build_observation_from_bars("X", [], session_date="2026-06-27")
    assert r.ok is False
    assert "returns" in r.observation.missing_fields


def test_bridge_market_mapping():
    assert sb._map_market("INDIA", "NSE", "INR") == "IN"
    assert sb._map_market("ROW", "NASDAQ", "USD") == "US"
    assert sb._map_market("UNKNOWN", "", "") == "UNKNOWN"


def test_bridge_db_backed(tmp_path, monkeypatch):
    from scripts import persistence as P
    dbp = tmp_path / "t.db"
    P.init_schema(dbp)
    bars = [{"ticker": "INFY.NS", "date": f"2026-06-{d:02d}", "open": 100, "high": 101,
             "low": 99, "close": 100 + math.sin(d) * 2, "adjusted_close": 100 + math.sin(d) * 2,
             "volume": 1e6, "exchange": "NSE", "currency": "INR", "source": "test"}
            for d in range(1, 26)]
    P.insert_ohlcv_bars(bars, db_path=dbp)
    r = sb.build_observation_for_ticker("INFY.NS", session_date="2026-06-27",
                                        parent_signal_id="SIG_X", db_path=dbp)
    assert r.ok
    assert r.observation.market == "IN"
    assert r.parent_signal_id == "SIG_X"


# ---------------------------------------------------------------------------
# Calibration harness (Priority 2) — leakage safety
# ---------------------------------------------------------------------------
def test_prediction_is_immutable():
    council = {"run_id": "S1", "data_cutoff": "2026-06-01", "aggregate_vote": "AVOID",
               "ticker": "X", "market": "IN"}
    p = chm.prediction_from_council(council)
    with pytest.raises(Exception):
        p.predicted_adverse_prob = 0.99  # frozen


def test_calibration_lookahead_guard():
    council = {"run_id": "S1", "data_cutoff": "2026-06-01", "aggregate_vote": "AVOID"}
    p = chm.prediction_from_council(council)
    # bar ON the cutoff date must be excluded as entry
    bars = [{"date": "2026-06-01", "close": 100}, {"date": "2026-06-02", "close": 100},
            {"date": "2026-06-20", "close": 90}]
    o = chm.resolve_prediction(p, bars, session_date="2026-07-15")
    assert o.resolved
    assert o.entry_date == "2026-06-02"  # strictly after cutoff


def test_calibration_future_unresolved_guard():
    council = {"run_id": "S1", "data_cutoff": "2026-06-01", "aggregate_vote": "AVOID"}
    p = chm.prediction_from_council(council)
    bars = [{"date": "2026-06-02", "close": 100}, {"date": "2026-06-20", "close": 90}]
    o = chm.resolve_prediction(p, bars, session_date="2026-06-05")  # window not elapsed
    assert not o.resolved
    assert o.reason == "FUTURE_UNRESOLVED"


def test_calibration_no_auto_promotion():
    council = {"run_id": "S1", "data_cutoff": "2026-06-01", "aggregate_vote": "AVOID"}
    preds, outs = [], []
    for i in range(25):
        c = dict(council, run_id=f"S{i}", aggregate_vote=["WATCH", "AVOID"][i % 2])
        p = chm.prediction_from_council(c)
        preds.append(p)
        ret = -0.08 if i % 2 else 0.03
        bars = [{"date": "2026-06-02", "close": 100},
                {"date": "2026-06-21", "close": 100 * (1 + ret)}]
        outs.append(chm.resolve_prediction(p, bars, session_date="2026-07-15"))
    coh = chm.build_cohort(preds, outs)
    assert coh.resolved_n == 25
    # applied grade NEVER auto-promotes
    assert coh.evidence_grade_applied == "SIMULATED_ONLY"
    assert coh.brier is not None


def test_calibration_low_sample_never_calibrated():
    council = {"run_id": "S1", "data_cutoff": "2026-06-01", "aggregate_vote": "AVOID"}
    p = chm.prediction_from_council(council)
    bars = [{"date": "2026-06-02", "close": 100}, {"date": "2026-06-21", "close": 92}]
    o = chm.resolve_prediction(p, bars, session_date="2026-07-15")
    coh = chm.build_cohort([p], [o])
    assert coh.status in ("LOW_SAMPLE", "NO_DATA")


def test_calibration_dedup_guard():
    council = {"run_id": "S1", "data_cutoff": "2026-06-01", "aggregate_vote": "AVOID"}
    p = chm.prediction_from_council(council)
    bars = [{"date": "2026-06-02", "close": 100}, {"date": "2026-06-21", "close": 92}]
    o = chm.resolve_prediction(p, bars, session_date="2026-07-15")
    coh = chm.build_cohort([p], [o, o, o])  # same outcome three times
    assert coh.resolved_n == 1
    assert coh.excluded["DUPLICATE"] == 2


# ---------------------------------------------------------------------------
# Reliability + fault injection + mutation
# ---------------------------------------------------------------------------
def test_reliability_deterministic_and_safe():
    r = rel.measure_reliability([_req()] * 3).to_dict()
    assert r["determinism_rate"] == 1.0
    assert r["safe_rate"] == 1.0


def test_fault_injection_all_survive_safely():
    faults = rel.run_fault_injection()
    assert faults
    for f in faults:
        assert f.survived, f.fault
        assert f.safe, f.fault


def test_scenario_mutation_irrelevant_does_not_flip():
    muts = rel.run_scenario_mutations(_req())
    irrelevant = [m for m in muts if not m.expected_sensitive]
    assert irrelevant
    for m in irrelevant:
        assert m.behaved_correctly, m.mutation


# ---------------------------------------------------------------------------
# Optional-engine validation + champion-challenger
# ---------------------------------------------------------------------------
def test_engine_validation_base_app_runs_without_engines():
    r = ev.validate_optional_engines()
    assert r["base_app_runs_without_engines"] is True
    assert r["all_never_real_execution"] is True
    assert set(r["optional_real_integrations"]) == {"COPASI", "Stockfish"}


def test_champion_challenger_no_auto_promotion():
    cohort = [SimulationRequest(ticker="X", market="IN", observation=_obs(), seed=s,
                                scenarios=["broad_market_crash"]) for s in range(4)]
    r = cc.evaluate(cohort)
    assert r["recommendation"] in ("NO_CHANGE", "REVIEW_REQUIRED")
    assert "never automatic" in r["note"].lower()


# ---------------------------------------------------------------------------
# Full runtime service + no-execution invariants
# ---------------------------------------------------------------------------
def test_service_produces_five_scores_and_events(monkeypatch):
    monkeypatch.setenv("SIL_ENABLED", "1")
    out = svc.build_ratings(_req())
    fs = out["five_scores"]
    assert fs["components_scored"] == 18
    assert out["contribution_events"]
    assert len(out["ratings"]) == 18
    # empirical firewall holds through the service
    assert fs["empirical_validation"] <= 2.0


def test_service_no_execution_invariants(monkeypatch):
    monkeypatch.setenv("SIL_ENABLED", "1")
    out = svc.build_ratings(_req())
    assert out["execution_gate"] == "LOCKED"
    assert out["broker_api_called"] is False
    assert out["ai_execution_count"] == 0
    assert out["advisory_status"] == "ADVISORY_ONLY"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def test_contribution_event_persistence(tmp_path):
    from scripts import persistence as P
    dbp = tmp_path / "t.db"
    P.init_schema(dbp)
    evs = [cl.make_event("council", "R1", "minority_warning_preserved", ordinal=i).to_dict()
           for i in range(3)]
    assert P.insert_contribution_events(evs, db_path=dbp) == 3
    assert P.insert_contribution_events(evs, db_path=dbp) == 0  # idempotent
    got = P.get_contribution_events(component_id="council", db_path=dbp)
    assert len(got) == 3
    assert got[0]["execution_gate"] == "LOCKED"
    assert got[0]["broker_api_called"] == 0


def test_role_rating_persistence(tmp_path):
    from scripts import persistence as P
    dbp = tmp_path / "t.db"
    P.init_schema(dbp)
    rid = P.insert_role_rating(
        {"rating_id": "RR1", "component_id": "council",
         "role_adjusted_performance": 8.2, "runtime_reached": True}, db_path=dbp)
    assert rid == "RR1"
    rr = P.get_role_ratings(db_path=dbp)
    assert len(rr) == 1
    assert rr[0]["role_adjusted_performance"] == 8.2
    assert rr[0]["runtime_reached"] is True
