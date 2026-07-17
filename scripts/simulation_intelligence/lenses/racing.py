"""Racing lens — iRacing + rFactor 2 + EA F1 operational principles.

Transplants racing's strongest OPERATIONAL ideas into advisory market concepts
(no racing terminology reaches the investor-facing output):

* telemetry     ← every state transition / gate / warning recorded
* degradation   ← thesis "tyre wear": edge decays with time & regime change
* pit window    ← optimal *timing* band for the human to act (or step back)
* undercut/overcut ← acting earlier vs later than consensus
* safety-car    ← volatility-regime pause (reduce risk budget)
* red-flag      ← hard stop (maps to RISK_BLOCK precondition)
* driver-error allowance ← margin for operator mistakes

Output is advisory *timing*: WATCH / WAIT / AVOID, with a "cost of waiting"
estimate and a degradation curve.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.simulation_intelligence.lenses.base import Lens, clamp, mean, stdev, prov
    from scripts.simulation_intelligence.contracts import (
        LensResult, MarketObservation, AdvisoryVote, EvidenceLabel,
    )
except ModuleNotFoundError:  # pragma: no cover
    from simulation_intelligence.lenses.base import Lens, clamp, mean, stdev, prov  # type: ignore[no-redef]
    from simulation_intelligence.contracts import (  # type: ignore[no-redef]
        LensResult, MarketObservation, AdvisoryVote, EvidenceLabel,
    )


class RacingLens(Lens):
    domain = "RACING"
    name = "racing"
    required_fields = ("returns",)

    def _evaluate(self, obs: MarketObservation, request, seed: int) -> LensResult:
        rets = [float(r) for r in obs.returns if r == r]
        drift = mean(rets[-5:]) if rets else 0.0
        vol = stdev(rets) or (obs.volatility or 0.03)
        vol_early = stdev(rets[:len(rets) // 2]) if len(rets) >= 6 else vol
        vol_late = stdev(rets[len(rets) // 2:]) if len(rets) >= 6 else vol

        # -- Track conditions (rFactor 2): regime evolution -------------------
        vol_regime_change = clamp((vol_late - vol_early) / (vol_early + 1e-6), -1.0, 1.0)
        news_accumulation = clamp(max(obs.source_count, len(obs.narrative_sources)) / 8.0)
        # "Grip" = confidence in the track: high when vol stable and liquid.
        spread = obs.spread_bps if obs.spread_bps is not None else 25.0
        friction = clamp(spread / 100.0)
        grip = clamp(1.0 - 0.5 * clamp(abs(vol_regime_change)) - 0.5 * friction)

        # -- Tyre degradation: the edge decays with time & regime change ------
        # Fresh edge from |drift|/vol; degrades with regime change + saturation.
        fresh_edge = clamp(abs(drift) / (vol + 1e-6))
        degradation_rate = clamp(0.5 * clamp(abs(vol_regime_change)) + 0.5 * news_accumulation)
        remaining_edge = clamp(fresh_edge * (1.0 - degradation_rate))

        # -- Pit window: is now inside the optimal action band? ---------------
        # Window opens when edge is fresh and grip is high; closes as it degrades.
        window_open = remaining_edge > 0.3 and grip > 0.5 and degradation_rate < 0.6
        # Cost of waiting = edge you lose per period if you delay.
        cost_of_waiting = round(fresh_edge * degradation_rate, 4)

        # -- Safety-car / red-flag conditions ---------------------------------
        safety_car = vol_regime_change > 0.5  # vol spiking → reduce risk budget
        red_flag = (obs.freshness_status.upper() == "STALE") or bool(obs.missing_fields)

        # -- Undercut/overcut analysis ----------------------------------------
        # Undercut (act early) favoured when edge fresh & degrading fast.
        undercut_favoured = fresh_edge > 0.4 and degradation_rate > 0.4
        # Overcut (wait) favoured when grip low now but stabilizing.
        overcut_favoured = grip < 0.5 and vol_regime_change < 0

        if red_flag:
            state = "red-flag: data integrity stop — do not act on this telemetry"
            vote = AdvisoryVote.AVOID.value
        elif safety_car:
            state = "safety-car: volatility regime spiking — reduce risk budget, hold"
            vote = AdvisoryVote.WAIT.value
        elif window_open and undercut_favoured:
            state = "action window open, edge degrading — earlier action favoured"
            vote = AdvisoryVote.WATCH.value
        elif window_open:
            state = "action window open with stable grip"
            vote = AdvisoryVote.WATCH.value
        elif remaining_edge < 0.2:
            state = "edge fully degraded — window closed"
            vote = AdvisoryVote.AVOID.value
        else:
            state = "between windows — wait for grip to improve"
            vote = AdvisoryVote.WAIT.value

        fragility = clamp(0.5 * degradation_rate + 0.5 * clamp(abs(vol_regime_change)))
        robustness = clamp(grip * (1.0 - degradation_rate))
        confidence = clamp(0.4 * grip + 0.3 * remaining_edge + 0.3 * min(1.0, len(rets) / 20.0))
        uncertainty = clamp(0.5 * clamp(abs(vol_regime_change)) + 0.5 * (1.0 - grip))

        label = EvidenceLabel.PROXY_DERIVED.value
        # Racing leans on narrative accumulation (news as track conditions).
        evidence = self._evidence(obs, "decision-telemetry + degradation read", label,
                                  external_keys=self.narrative_keys(obs))

        tail_warning = ""
        if safety_car:
            tail_warning = "volatility-regime spike: correlated risk elevated across the grid"

        return LensResult(
            lens=self.domain,
            state_interpretation=state,
            scenario_branches=[
                "act inside the window → capture remaining edge",
                "wait through the safety-car → lower risk, lower edge",
                "window closes (full degradation) → opportunity gone",
            ],
            main_risk=("regime change mid-thesis (safety-car)" if safety_car else
                       "edge degradation before action"),
            main_opportunity=("open action window with fresh edge" if window_open else
                              "grip recovery after the regime settles"),
            advisory_vote=vote,
            confidence=confidence,
            evidence_label=label,
            uncertainty=uncertainty,
            robustness=robustness,
            fragility=fragility,
            regret=clamp(cost_of_waiting + 0.3 * fragility),
            exploitability=clamp(degradation_rate),
            evidence=evidence,
            freshness_status=obs.freshness_status,
            tail_warning=tail_warning,
            detail={
                "grip_confidence": round(grip, 4),
                "vol_regime_change": round(vol_regime_change, 4),
                "news_accumulation": round(news_accumulation, 4),
                "fresh_edge": round(fresh_edge, 4),
                "degradation_rate": round(degradation_rate, 4),
                "remaining_edge": round(remaining_edge, 4),
                "action_window_open": window_open,
                "cost_of_waiting": cost_of_waiting,
                "safety_car": safety_car,
                "red_flag": red_flag,
                "undercut_favoured": undercut_favoured,
                "overcut_favoured": overcut_favoured,
            },
        )


__all__ = ["RacingLens"]
