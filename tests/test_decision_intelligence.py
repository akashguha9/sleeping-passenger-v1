"""Tests for the Eureka closed-loop decision-intelligence layer.

Covers: Decision Twin creation + immutability + refused predictions + parent
linkage + info-cutoff preservation; falsifiable prediction freezing + hash
integrity; regime storage; actionable uncertainty; value-of-information ranking +
no-value conclusion + redundancy/calibration surprise; intelligence-budget cheap
rejection vs deep allocation; shadow-policy immutability + no-action baseline;
outcome resolution without look-ahead + duplicate/future guards; process vs
outcome four-quadrant; append-only belief revision; the closed-loop daily run;
persistence; and the no-execution invariants.
"""
from __future__ import annotations

import dataclasses

import pytest

from scripts.simulation_intelligence import api_surface as api
from scripts.simulation_intelligence import decision_twin as dt
from scripts.simulation_intelligence import regime as regime_mod
from scripts.simulation_intelligence import actionable_uncertainty as unc
from scripts.simulation_intelligence import value_of_information as voi
from scripts.simulation_intelligence import intelligence_budget as ib
from scripts.simulation_intelligence import shadow_policies as sp
from scripts.simulation_intelligence import outcome_resolution as ores
from scripts.simulation_intelligence import belief_revision as br
from scripts.simulation_intelligence import process_outcome as po
from scripts.simulation_intelligence import daily_shadow_run as dsr
from scripts.simulation_intelligence.contracts import MarketObservation


def _obs(**kw):
    d = dict(ticker="RELIANCE.NS", market="IN", as_of="2026-07-15", data_cutoff="2026-07-15",
             price=100.0, prev_close=99.0,
             returns=[0.01, -0.02, 0.015, -0.01, 0.02, -0.03, 0.01, 0.0, -0.012, 0.02],
             volumes=[1e6] * 10, volatility=0.025, spread_bps=8.0, adv_usd=5e7,
             source_count=3, narrative_sources=["a", "b", "c"], freshness_status="FRESH")
    d.update(kw)
    return MarketObservation(**d)


def _council(obs, seed=1):
    import os
    os.environ["SIL_ENABLED"] = "1"
    return api.run_simulation({"ticker": obs.ticker, "market": obs.market, "seed": seed,
                               "observation": obs.to_dict()})


# ---------------------------------------------------------------------------
# Decision Twin + falsifiable predictions
# ---------------------------------------------------------------------------
def test_twin_creation_and_fields():
    obs = _obs()
    twin = dt.build_twin(_council(obs), obs)
    assert twin.twin_id.startswith("TWIN_")
    assert twin.candidate_id == "RELIANCE.NS"
    assert twin.info_cutoff == "2026-07-15"
    assert len(twin.predictions) == 5
    assert twin.regime and twin.uncertainty


def test_twin_immutable_and_hash_detects_tamper():
    obs = _obs()
    twin = dt.build_twin(_council(obs), obs)
    assert twin.verify_integrity()
    tampered = dataclasses.replace(twin, advisory_state="WATCH")
    assert not tampered.verify_integrity()
    with pytest.raises(Exception):
        twin.advisory_state = "WATCH"  # frozen


def test_twin_refuses_prediction_without_price():
    obs = _obs(price=None, returns=[], missing_fields=["price", "returns"])
    twin = dt.build_twin(_council(obs), obs)
    assert len(twin.predictions) == 0
    assert len(twin.refused_predictions) == 1
    assert twin.refused_predictions[0]["evidence_grade"] == "INSUFFICIENT_DATA"


def test_twin_parent_signal_linkage_and_cutoff():
    obs = _obs()
    council = _council(obs)
    council["parent_signal_id"] = "SIG_42"
    twin = dt.build_twin(council, obs)
    assert twin.parent_signal_id == "SIG_42"
    for p in twin.predictions:
        assert p.info_cutoff == twin.info_cutoff
        assert p.immutability_hash


def test_prediction_hash_integrity():
    obs = _obs()
    twin = dt.build_twin(_council(obs), obs)
    # Two builds from the same inputs → identical prediction hashes.
    twin2 = dt.build_twin(_council(obs), obs)
    assert [p.immutability_hash for p in twin.predictions] == \
           [p.immutability_hash for p in twin2.predictions]


# ---------------------------------------------------------------------------
# Regime + uncertainty
# ---------------------------------------------------------------------------
def test_regime_classification():
    r = regime_mod.classify_regime(_obs(volatility=0.06, adv_usd=1e6))
    assert r.volatility_regime == "EXTREME"
    assert r.liquidity_regime == "THIN"
    assert "|" in r.regime_key


def test_uncertainty_decomposition_marks_reducibility():
    prof = unc.decompose(_obs(), _council(_obs()))
    kinds = {c.kind for c in prof.components}
    assert {"aleatoric", "epistemic", "data_quality", "regime", "timing"} <= kinds
    assert any(c.reducible for c in prof.components)
    assert any(not c.reducible for c in prof.components)


# ---------------------------------------------------------------------------
# Value of Information
# ---------------------------------------------------------------------------
def test_voi_recommends_research_when_uncertain_and_thin_sources():
    obs = _obs(source_count=1, narrative_sources=["a"], volatility=0.045, freshness_status="FRESH")
    rp = voi.rank_information(obs, _council(obs), budget=0.5)
    assert rp.verdict in ("ACQUIRE", "WAIT_FOR_CATALYST")


def test_voi_can_conclude_no_research_worthwhile():
    # (a) A genuinely robust, well-sourced, well-calibrated situation: convergent
    # beliefs make new information largely redundant → no research worthwhile.
    obs = _obs(source_count=6, narrative_sources=list("abcdef"), volatility=0.008)
    robust_council = {"aggregate_vote": "WATCH", "fragility": 0.1, "robustness": 0.9,
                      "disagreement_class": "CONSENSUS_ROBUST", "tail_warnings": []}
    rp = voi.rank_information(obs, robust_council, budget=0.5, calibration_reliability=0.95)
    assert rp.verdict in ("NO_RESEARCH_WORTHWHILE", "WAIT_FOR_CATALYST")
    assert rp.top_action == "NO_RESEARCH_WORTHWHILE"
    # (b) The budget gate: nothing clears an impossibly small budget.
    rp2 = voi.rank_information(_obs(source_count=1), _council(_obs()), budget=0.01)
    assert rp2.verdict in ("NO_RESEARCH_WORTHWHILE", "WAIT_FOR_CATALYST")


def test_voi_calibration_amplifier_raises_value_when_miscalibrated():
    obs = _obs(source_count=1)
    c = _council(obs)
    poor = voi.rank_information(obs, c, calibration_reliability=0.1)
    good = voi.rank_information(obs, c, calibration_reliability=0.95)
    assert poor.ranked[0].net_voi > good.ranked[0].net_voi


def test_voi_redundancy_discount_applies():
    obs_few = _obs(source_count=1)
    obs_many = _obs(source_count=6, narrative_sources=list("abcdef"))
    c = _council(obs_few)
    few = voi.rank_information(obs_few, c)
    many = voi.rank_information(obs_many, c)
    # More independent sources → higher redundancy discount → same item worth less.
    item = few.ranked[0].item
    few_e = next(e for e in few.ranked if e.item == item)
    many_e = next((e for e in many.ranked if e.item == item), None)
    if many_e:
        assert many_e.redundancy_discount <= few_e.redundancy_discount


# ---------------------------------------------------------------------------
# Intelligence budget
# ---------------------------------------------------------------------------
def test_budget_rejects_weak_candidate_cheaply():
    obs = api.build_observation({"ticker": "JUNK", "source_count": 0})
    b = ib.allocate(obs, uncertainty=0.5, tail_risk=0.0, value_of_information=0.0)
    assert b.analysis_depth == "REJECT_CHEAP"
    assert not b.run_full_council


def test_budget_deep_for_high_value_uncertainty():
    obs = _obs()
    b = ib.allocate(obs, prescreen_confidence=0.5, uncertainty=0.7, tail_risk=0.5,
                    value_of_information=0.2)
    assert b.analysis_depth == "DEEP"
    assert b.run_pairwise_ablation


def test_budget_stops_on_strong_low_uncertainty():
    obs = _obs(volatility=0.008, adv_usd=8e7, source_count=5)
    b = ib.allocate(obs, prescreen_confidence=0.7, uncertainty=0.2, value_of_information=0.0)
    assert b.stop_researching


# ---------------------------------------------------------------------------
# Shadow policies
# ---------------------------------------------------------------------------
def test_shadow_policies_immutable_and_no_action_baseline():
    obs = _obs()
    council = _council(obs)
    twin = dt.build_twin(council, obs)
    decisions = sp.evaluate_policies(council, twin.twin_id)
    assert len(decisions) == len(sp.policy_names())
    assert any(d.policy == "no_action" and d.advisory_state == "WATCH" for d in decisions)
    for d in decisions:
        assert sp.verify_decision(d)
        # tampering the state breaks the hash
        bad = dataclasses.replace(d, advisory_state="RISK_BLOCK")
        assert not sp.verify_decision(bad)


def test_shadow_policy_case_scoring():
    obs = _obs()
    decisions = [d.to_dict() for d in sp.evaluate_policies(_council(obs), "T1")]
    res = sp.compare_on_outcome(decisions, adverse=True, tail=True)
    assert "per_policy" in res
    # risk_first should have caught an adverse+tail case if it was defensive
    assert set(res["per_policy"]) == set(sp.policy_names())


# ---------------------------------------------------------------------------
# Outcome resolution — leakage safety
# ---------------------------------------------------------------------------
def _pred(cutoff="2026-06-01", window=20, kind="PROBABILITY", prob=0.7, target="adverse drawdown <= -5% within"):
    return {"prediction_id": "P1", "twin_id": "T1", "candidate_id": "X",
            "info_cutoff": cutoff, "kind": kind, "probability": prob,
            "outcome_window_days": window, "target_variable": target,
            "immutability_hash": "h"}


def test_resolution_excludes_lookahead_bars():
    bars = [{"date": "2026-06-01", "close": 100}, {"date": "2026-06-02", "close": 100},
            {"date": "2026-06-20", "close": 90}]
    o = ores.resolve(_pred(), bars, session_date="2026-07-15")
    assert o.resolved
    assert o.entry_date == "2026-06-02"  # strictly after cutoff
    assert o.adverse  # -10% drawdown


def test_resolution_future_window_unresolved():
    bars = [{"date": "2026-06-02", "close": 100}, {"date": "2026-06-05", "close": 98}]
    o = ores.resolve(_pred(), bars, session_date="2026-06-06")  # window not elapsed
    assert not o.resolved
    assert o.reason == "FUTURE_UNRESOLVED"


def test_resolution_probability_brier_and_hit():
    bars = [{"date": "2026-06-02", "close": 100}, {"date": "2026-06-21", "close": 92}]
    o = ores.resolve(_pred(prob=0.7), bars, session_date="2026-07-15")
    assert o.resolved and o.brier_contribution is not None
    assert o.hit is True  # predicted adverse (0.7) and it was adverse


def test_resolution_interval_prediction():
    p = _pred(kind="INTERVAL", prob=None, target="realized daily volatility in band")
    p["interval_low"], p["interval_high"] = 0.0, 0.1
    bars = [{"date": f"2026-06-{d:02d}", "close": 100 + d} for d in range(2, 22)]
    o = ores.resolve(p, bars, session_date="2026-07-15")
    assert o.resolved and o.hit is not None


# ---------------------------------------------------------------------------
# Belief revision — append-only
# ---------------------------------------------------------------------------
def test_belief_revision_classes():
    over = br.revise("T1", 1, "WATCH", "RISK_BLOCK", 0.3, 0.9, evidence_arrival="crash", days_since_signal=2)
    assert over.revision_class in ("OVERREACTION", "CORRECT_UPDATE")
    none = br.revise("T1", 2, "WATCH", "WATCH", 0.5, 0.51, evidence_arrival="noise", days_since_signal=3)
    assert none.revision_class == "NO_UPDATE"


def test_belief_timeline_summary():
    revs = [br.revise("T1", i, "WATCH", "AVOID" if i % 2 else "WATCH", 0.5, 0.6,
                      evidence_arrival="e", days_since_signal=i).to_dict() for i in range(4)]
    s = br.analyse_timeline(revs)
    assert s["n"] == 4 and "churn" in s


# ---------------------------------------------------------------------------
# Process vs outcome
# ---------------------------------------------------------------------------
def test_process_quality_outcome_independent():
    obs = _obs()
    pq = po.score_process(obs, _council(obs))
    assert 0.0 <= pq.score <= 10.0
    assert pq.no_execution_compliant


def test_process_quality_capped_on_no_execution_violation():
    obs = _obs()
    council = dict(_council(obs))
    council["execution_gate"] = "OPEN"  # simulate a (impossible) violation
    council["broker_api_called"] = True
    pq = po.score_process(obs, council)
    assert pq.score <= 3.0
    assert not pq.no_execution_compliant


def test_four_quadrant_classification():
    assert po.classify(8.0, 3.0).quadrant == "GOOD_PROCESS_BAD_OUTCOME"
    assert po.classify(3.0, 8.0).quadrant == "BAD_PROCESS_GOOD_OUTCOME"
    # good process, bad outcome must NOT be penalised
    v = po.classify(8.0, 2.0)
    assert v.ledger_signal == "protect_process_credit"
    # bad process, good outcome must NOT be rewarded
    assert po.classify(2.0, 9.0).ledger_signal == "flag_lucky_process"


# ---------------------------------------------------------------------------
# Closed-loop daily run
# ---------------------------------------------------------------------------
def test_daily_shadow_run_closes_loop(monkeypatch):
    monkeypatch.setenv("SIL_ENABLED", "1")
    cands = [_obs().to_dict(), {"ticker": "JUNK", "source_count": 0}]
    out = dsr.run_daily_shadow(cands, session_date="2026-07-15", seed=1)
    assert out["ok"]
    assert out["rejected_cheaply"] >= 1
    assert out["twins_created"] >= 1
    assert out["predictions_frozen"] >= 1
    assert out["outcome_jobs_registered"] >= 1
    assert out["human_action_required"] is False


def test_daily_shadow_run_no_execution(monkeypatch):
    monkeypatch.setenv("SIL_ENABLED", "1")
    out = dsr.run_daily_shadow([_obs().to_dict()], session_date="2026-07-15")
    assert out["execution_gate"] == "LOCKED"
    assert out["broker_api_called"] is False
    assert out["ai_execution_count"] == 0


def test_daily_shadow_run_disabled_fails_closed(monkeypatch):
    monkeypatch.setenv("SIL_ENABLED", "0")
    out = dsr.run_daily_shadow([_obs().to_dict()], session_date="2026-07-15")
    assert out["ok"] is False


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def test_twin_and_outcome_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("SIL_ENABLED", "1")
    from scripts import persistence as P
    dbp = tmp_path / "t.db"
    P.init_schema(dbp)
    obs = _obs(data_cutoff="2026-06-01")
    twin = dt.build_twin(_council(obs), obs)
    tid = P.insert_decision_twin(twin.to_dict(), db_path=dbp)
    jobs = [{"prediction_id": p.prediction_id, "twin_id": tid, "candidate_id": obs.ticker,
             "info_cutoff": p.info_cutoff, "outcome_window_days": p.outcome_window_days,
             "resolution_method": p.resolution_method} for p in twin.predictions]
    assert P.register_outcome_jobs(jobs, db_path=dbp) == len(jobs)
    got = P.get_decision_twin(tid, db_path=dbp)
    assert got and got["immutability_hash"] == twin.immutability_hash
    assert got["execution_gate"] == "LOCKED" and got["broker_api_called"] == 0
    # due jobs after the window
    due = P.get_due_outcome_jobs("2026-07-15", db_path=dbp)
    assert len(due) == len(jobs)
    # resolve one; job → RESOLVED (idempotent, no prediction mutation)
    o = ores.resolve(twin.predictions[0].to_dict(),
                     [{"date": "2026-06-02", "close": 100}, {"date": "2026-06-21", "close": 90}],
                     session_date="2026-07-15")
    P.record_prediction_outcome(o.to_dict(), db_path=dbp)
    assert len(P.get_due_outcome_jobs("2026-07-15", db_path=dbp)) == len(jobs) - 1
    outs = P.get_prediction_outcomes(db_path=dbp)
    assert len(outs) == 1 and outs[0]["execution_gate"] == "LOCKED"


def test_belief_revision_persistence_append_only(tmp_path):
    from scripts import persistence as P
    dbp = tmp_path / "t.db"
    P.init_schema(dbp)
    r1 = br.revise("T1", 1, "WATCH", "AVOID", 0.5, 0.7, evidence_arrival="e1", days_since_signal=1)
    r2 = br.revise("T1", 2, "AVOID", "WAIT", 0.7, 0.6, evidence_arrival="e2", days_since_signal=3)
    P.append_belief_revision(r1.to_dict(), db_path=dbp)
    P.append_belief_revision(r2.to_dict(), db_path=dbp)
    # re-append r1 is a no-op (idempotent) — history is append-only, never overwritten
    P.append_belief_revision(r1.to_dict(), db_path=dbp)
    tl = P.get_belief_timeline("T1", db_path=dbp)
    assert [r["seq"] for r in tl] == [1, 2]
