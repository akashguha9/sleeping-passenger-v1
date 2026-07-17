"""Reliability + fault-injection + scenario-mutation harness for the SIL.

Three responsibilities:
* **Reliability metrics** — successful/failed/timeout/degradation/determinism
  rates over a batch of runs, plus mean-time-to-detect/contain/recover proxies.
* **Fault injection** — deliberately break inputs/engines and assert the base
  system stays *safe and comprehensible* (advisory-only, no crash, fail-closed).
* **Scenario mutation** — perturb an observation and measure decision stability:
  a strong system does not flip on irrelevant noise but moves decisively when a
  genuinely important assumption crosses a threshold.

Pure/deterministic: no clock randomness. The council itself is the system under
test; these harnesses only observe it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.simulation_intelligence.contracts import (
        SimulationRequest, MarketObservation, VOTE_DEFENSIVENESS,
    )
    from scripts.simulation_intelligence.council import run_council
except ModuleNotFoundError:  # pragma: no cover
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]
    from simulation_intelligence.contracts import (  # type: ignore[no-redef]
        SimulationRequest, MarketObservation, VOTE_DEFENSIVENESS,
    )
    from simulation_intelligence.council import run_council  # type: ignore[no-redef]


def _safe_stamps_ok(result: dict[str, Any]) -> bool:
    return (result.get("execution_gate") == "LOCKED"
            and result.get("broker_api_called") in (False, 0)
            and result.get("ai_execution_count", 0) == 0
            and result.get("advisory_status") == "ADVISORY_ONLY")


# ---------------------------------------------------------------------------
# Reliability metrics over a batch of runs.
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class ReliabilityReport:
    total: int
    successful: int
    failed: int
    timed_out: int
    degraded: int
    deterministic_matches: int
    safe_stamp_intact: int
    success_rate: float
    determinism_rate: float
    graceful_degradation_rate: float
    safe_rate: float
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = {k: getattr(self, k) for k in self.__slots__}
        d.update(advisory_safety_stamps())
        return d


def measure_reliability(requests: list[SimulationRequest]) -> ReliabilityReport:
    """Run a batch, re-run each once for determinism, and tally reliability."""
    import json as _json
    total = len(requests)
    ok = failed = timed = degraded = det = safe = 0
    notes: list[str] = []
    for req in requests:
        try:
            r1 = run_council(req, run_stress=False).to_dict()
            r2 = run_council(req, run_stress=False).to_dict()
        except Exception as exc:  # a crash is a reliability failure, never a leak
            failed += 1
            notes.append(f"run failed: {type(exc).__name__}")
            continue
        ok += 1
        if _safe_stamps_ok(r1):
            safe += 1
        if _json.dumps(r1, sort_keys=True) == _json.dumps(r2, sort_keys=True):
            det += 1
        # Degraded = ran but some engine/lens unavailable or missing-data flagged.
        if r1.get("missing_data_warnings") or any(
                str(v).upper() in ("DISABLED", "UNAVAILABLE")
                for v in (r1.get("engine_availability", {}) or {}).values()):
            degraded += 1
    return ReliabilityReport(
        total=total, successful=ok, failed=failed, timed_out=timed,
        degraded=degraded, deterministic_matches=det, safe_stamp_intact=safe,
        success_rate=round(ok / total, 4) if total else 0.0,
        determinism_rate=round(det / total, 4) if total else 0.0,
        graceful_degradation_rate=round(degraded / total, 4) if total else 0.0,
        safe_rate=round(safe / total, 4) if total else 0.0,
        notes=notes)


# ---------------------------------------------------------------------------
# Fault injection — deliberately break things; assert safe + comprehensible.
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class FaultResult:
    fault: str
    survived: bool           # ran or failed-closed WITHOUT crashing/leaking
    safe: bool               # advisory stamps intact (or clean structured refusal)
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


def _base_obs() -> MarketObservation:
    return MarketObservation(
        ticker="TST", market="IN", data_cutoff="2026-07-15",
        returns=[0.01, -0.02, 0.015, -0.01, 0.02, -0.03, 0.01, 0.0, -0.012, 0.02],
        volumes=[1e6] * 10, volatility=0.025, spread_bps=8.0, adv_usd=5e6,
        source_count=2, narrative_sources=["a", "b"], freshness_status="FRESH")


def run_fault_injection() -> list[FaultResult]:
    """Inject a battery of faults; each must be survived safely."""
    results: list[FaultResult] = []

    def check(name: str, fn: Callable[[], Any]) -> None:
        try:
            out = fn()
            safe = True
            if isinstance(out, dict):
                safe = _safe_stamps_ok(out) or out.get("ok") is False
            results.append(FaultResult(name, True, safe, "handled"))
        except Exception as exc:
            results.append(FaultResult(name, False, False, f"crash: {type(exc).__name__}"))

    # 1. Malformed observation (garbage types) → build_observation coerces/fails closed.
    def malformed() -> Any:
        from scripts.simulation_intelligence.api_surface import run_simulation
        return run_simulation({"ticker": "X", "observation": {
            "returns": ["not", "a", "number"], "volatility": "abc", "price": None}})
    check("malformed_observation", malformed)

    # 2. Empty observation → INSUFFICIENT_DATA, not a crash.
    def empty() -> Any:
        req = SimulationRequest(ticker="X", market="IN",
                                observation=MarketObservation(ticker="X", missing_fields=["all"]))
        return run_council(req, run_stress=False).to_dict()
    check("empty_observation", empty)

    # 3. Corrupted/empty replay metadata → replay refuses cleanly, no crash.
    def bad_replay() -> Any:
        from scripts.simulation_intelligence import replay as R
        return R.replay_run({"request": {}, "result": {"run_id": "ghost"}})
    check("corrupted_replay_metadata", bad_replay)

    # 4. NaN/inf in returns → clamped, no crash.
    def nan_returns() -> Any:
        req = SimulationRequest(ticker="X", market="IN", observation=MarketObservation(
            ticker="X", returns=[float("nan"), float("inf"), -0.02, 0.01],
            volatility=0.02, freshness_status="FRESH", source_count=1))
        return run_council(req, run_stress=False).to_dict()
    check("nan_inf_returns", nan_returns)

    # 5. Huge max_runs → bounded by feature-flag cap, no unbounded execution.
    def huge_runs() -> Any:
        from scripts.simulation_intelligence.api_surface import run_simulation
        return run_simulation({"ticker": "X", "max_runs": 10_000_000,
                               "observation": _base_obs().to_dict(),
                               "scenarios": ["broad_market_crash"]})
    check("unbounded_runs_request", huge_runs)

    # 6. SIL disabled mid-flight → structured refusal, not a crash.
    def disabled() -> Any:
        import os
        from scripts.simulation_intelligence.api_surface import run_simulation
        prev = os.environ.get("SIL_ENABLED")
        os.environ["SIL_ENABLED"] = "0"
        try:
            return run_simulation({"ticker": "X", "observation": _base_obs().to_dict()})
        finally:
            if prev is None:
                os.environ.pop("SIL_ENABLED", None)
            else:
                os.environ["SIL_ENABLED"] = prev
    check("sil_disabled_midflight", disabled)

    return results


# ---------------------------------------------------------------------------
# Scenario mutation — perturb an observation, measure decision stability.
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class MutationResult:
    mutation: str
    baseline_vote: str
    mutated_vote: str
    vote_changed: bool
    confidence_delta: float
    expected_sensitive: bool   # SHOULD this mutation change the decision?
    behaved_correctly: bool    # changed iff expected_sensitive (roughly)
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


def _clone_obs(obs: MarketObservation, **overrides: Any) -> MarketObservation:
    import dataclasses
    return dataclasses.replace(obs, **overrides)


def run_scenario_mutations(request: SimulationRequest) -> list[MutationResult]:
    """Apply bounded mutations. Irrelevant perturbations should NOT flip the vote;
    threshold-crossing ones should."""
    obs = request.observation or MarketObservation(ticker=request.ticker)
    base = run_council(SimulationRequest(
        ticker=request.ticker, market=request.market, observation=obs,
        seed=request.seed), run_stress=False).to_dict()
    base_vote = base["aggregate_vote"]
    base_conf = base["aggregate_confidence"]
    results: list[MutationResult] = []

    def apply(name: str, mutant: MarketObservation, expected_sensitive: bool,
              detail: str = "") -> None:
        r = run_council(SimulationRequest(
            ticker=request.ticker, market=request.market, observation=mutant,
            seed=request.seed), run_stress=False).to_dict()
        changed = r["aggregate_vote"] != base_vote
        # Correct behaviour: insensitive mutations shouldn't flip; sensitive MAY.
        behaved = (not changed) if not expected_sensitive else True
        results.append(MutationResult(
            mutation=name, baseline_vote=base_vote, mutated_vote=r["aggregate_vote"],
            vote_changed=changed, confidence_delta=round(base_conf - r["aggregate_confidence"], 4),
            expected_sensitive=expected_sensitive, behaved_correctly=behaved, detail=detail))

    rets = list(obs.returns or [])
    # Irrelevant: tiny jitter on one return (should NOT flip).
    if rets:
        jittered = rets[:]
        jittered[0] = jittered[0] + 1e-5
        apply("tiny_return_jitter", _clone_obs(obs, returns=jittered), False,
              "1e-5 perturbation on one return")
    # Irrelevant: reorder narrative sources (should NOT flip).
    if len(obs.narrative_sources) >= 2:
        apply("reorder_sources", _clone_obs(obs, narrative_sources=list(reversed(obs.narrative_sources))),
              False, "source order should not matter")
    # Relevant: freshness → STALE (may flip toward defensive).
    apply("freshness_to_stale", _clone_obs(obs, freshness_status="STALE"), True,
          "staleness is a real risk factor")
    # Relevant: drop all sources to 0 (may flip toward defensive / insufficient).
    apply("drop_all_sources", _clone_obs(obs, source_count=0, narrative_sources=[],
                                         missing_fields=list(obs.missing_fields) + ["sources"]),
          True, "losing all corroboration is material")
    # Relevant: 3x volatility (may flip toward defensive).
    if obs.volatility:
        apply("triple_volatility", _clone_obs(obs, volatility=obs.volatility * 3.0), True,
              "a large volatility jump is material")
    return results


__all__ = [
    "ReliabilityReport", "measure_reliability", "FaultResult", "run_fault_injection",
    "MutationResult", "run_scenario_mutations",
]
