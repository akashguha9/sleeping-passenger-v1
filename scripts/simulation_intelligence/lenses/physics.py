"""Physics lens — MuJoCo + Project Chrono + PhET principles (original code).

Maps the candidate to a constrained dynamic system and reads its stability:

* position       ← price level
* velocity       ← mean recent return
* acceleration   ← change in velocity (return of returns)
* momentum       ← volume-adjusted velocity
* friction       ← spread / illiquidity
* external force ← catalysts
* constraint     ← declared limits (regulatory / balance-sheet), unmodelled => 0
* instability    ← acceleration relative to friction
* collision      ← dependency-graph shock reflection (Chrono multi-body)

These are DEFENSIBLE analogies, never physical facts.  The lens is explicit
that its output is SIMULATED_ONLY / PROXY_DERIVED.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.simulation_intelligence.lenses.base import Lens, clamp, mean, stdev, prov
    from scripts.simulation_intelligence.contracts import (
        LensResult, MarketObservation, SimulationRequest, AdvisoryVote,
        EvidenceLabel, CounterfactualBranch,
    )
    from scripts.simulation_intelligence import scenario_graph as sg
except ModuleNotFoundError:  # pragma: no cover
    from simulation_intelligence.lenses.base import Lens, clamp, mean, stdev, prov  # type: ignore[no-redef]
    from simulation_intelligence.contracts import (  # type: ignore[no-redef]
        LensResult, MarketObservation, SimulationRequest, AdvisoryVote,
        EvidenceLabel, CounterfactualBranch,
    )
    from simulation_intelligence import scenario_graph as sg  # type: ignore[no-redef]


class PhysicsLens(Lens):
    domain = "PHYSICS"
    name = "physics"
    required_fields = ("returns",)

    def _evaluate(self, obs: MarketObservation, request, seed: int) -> LensResult:
        rets = [float(r) for r in obs.returns if r == r]
        velocity = mean(rets[-5:]) if len(rets) >= 2 else (rets[-1] if rets else 0.0)
        prior_v = mean(rets[-10:-5]) if len(rets) >= 10 else 0.0
        acceleration = velocity - prior_v
        vol = stdev(rets) or (obs.volatility or 0.03)

        # Friction from spread + illiquidity (higher => more friction, 0..1).
        spread = obs.spread_bps if obs.spread_bps is not None else 25.0
        friction_spread = clamp(spread / 100.0)  # 100 bps => full friction
        adv = obs.adv_usd if obs.adv_usd else 0.0
        friction_liq = clamp(1.0 - min(1.0, adv / 5_000_000.0)) if adv else 0.7
        friction = clamp(0.5 * friction_spread + 0.5 * friction_liq)

        # External force from catalysts (net signed push, bounded).
        force = 0.0
        for c in obs.catalysts:
            mag = c.get("magnitude", c.get("strength", 0.0))
            try:
                force += float(mag)
            except (TypeError, ValueError):
                continue
        force = clamp(abs(force), 0.0, 1.0)

        # Instability: acceleration relative to volatility, damped by friction.
        raw_instab = abs(acceleration) / (vol + 1e-6)
        instability = clamp(raw_instab * (1.0 - 0.5 * friction))

        # Chrono multi-body: build a dependency graph and measure shock echo.
        graph = sg.build_default_graph(obs.ticker, obs.sector, obs.dependencies)
        collision = graph.systemic_fragility(obs.ticker.upper(), magnitude=1.0)

        # Momentum: volume-adjusted velocity.
        vol_factor = 1.0
        if obs.volumes and len(obs.volumes) >= 2:
            recent = mean(obs.volumes[-3:])
            base = mean(obs.volumes) or 1.0
            vol_factor = clamp(recent / base, 0.0, 3.0) / 3.0 + 0.5
        momentum = velocity * vol_factor

        # Stability vs fragility.
        fragility = clamp(0.45 * instability + 0.35 * collision + 0.20 * friction)
        robustness = clamp(1.0 - fragility)

        # Advisory vote: unstable + high collision => defensive.
        if fragility >= 0.7:
            vote = AdvisoryVote.AVOID.value
            state = "unstable / high shock-reflection — structurally fragile"
        elif momentum > 0 and friction < 0.5 and instability < 0.5:
            vote = AdvisoryVote.WATCH.value
            state = "positive momentum through low friction — coiled but stable"
        else:
            vote = AdvisoryVote.WAIT.value
            state = "mixed dynamics — no clean force/friction alignment"

        confidence = clamp(0.55 * robustness + 0.25 * (1.0 - instability) + 0.2 * min(1.0, len(rets) / 20.0))
        uncertainty = clamp(0.5 * instability + 0.3 * friction + 0.2 * (1.0 - min(1.0, len(rets) / 20.0)))

        # PhET counterfactual: which assumption dominates? Perturb friction & force.
        baseline = robustness
        cf_friction = clamp(1.0 - clamp(0.45 * instability + 0.35 * collision + 0.20 * clamp(friction + 0.3)))
        cf_force = clamp(1.0 - clamp(0.45 * clamp(raw_instab * (1.0 - 0.5 * clamp(friction))) + 0.35 * collision + 0.20 * friction))
        counterfactuals = [
            CounterfactualBranch("phys_friction", "friction", friction, clamp(friction + 0.3),
                                 baseline, cf_friction, round(cf_friction - baseline, 4),
                                 dominant=abs(cf_friction - baseline) >= 0.1),
            CounterfactualBranch("phys_force", "external_force", force, clamp(force + 0.3),
                                 baseline, cf_force, round(cf_force - baseline, 4),
                                 dominant=abs(cf_force - baseline) >= 0.1),
        ]
        dominant = [c.changed_assumption for c in counterfactuals if c.dominant]

        label = EvidenceLabel.PROXY_DERIVED.value if (obs.spread_bps is not None or obs.adv_usd) else EvidenceLabel.SIMULATED_ONLY.value
        # Physics leans on catalysts as external "forces".
        evidence = self._evidence(obs, "market-as-dynamic-system state read", label,
                                  external_keys=self.catalyst_keys(obs))

        tail_warning = ""
        if collision >= 0.6:
            tail_warning = "high correlated shock-reflection: gap/collision risk in a broad sell-off"

        return LensResult(
            lens=self.domain,
            state_interpretation=state,
            scenario_branches=[
                "force overwhelms friction → directional move",
                "friction absorbs force → range-bound",
                "correlated collision → gap regardless of idiosyncratic force",
            ],
            main_risk=("structural instability / collision" if fragility >= 0.5
                       else "friction stalls the thesis"),
            main_opportunity=("momentum through low friction" if momentum > 0 and friction < 0.5
                              else "shock absorption keeps drawdown bounded"),
            advisory_vote=vote,
            confidence=confidence,
            evidence_label=label,
            uncertainty=uncertainty,
            robustness=robustness,
            fragility=fragility,
            regret=clamp(fragility * 0.6),
            exploitability=clamp(collision),
            evidence=evidence,
            freshness_status=obs.freshness_status,
            tail_warning=tail_warning,
            detail={
                "position_price": obs.price,
                "velocity": round(velocity, 6),
                "acceleration": round(acceleration, 6),
                "momentum": round(momentum, 6),
                "friction": round(friction, 4),
                "external_force": round(force, 4),
                "instability": round(instability, 4),
                "collision_reflection": round(collision, 4),
                "dominant_assumptions": dominant,
                "counterfactuals": [c.to_dict() for c in counterfactuals],
            },
        )


__all__ = ["PhysicsLens"]
