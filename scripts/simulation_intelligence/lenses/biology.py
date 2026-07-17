"""Biology lens — PhysiCell + BioDynaMo + COPASI principles (original code).

Models a heterogeneous population of market participants (via LAWFUL PUBLIC-DATA
PROXIES ONLY — never identifying real actors) and the feedback network among
narratives.  Classifies the thesis lifecycle:
EMERGING / GROWING / STABLE / SATURATED / ADAPTING / DECAYING / COLLAPSING.

Participant cohorts (proxied, not identified):
long-term investors, short-term traders, passive funds, market makers,
retail participants, institutional allocators, short sellers, analysts,
narrative amplifiers.  Cohort *weights* are inferred from volume/volatility/
source-mix proxies; the lens never claims to know who is actually trading.

If ``SIL_COPASI_ENABLED`` is set and copasi-basico is importable, the feedback
network can be integrated with the COPASI ODE solver via the adapter; otherwise
the native logistic/feedback model is used (default path).
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.simulation_intelligence.lenses.base import Lens, clamp, mean, stdev, prov
    from scripts.simulation_intelligence.contracts import (
        LensResult, MarketObservation, AdvisoryVote, EvidenceLabel, ThesisLifecycle,
    )
    from scripts.simulation_intelligence import feature_flags as flags
except ModuleNotFoundError:  # pragma: no cover
    from simulation_intelligence.lenses.base import Lens, clamp, mean, stdev, prov  # type: ignore[no-redef]
    from simulation_intelligence.contracts import (  # type: ignore[no-redef]
        LensResult, MarketObservation, AdvisoryVote, EvidenceLabel, ThesisLifecycle,
    )
    from simulation_intelligence import feature_flags as flags  # type: ignore[no-redef]


_COHORTS = (
    "long_term_investors", "short_term_traders", "passive_funds", "market_makers",
    "retail_participants", "institutional_allocators", "short_sellers", "analysts",
    "narrative_amplifiers",
)


class BiologyLens(Lens):
    domain = "BIOLOGY"
    name = "biology"
    required_fields = ("returns",)

    def _cohort_weights(self, obs: MarketObservation) -> dict[str, float]:
        """Infer cohort mix from proxies. Sums to ~1. Never identifies actors."""
        rets = [float(r) for r in obs.returns if r == r]
        vol = stdev(rets) or (obs.volatility or 0.03)
        turnover = 1.0
        if obs.volumes and len(obs.volumes) >= 2:
            turnover = clamp(mean(obs.volumes[-3:]) / (mean(obs.volumes) or 1.0), 0.0, 3.0)
        n_sources = max(obs.source_count, len(obs.narrative_sources))

        # Proxy heuristics (bounded, transparent):
        short_term = clamp(0.3 + 0.4 * min(1.0, vol / 0.05) + 0.2 * (turnover - 1.0))
        retail = clamp(0.2 + 0.3 * min(1.0, n_sources / 8.0))
        amplifiers = clamp(0.1 + 0.4 * min(1.0, n_sources / 6.0))
        passive = clamp(0.15 + 0.1 * (1.0 - min(1.0, vol / 0.05)))
        raw = {
            "long_term_investors": clamp(1.0 - short_term),
            "short_term_traders": short_term,
            "passive_funds": passive,
            "market_makers": clamp(0.1 + 0.2 * min(1.0, vol / 0.05)),
            "retail_participants": retail,
            "institutional_allocators": clamp(0.2 + 0.2 * (1.0 - min(1.0, vol / 0.05))),
            "short_sellers": clamp(0.05 + 0.3 * min(1.0, vol / 0.06)),
            "analysts": clamp(0.1 + 0.2 * min(1.0, n_sources / 10.0)),
            "narrative_amplifiers": amplifiers,
        }
        total = sum(raw.values()) or 1.0
        return {k: round(v / total, 4) for k, v in raw.items()}

    def _evaluate(self, obs: MarketObservation, request, seed: int) -> LensResult:
        rets = [float(r) for r in obs.returns if r == r]
        drift = mean(rets[-10:]) if rets else 0.0
        early = mean(rets[:5]) if len(rets) >= 10 else drift
        late = mean(rets[-5:]) if len(rets) >= 5 else drift
        vol = stdev(rets) or (obs.volatility or 0.03)

        cohorts = self._cohort_weights(obs)
        crowding = clamp(cohorts["short_term_traders"] + cohorts["narrative_amplifiers"])
        n_sources = max(obs.source_count, len(obs.narrative_sources))

        # -- Contagion / narrative spread (BioDynaMo) -------------------------
        # Logistic growth toward a carrying capacity (source saturation).
        carrying_capacity = 12.0
        spread_ratio = clamp(n_sources / carrying_capacity)
        # Growth momentum: is attention still rising (late vs early)?
        attention_growth = late - early

        # -- Feedback network (COPASI): positive vs negative feedback ---------
        positive_feedback = clamp(0.5 * clamp(attention_growth / (vol + 1e-6)) + 0.5 * crowding)
        negative_feedback = clamp(0.5 * spread_ratio + 0.5 * (1.0 - crowding))  # saturation resists
        homeostasis = clamp(1.0 - abs(positive_feedback - negative_feedback))

        # -- COPASI optional native accelerator (feedback ODE) ----------------
        copasi_used = False
        copasi_note = "native feedback model"
        if flags.copasi_enabled():
            try:
                from scripts.simulation_intelligence.adapters.copasi_adapter import (
                    solve_feedback_equilibrium,
                )
            except ModuleNotFoundError:  # pragma: no cover
                try:
                    from simulation_intelligence.adapters.copasi_adapter import (  # type: ignore[no-redef]
                        solve_feedback_equilibrium,
                    )
                except ModuleNotFoundError:
                    solve_feedback_equilibrium = None  # type: ignore[assignment]
            if solve_feedback_equilibrium is not None:
                res = solve_feedback_equilibrium(positive_feedback, negative_feedback)
                if res.get("available"):
                    homeostasis = clamp(res.get("equilibrium", homeostasis))
                    copasi_used = True
                    copasi_note = "COPASI ODE feedback equilibrium"

        # -- Lifecycle classification -----------------------------------------
        if spread_ratio < 0.25 and attention_growth > 0:
            lifecycle = ThesisLifecycle.EMERGING.value
        elif attention_growth > 0 and spread_ratio < 0.7:
            lifecycle = ThesisLifecycle.GROWING.value
        elif spread_ratio >= 0.7 and abs(attention_growth) < vol:
            lifecycle = ThesisLifecycle.SATURATED.value
        elif drift < 0 and late < early and spread_ratio >= 0.6:
            lifecycle = ThesisLifecycle.COLLAPSING.value
        elif drift < 0 and late < early:
            lifecycle = ThesisLifecycle.DECAYING.value
        elif abs(attention_growth) < vol and homeostasis > 0.6:
            lifecycle = ThesisLifecycle.STABLE.value
        else:
            lifecycle = ThesisLifecycle.ADAPTING.value

        # -- Vote --------------------------------------------------------------
        if lifecycle in (ThesisLifecycle.COLLAPSING.value, ThesisLifecycle.DECAYING.value):
            vote = AdvisoryVote.AVOID.value
        elif lifecycle == ThesisLifecycle.SATURATED.value:
            vote = AdvisoryVote.WAIT.value
        elif lifecycle in (ThesisLifecycle.EMERGING.value, ThesisLifecycle.GROWING.value):
            vote = AdvisoryVote.WATCH.value
        else:
            vote = AdvisoryVote.WAIT.value

        fragility = clamp(0.5 * crowding + 0.5 * spread_ratio)  # crowded + saturated = fragile
        robustness = clamp(homeostasis * (1.0 - 0.5 * crowding))
        confidence = clamp(0.4 * min(1.0, n_sources / 6.0) + 0.3 * robustness + 0.3 * min(1.0, len(rets) / 20.0))
        uncertainty = clamp(0.4 * (1.0 - min(1.0, n_sources / 6.0)) + 0.3 * crowding + 0.3 * (1.0 - homeostasis))

        label = EvidenceLabel.PROXY_DERIVED.value
        # Biology leans on narrative sources (contagion / cohort proxies).
        evidence = self._evidence(obs, f"participant-ecosystem + lifecycle={lifecycle}", label,
                                  external_keys=self.narrative_keys(obs))

        tail_warning = ""
        if crowding >= 0.6 and lifecycle in (ThesisLifecycle.SATURATED.value, ThesisLifecycle.COLLAPSING.value):
            tail_warning = "crowded + saturated: reflexive unwind risk if narrative reverses"

        missing = []
        if n_sources == 0:
            missing.append("no narrative sources: cohort mix is a weak proxy")

        return LensResult(
            lens=self.domain,
            state_interpretation=f"thesis lifecycle: {lifecycle} (crowding {crowding:.2f})",
            scenario_branches=[
                "narrative keeps spreading below carrying capacity → growth",
                "saturation + crowding → reflexive unwind",
                "homeostatic negative feedback → stabilization",
            ],
            main_risk=("reflexive crowded unwind" if crowding >= 0.5 else "attention decay"),
            main_opportunity=("emerging narrative below carrying capacity" if lifecycle in
                              (ThesisLifecycle.EMERGING.value, ThesisLifecycle.GROWING.value)
                              else "stable homeostasis"),
            advisory_vote=vote,
            confidence=confidence,
            evidence_label=label,
            uncertainty=uncertainty,
            robustness=robustness,
            fragility=fragility,
            regret=clamp(fragility * 0.6),
            exploitability=clamp(crowding),
            evidence=evidence,
            missing_data_warnings=missing,
            freshness_status=obs.freshness_status,
            tail_warning=tail_warning,
            detail={
                "lifecycle": lifecycle,
                "cohort_weights": cohorts,
                "crowding": round(crowding, 4),
                "attention_growth": round(attention_growth, 6),
                "spread_ratio": round(spread_ratio, 4),
                "carrying_capacity_sources": carrying_capacity,
                "positive_feedback": round(positive_feedback, 4),
                "negative_feedback": round(negative_feedback, 4),
                "homeostasis": round(homeostasis, 4),
                "copasi_used": copasi_used,
                "feedback_engine": copasi_note,
            },
        )


__all__ = ["BiologyLens"]
