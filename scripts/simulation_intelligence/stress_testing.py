"""Stress-test framework — apply scenarios to a candidate, seeded & bounded.

Combines the OpenMM lens (seeded Monte-Carlo, bounded runs, convergence) with
the GROMACS lens (distribution of outcomes, tail states).  Deterministic:
identical (seed, scenario, observation) always yields identical results.
"""
from __future__ import annotations

import math
from typing import Any

try:
    from scripts.simulation_intelligence.contracts import (
        MarketObservation,
        SimulationScenario,
        StressTestResult,
        EvidenceLabel,
    )
    from scripts.simulation_intelligence.deterministic_rng import (
        DeterministicRNG,
        convergence_diagnostic,
    )
    from scripts.simulation_intelligence import uncertainty as unc
except ModuleNotFoundError:  # pragma: no cover
    from simulation_intelligence.contracts import (  # type: ignore[no-redef]
        MarketObservation,
        SimulationScenario,
        StressTestResult,
        EvidenceLabel,
    )
    from simulation_intelligence.deterministic_rng import (  # type: ignore[no-redef]
        DeterministicRNG,
        convergence_diagnostic,
    )
    from simulation_intelligence import uncertainty as unc  # type: ignore[no-redef]


def _base_sigma(obs: MarketObservation) -> float:
    """Daily-return sigma from the observation, fail-closed to a wide default."""
    if obs is not None and obs.volatility is not None and obs.volatility > 0:
        return min(0.2, float(obs.volatility))
    rets = [float(r) for r in (obs.returns if obs else []) if r == r]
    if len(rets) >= 5:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        return min(0.2, max(0.005, math.sqrt(max(var, 0.0))))
    # No data: fail closed to a conservatively *wide* sigma so tails are honest.
    return 0.03


def apply_scenario(
    obs: MarketObservation,
    scenario: SimulationScenario,
    seed: int,
    n_runs: int,
) -> StressTestResult:
    """Simulate the candidate's return under one scenario, seeded.

    Operational scenarios (is_operational=1) don't produce a price impact; they
    produce a *survival* verdict on data/feed integrity instead, so the impact
    is reported as 0 with a failure mode describing the integrity risk.
    """
    sp = scenario.shock_parameters
    is_operational = bool(sp.get("is_operational", 0.0))
    rng = DeterministicRNG(seed, f"stress/{scenario.scenario_id}")
    n_runs = max(8, min(int(n_runs), 20_000))

    if is_operational:
        # Fail-closed verdict: with missing/stale data the candidate does NOT
        # "survive" the scenario for decision purposes.
        missing = list(obs.missing_fields) if obs else []
        stale = (obs.freshness_status.upper() == "STALE") if obs else True
        survived = not stale and not missing
        band = unc.summarize([0.0] * n_runs, convergence="DETERMINISTIC")
        failure_modes = []
        if not survived:
            failure_modes.append(
                f"{scenario.name}: data integrity compromised — advisory must fail closed"
            )
        return StressTestResult(
            scenario_id=scenario.scenario_id,
            scenario_name=scenario.name,
            survived=survived,
            impact=0.0,
            band=band,
            failure_modes=failure_modes,
            evidence_label=EvidenceLabel.SIMULATED_ONLY.value,
        )

    sigma = _base_sigma(obs)
    ret_shock = float(sp.get("ret_shock", 0.0))
    vol_mult = float(sp.get("vol_mult", 1.0))
    # Horizon of a few days for the shock to play out.
    horizon = 5
    shocked_sigma = sigma * vol_mult

    samples: list[float] = []
    for _ in range(n_runs):
        # Cumulative return over the horizon: the deterministic shock plus
        # fat-tailed daily noise scaled by the stressed sigma.
        cum = ret_shock
        for _ in range(horizon):
            cum += rng.student_t(df=4.0, mu=0.0, sigma=shocked_sigma)
        samples.append(cum)

    conv = convergence_diagnostic(samples)
    band = unc.summarize(
        samples,
        convergence="CONVERGED" if conv["converged"] else "NOT_CONVERGED",
    )
    # "Survived" if the 5th percentile outcome is above a -25% ruin threshold.
    survived = band.p05 > -0.25
    failure_modes = []
    if band.tail_low <= -0.25:
        failure_modes.append(
            f"{scenario.name}: tail outcome {band.tail_low:.0%} breaches ruin threshold"
        )
    if not conv["converged"]:
        failure_modes.append(f"{scenario.name}: MC not converged (n={conv['n']})")

    return StressTestResult(
        scenario_id=scenario.scenario_id,
        scenario_name=scenario.name,
        survived=survived,
        impact=round(band.p50, 6),
        band=band,
        failure_modes=failure_modes,
        evidence_label=EvidenceLabel.SIMULATED_ONLY.value,
    )


def run_stress_suite(
    obs: MarketObservation,
    scenarios: list[SimulationScenario],
    seed: int,
    n_runs: int,
    max_scenarios: int = 24,
) -> list[StressTestResult]:
    """Apply a bounded set of scenarios; deterministic given inputs."""
    picked = scenarios[: max(1, min(int(max_scenarios), len(scenarios)))]
    return [apply_scenario(obs, s, seed, n_runs) for s in picked]


def summarize_stress(results: list[StressTestResult]) -> dict[str, Any]:
    """Roll up a stress suite into a compact honesty-preserving summary."""
    if not results:
        return {"n_scenarios": 0, "survived": 0, "worst_tail": 0.0, "failures": []}
    survived = sum(1 for r in results if r.survived)
    worst = min((r.band.tail_low for r in results), default=0.0)
    failures = [fm for r in results for fm in r.failure_modes]
    return {
        "n_scenarios": len(results),
        "survived": survived,
        "survival_rate": round(survived / len(results), 4),
        "worst_tail": round(worst, 6),
        "failures": failures[:20],
    }


__all__ = [
    "apply_scenario", "run_stress_suite", "summarize_stress",
]
