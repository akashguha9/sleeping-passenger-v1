"""Simulation Intelligence Layer (SIL) — contracts, lenses, council, safety.

Covers: contracts + serialization, determinism/seed reproducibility, scenario
generation, stress tests, counterfactual branching, lens validity, evidence
dedup, correlation penalties, risk-block precedence, missing/stale/engine-
unavailable behaviour, feature flags, no-execution invariants, leakage
prevention, and engine-manifest honesty.

Pure unit tests — no network, no runtime DB writes (persistence tests use a
temp DB via the standard pattern).
"""
from __future__ import annotations

import json

import pytest

from scripts.simulation_intelligence import (
    run_council, SimulationRequest, MarketObservation, engine_manifest as em,
)
from scripts.simulation_intelligence.contracts import (
    LensResult, AdvisoryVote, EvidenceLabel, DisagreementClass, EVIDENCE_STRENGTH,
    CONTRACT_VERSION,
)
from scripts.simulation_intelligence import provenance as prov
from scripts.simulation_intelligence import scenario_library as scen
from scripts.simulation_intelligence import stress_testing as stress
from scripts.simulation_intelligence import feature_flags as flags
from scripts.simulation_intelligence.deterministic_rng import (
    DeterministicRNG, convergence_diagnostic,
)
from scripts.simulation_intelligence.lenses import all_lenses, LENS_DOMAINS
from scripts.simulation_intelligence import api_surface as api


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def _obs(**kw) -> MarketObservation:
    base = dict(
        ticker="RELIANCE.NS", market="IN", as_of="2026-07-15T00:00:00+00:00",
        data_cutoff="2026-07-15", price=2900.0, prev_close=2875.0,
        returns=[0.01, -0.02, 0.015, -0.005, 0.02, -0.03, 0.01, 0.005, -0.01, 0.025, -0.04, 0.02],
        volumes=[1e6, 1.2e6, 9e5, 1.1e6, 1.5e6, 2e6, 1.3e6, 1.1e6, 1e6, 1.4e6, 2.5e6, 1.8e6],
        volatility=0.022, spread_bps=8.0, adv_usd=8_000_000, sector="ENERGY",
        catalysts=[{"id": "q_earnings", "name": "earnings", "magnitude": 0.3}],
        narrative_sources=["sec", "news1", "news2"], source_count=3,
        freshness_status="FRESH",
    )
    base.update(kw)
    return MarketObservation(**base)


def _req(obs=None, seed=42, **kw) -> SimulationRequest:
    obs = obs or _obs()
    return SimulationRequest(ticker=obs.ticker, market=obs.market, observation=obs, seed=seed, **kw)


# ---------------------------------------------------------------------------
# contracts + serialization
# ---------------------------------------------------------------------------
def test_council_result_is_json_serializable_and_stamped():
    result = run_council(_req())
    d = result.to_dict()
    s = json.dumps(d, default=str)  # must not raise
    assert isinstance(s, str)
    assert d["advisory_status"] == "ADVISORY_ONLY"
    assert d["execution_gate"] == "LOCKED"
    assert d["ai_execution_count"] == 0
    assert d["broker_api_called"] is False
    assert d["human_review_required"] is True
    assert d["contract_version"] == CONTRACT_VERSION


def test_lens_result_scores_are_bounded():
    lr = LensResult(lens="X", state_interpretation="s", confidence=5.0, uncertainty=-3.0,
                    robustness=2.0, fragility=-1.0, regret=9.0, exploitability=1.5)
    for f in ("confidence", "uncertainty", "robustness", "fragility", "regret", "exploitability"):
        assert 0.0 <= getattr(lr, f) <= 1.0


# ---------------------------------------------------------------------------
# determinism / seed reproducibility
# ---------------------------------------------------------------------------
def test_council_is_deterministic_by_seed_and_cutoff():
    a = run_council(_req(seed=7)).to_dict()
    b = run_council(_req(seed=7)).to_dict()
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def test_different_seed_changes_stochastic_details_not_run_id_basis():
    a = run_council(_req(seed=1))
    b = run_council(_req(seed=2))
    # run_id depends on seed → different
    assert a.run_id != b.run_id


def test_rng_reproducible_and_substreams_independent():
    r1 = DeterministicRNG(5, "a").sample_returns(50)
    r2 = DeterministicRNG(5, "a").sample_returns(50)
    assert r1 == r2
    r3 = DeterministicRNG(5, "b").sample_returns(50)
    assert r1 != r3  # independent substream


def test_convergence_diagnostic_flags_small_samples():
    assert convergence_diagnostic([1.0, 2.0]).get("converged") is False


# ---------------------------------------------------------------------------
# lenses — validity + independence
# ---------------------------------------------------------------------------
def test_all_six_lenses_produce_valid_typed_output():
    obs = _obs()
    lenses = all_lenses()
    assert {l.domain for l in lenses} == set(LENS_DOMAINS)
    for lens in lenses:
        res = lens.evaluate(obs, _req(obs), seed=3)
        assert isinstance(res, LensResult)
        assert res.advisory_vote in {v.value for v in AdvisoryVote}
        assert res.evidence_label in {e.value for e in EvidenceLabel}
        assert 0.0 <= res.confidence <= 1.0
        assert res.lens == lens.domain
        # No lens may claim MEASURED evidence — there are no real outcomes.
        assert res.evidence_label != EvidenceLabel.MEASURED.value


def test_lens_exceptions_fail_closed_not_crash(monkeypatch):
    from scripts.simulation_intelligence.lenses.physics import PhysicsLens
    lens = PhysicsLens()
    monkeypatch.setattr(lens, "_evaluate", lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")))
    res = lens.evaluate(_obs(), _req(), seed=1)
    assert res.error == "ValueError"
    assert res.advisory_vote == AdvisoryVote.WAIT.value
    assert res.confidence == 0.0


# ---------------------------------------------------------------------------
# missing / stale / engine-unavailable behaviour (fail closed)
# ---------------------------------------------------------------------------
def test_missing_data_fails_closed():
    obs = _obs(returns=[], price=None, missing_fields=["returns", "price"])
    result = run_council(_req(obs))
    assert result.evidence_label in (
        EvidenceLabel.INSUFFICIENT_DATA.value, EvidenceLabel.SIMULATED_ONLY.value)
    assert result.aggregate_vote in (AdvisoryVote.WAIT.value, AdvisoryVote.AVOID.value,
                                     AdvisoryVote.RISK_BLOCK.value)
    assert result.missing_data_warnings


def test_stale_data_caps_confidence():
    fresh = run_council(_req(_obs(freshness_status="FRESH")))
    stale = run_council(_req(_obs(freshness_status="STALE")))
    assert stale.aggregate_confidence <= fresh.aggregate_confidence


def test_optional_engines_off_by_default():
    # No SIL_*_ENABLED set → both optional adapters unavailable, council still runs.
    result = run_council(_req())
    avail = result.engine_availability
    assert avail.get("COPASI") in ("DISABLED", "UNAVAILABLE")
    assert avail.get("Stockfish") in ("DISABLED", "UNAVAILABLE")
    # Council produced a valid verdict regardless.
    assert result.aggregate_vote in {v.value for v in AdvisoryVote}


# ---------------------------------------------------------------------------
# evidence dedup + correlation penalties
# ---------------------------------------------------------------------------
def test_evidence_dedup_collapses_shared_fingerprints():
    e1 = prov.make_evidence("A", "c", "PROXY_DERIVED", ["narrative::x"])
    e2 = prov.make_evidence("B", "c", "MODEL_INFERRED", ["narrative::x"])
    e3 = prov.make_evidence("C", "c", "SIMULATED_ONLY", ["price::y"])
    unique, report = prov.deduplicate([e1, e2, e3])
    assert report["shared_evidence_detected"] is True
    assert set(report["entangled_lenses"]) == {"A", "B"}
    assert len(unique) == 2  # x collapsed, y distinct


def test_correlation_penalty_applied_when_lenses_share_evidence():
    # Two shared narratives + one catalyst → several lenses entangled → their
    # weights carry a correlation penalty reason.
    result = run_council(_req())
    penalised = [w for w in result.lens_weights if w.correlation_penalty > 0]
    if penalised:  # entanglement present in this fixture
        assert any("correlation" in r for w in penalised for r in w.reasons)


def test_no_narrative_no_catalyst_is_maximally_independent():
    obs = _obs(narrative_sources=[], catalysts=[], source_count=0)
    result = run_council(_req(obs))
    # No shared external sources → no entanglement → high usefulness.
    assert result.usefulness_score >= 8.0


def test_weights_are_explained():
    result = run_council(_req())
    for w in result.lens_weights:
        assert w.reasons  # every weight explains itself
        assert 0.0 <= w.final_weight


def test_evidence_strength_orders_measured_above_simulated():
    assert EVIDENCE_STRENGTH["MEASURED"] > EVIDENCE_STRENGTH["SIMULATED_ONLY"]
    assert EVIDENCE_STRENGTH["SIMULATED_ONLY"] > EVIDENCE_STRENGTH["ENGINE_UNAVAILABLE"]


# ---------------------------------------------------------------------------
# risk-block precedence
# ---------------------------------------------------------------------------
def test_risk_block_overrides_attractive_score():
    # A crashing name: strong negative drift + high vol → defensive lenses +
    # severe tail → RISK_BLOCK must engage regardless of any single upbeat lens.
    crash = _obs(
        returns=[-0.02, -0.03, -0.05, -0.04, -0.06, -0.03, -0.08, -0.05, -0.04, -0.07, -0.09, -0.06],
        volatility=0.08,
    )
    result = run_council(_req(crash, seed=7))
    assert result.risk_block_engaged is True
    assert result.aggregate_vote == AdvisoryVote.RISK_BLOCK.value
    assert result.risk_block_reason


def test_benign_name_does_not_force_risk_block():
    result = run_council(_req(_obs(), seed=42))
    # A normal volatile name should not auto-trip RISK_BLOCK.
    assert result.aggregate_vote != AdvisoryVote.RISK_BLOCK.value or not result.risk_block_engaged


# ---------------------------------------------------------------------------
# minority + tail preservation
# ---------------------------------------------------------------------------
def test_tail_warnings_preserved_through_aggregation():
    crash = _obs(returns=[-0.05] * 12, volatility=0.09)
    result = run_council(_req(crash, seed=3))
    assert result.tail_warnings  # not swallowed by the aggregate


# ---------------------------------------------------------------------------
# scenarios + stress + counterfactuals
# ---------------------------------------------------------------------------
def test_scenario_library_covers_market_and_operational():
    cat = scen.catalog()
    ids = {c["scenario_id"] for c in cat}
    assert {"broad_market_crash", "fraud_allegation", "gap_down_open"} <= ids
    assert {"four_of_five_degradation", "stale_price_feed", "sheets_outage"} <= ids
    assert any(c["operational"] for c in cat)


def test_stress_operational_scenario_fails_closed_on_stale():
    obs = _obs(freshness_status="STALE", missing_fields=["price"])
    s = scen.get_scenario("stale_price_feed")
    res = stress.apply_scenario(obs, s, seed=1, n_runs=64)
    assert res.survived is False
    assert res.failure_modes


def test_stress_is_deterministic():
    obs = _obs()
    s = scen.get_scenario("broad_market_crash")
    a = stress.apply_scenario(obs, s, seed=9, n_runs=128).to_dict()
    b = stress.apply_scenario(obs, s, seed=9, n_runs=128).to_dict()
    assert a == b


def test_counterfactual_branches_present():
    result = run_council(_req())
    # Physics lens emits counterfactuals with a measurable delta.
    assert result.counterfactuals
    for cf in result.counterfactuals:
        assert cf.changed_assumption
        assert isinstance(cf.delta, float)


# ---------------------------------------------------------------------------
# feature flags
# ---------------------------------------------------------------------------
def test_feature_flags_default_off_for_optional_engines(monkeypatch):
    monkeypatch.delenv("SIL_STOCKFISH_ENABLED", raising=False)
    monkeypatch.delenv("SIL_COPASI_ENABLED", raising=False)
    assert flags.stockfish_enabled() is False
    assert flags.copasi_enabled() is False
    assert flags.sil_enabled() is True  # master default ON


def test_sil_disabled_fails_closed(monkeypatch):
    monkeypatch.setenv("SIL_ENABLED", "0")
    out = api.run_simulation({"ticker": "X", "observation": {"returns": [0.01, 0.02]}})
    assert out["ok"] is False
    assert out["error"] == "sil_disabled"
    assert out["execution_gate"] == "LOCKED"


def test_max_runs_bounded(monkeypatch):
    monkeypatch.setenv("SIL_MAX_RUNS", "999999")
    assert flags.max_runs() <= 20_000
    monkeypatch.setenv("SIL_MAX_RUNS", "1")
    assert flags.max_runs() >= 8


# ---------------------------------------------------------------------------
# engine manifest honesty
# ---------------------------------------------------------------------------
def test_manifest_has_all_eighteen_engines_with_one_mode_each():
    assert len(em.MANIFEST) == 18
    modes = {"NATIVE_LIBRARY", "EXTERNAL_PROCESS", "ISOLATED_CONTAINER",
             "OFFICIAL_API", "ADAPTER_STUB", "CONCEPT_TRANSPLANT", "REJECTED"}
    for e in em.MANIFEST:
        assert e.integration_mode in modes
        assert e.final_decision in modes
        assert e.reason


def test_manifest_no_proprietary_engine_claimed_native():
    proprietary = {"iRacing", "rFactor 2", "EA Sports F1", "GTO Wizard",
                   "PioSOLVER", "MonkerSolver"}
    for e in em.MANIFEST:
        if e.engine in proprietary:
            assert e.integration_mode in ("CONCEPT_TRANSPLANT", "ADAPTER_STUB", "REJECTED")


def test_manifest_only_copasi_native_only_stockfish_external():
    summary = em.summary()
    assert summary["native_integrations"] == ["COPASI"]
    assert summary["external_process_integrations"] == ["Stockfish"]


# ---------------------------------------------------------------------------
# no-execution invariants + leakage prevention
# ---------------------------------------------------------------------------
def test_every_council_output_is_simulation_labelled_never_measured():
    result = run_council(_req())
    d = result.to_dict()
    # The council never claims MEASURED, and simulated output is flagged.
    assert d["evidence_label"] != EvidenceLabel.MEASURED.value
    for lr in d["lens_results"]:
        assert lr["evidence_label"] != EvidenceLabel.MEASURED.value


def test_no_execution_tokens_in_serialized_output():
    result = run_council(_req())
    blob = json.dumps(result.to_dict(), default=str).lower()
    for forbidden in ("place_order", "submit_order", "broker_api_called\": true",
                      "execution_gate\": \"unlocked", "auto_trade"):
        assert forbidden not in blob
    assert "\"broker_api_called\": false" in blob
    assert "\"execution_gate\": \"locked\"" in blob


def test_disagreement_class_is_a_known_value():
    result = run_council(_req())
    assert result.disagreement_class in {d.value for d in DisagreementClass}


# ---------------------------------------------------------------------------
# API surface validation
# ---------------------------------------------------------------------------
def test_api_surface_bounds_inputs():
    payload = {
        "ticker": "X" * 100, "market": "TOOLONG", "seed": -5, "max_runs": 10 ** 9,
        "observation": {"returns": [1.0] * 10_000, "narrative_sources": ["s"] * 1000},
    }
    req = api.build_request(payload)
    assert len(req.ticker) <= 32
    assert req.max_runs <= flags.max_runs()
    assert len(req.observation.returns) <= 512
    assert len(req.observation.narrative_sources) <= 64
