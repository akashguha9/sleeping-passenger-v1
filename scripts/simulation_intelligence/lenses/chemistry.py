"""Chemistry lens — GROMACS + LAMMPS + OpenMM + reaction-network principles.

Treats the candidate as an ensemble of microstates (seeded Monte-Carlo forward
returns) and as a reaction system with catalysts, inhibitors, an activation
barrier, reaction rate, saturation, equilibrium, runaway and decay.

This lens is the natural home for the repo's existing reaction/titration
vocabulary: it emits an ``activation_barrier`` (distance to a resistance level),
a ``reaction_rate`` (momentum vs friction), a ``saturation`` (how much of the
move is already spent) and a ``runaway_risk`` (short-squeeze-style positive
feedback), which the council and the existing signal reactor can consume.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.simulation_intelligence.lenses.base import Lens, clamp, mean, stdev, prov
    from scripts.simulation_intelligence.contracts import (
        LensResult, MarketObservation, AdvisoryVote, EvidenceLabel,
    )
    from scripts.simulation_intelligence.deterministic_rng import (
        DeterministicRNG, convergence_diagnostic,
    )
    from scripts.simulation_intelligence import uncertainty as unc
    from scripts.simulation_intelligence import feature_flags as flags
except ModuleNotFoundError:  # pragma: no cover
    from simulation_intelligence.lenses.base import Lens, clamp, mean, stdev, prov  # type: ignore[no-redef]
    from simulation_intelligence.contracts import (  # type: ignore[no-redef]
        LensResult, MarketObservation, AdvisoryVote, EvidenceLabel,
    )
    from simulation_intelligence.deterministic_rng import (  # type: ignore[no-redef]
        DeterministicRNG, convergence_diagnostic,
    )
    from simulation_intelligence import uncertainty as unc  # type: ignore[no-redef]
    from simulation_intelligence import feature_flags as flags  # type: ignore[no-redef]


class ChemistryLens(Lens):
    domain = "CHEMISTRY"
    name = "chemistry"
    required_fields = ("returns",)

    def _evaluate(self, obs: MarketObservation, request, seed: int) -> LensResult:
        rets = [float(r) for r in obs.returns if r == r]
        drift = mean(rets[-10:]) if rets else 0.0
        sigma = stdev(rets) or (obs.volatility or 0.03)
        sigma = min(0.2, max(0.003, sigma))

        # -- GROMACS/OpenMM ensemble: seeded MC of cumulative 10-day return ----
        n = min(flags.max_runs(), max(64, request.max_runs if request else 256))
        rng = DeterministicRNG(seed, "chemistry/ensemble")
        horizon = 10
        samples = []
        for _ in range(n):
            cum = 0.0
            for _ in range(horizon):
                cum += rng.student_t(df=4.0, mu=drift, sigma=sigma)
            samples.append(cum)
        conv = convergence_diagnostic(samples)
        band = unc.summarize(samples, convergence="CONVERGED" if conv["converged"] else "NOT_CONVERGED")
        modes = unc.metastable_states(samples)

        # -- Reaction-network read --------------------------------------------
        # Catalysts (positive) vs inhibitors (negative) among declared catalysts.
        catalyst = 0.0
        inhibitor = 0.0
        for c in obs.catalysts:
            try:
                m = float(c.get("magnitude", c.get("strength", 0.0)))
            except (TypeError, ValueError):
                m = 0.0
            if m >= 0:
                catalyst += m
            else:
                inhibitor += -m
        catalyst = clamp(catalyst)
        inhibitor = clamp(inhibitor)

        # Activation barrier: normalized distance to nearest resistance proxy.
        # Without a level we use dispersion as the barrier height.
        activation_barrier = clamp(band.dispersion / (abs(drift) * horizon + band.dispersion + 1e-6))

        # Reaction rate: how fast the system is moving = |drift| vs friction.
        spread = obs.spread_bps if obs.spread_bps is not None else 25.0
        friction = clamp(spread / 100.0)
        reaction_rate = clamp(abs(drift) / (sigma + 1e-6) * (1.0 - 0.5 * friction))

        # Saturation: how much of a plausible move is already spent (mean/tail).
        saturation = clamp(abs(band.central) / (abs(band.tail_high - band.tail_low) + 1e-6))

        # Runaway (positive feedback / squeeze): strong drift + rising vol.
        runaway_risk = clamp(0.6 * clamp(drift / (sigma + 1e-6)) + 0.4 * min(1.0, sigma / 0.05)) if drift > 0 else 0.0

        # Decay / half-life: negative drift persistence.
        decay = clamp(-drift / (sigma + 1e-6)) if drift < 0 else 0.0
        half_life_days = round(0.693 / max(1e-3, decay), 2) if decay > 0 else None

        # Equilibrium vs reactive.
        reversibility = clamp(1.0 - reaction_rate)
        is_equilibrium = reaction_rate < 0.25 and activation_barrier > 0.5

        # -- State + vote ------------------------------------------------------
        multimodal = len(modes) >= 2
        if runaway_risk >= 0.6:
            state = "runaway reaction — positive feedback (squeeze-like), unstable"
            vote = AdvisoryVote.AVOID.value
        elif decay >= 0.5:
            state = "decaying reaction — thesis energy dissipating"
            vote = AdvisoryVote.AVOID.value
        elif catalyst > inhibitor and activation_barrier < 0.5 and reaction_rate > 0.3:
            state = "pre-activation with net catalyst — reaction-ready"
            vote = AdvisoryVote.WATCH.value
        elif is_equilibrium:
            state = "metastable equilibrium — high activation barrier, low rate"
            vote = AdvisoryVote.WAIT.value
        else:
            state = "competing reactions — no dominant pathway"
            vote = AdvisoryVote.WAIT.value

        fragility = clamp(0.4 * runaway_risk + 0.3 * decay + 0.3 * (1.0 if multimodal else 0.0))
        robustness = clamp(1.0 - fragility)
        confidence = clamp(0.5 * (1.0 if conv["converged"] else 0.4) + 0.3 * robustness + 0.2 * min(1.0, len(rets) / 20.0))
        uncertainty = clamp(0.4 * (0.0 if conv["converged"] else 1.0) + 0.3 * activation_barrier + 0.3 * (1.0 if multimodal else 0.0))

        label = EvidenceLabel.SIMULATED_ONLY.value
        # Chemistry leans on catalysts (catalyst/inhibitor terms).
        evidence = self._evidence(obs, "ensemble + reaction-network read", label,
                                  external_keys=self.catalyst_keys(obs))

        tail_warning = ""
        if band.tail_low <= -0.25:
            tail_warning = f"ensemble tail {band.tail_low:.0%} breaches ruin threshold"

        return LensResult(
            lens=self.domain,
            state_interpretation=state,
            scenario_branches=[
                "catalyst overcomes activation barrier → reaction proceeds",
                "inhibitor dominates → reaction stalls at equilibrium",
                "positive feedback → runaway (unstable, mean-reverting after)",
            ],
            main_risk=("runaway / squeeze reversal" if runaway_risk >= 0.5 else
                       "energy decay before activation" if decay >= 0.4 else
                       "multimodal regime ambiguity" if multimodal else "reaction stalls at the barrier"),
            main_opportunity=("net catalyst below a low activation barrier" if catalyst > inhibitor else
                              "reversible / mean-reverting setup"),
            advisory_vote=vote,
            confidence=confidence,
            evidence_label=label,
            uncertainty=uncertainty,
            robustness=robustness,
            fragility=fragility,
            regret=clamp(0.5 * runaway_risk + 0.5 * decay),
            exploitability=clamp(runaway_risk),
            evidence=evidence,
            freshness_status=obs.freshness_status,
            tail_warning=tail_warning,
            detail={
                "ensemble": band.to_dict(),
                "metastable_modes": modes,
                "catalyst": round(catalyst, 4),
                "inhibitor": round(inhibitor, 4),
                "activation_barrier": round(activation_barrier, 4),
                "reaction_rate": round(reaction_rate, 4),
                "saturation": round(saturation, 4),
                "reversibility": round(reversibility, 4),
                "runaway_risk": round(runaway_risk, 4),
                "decay": round(decay, 4),
                "half_life_days": half_life_days,
                "equilibrium": is_equilibrium,
                "converged": conv["converged"],
                "n_samples": band.n_samples,
            },
        )


__all__ = ["ChemistryLens"]
