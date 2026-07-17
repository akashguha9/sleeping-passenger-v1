"""Poker lens — GTO Wizard + PioSOLVER + MonkerSolver principles (original code).

Imperfect-information, game-theory reasoning about the candidate:

* equilibrium baseline (GTO): classify the recommended action as ROBUST /
  ASSUMPTION_DEPENDENT / EXPLOITATIVE / OVERFIT / DOMINATED / NO_ACTION_EDGE
* bounded decision tree + counterfactual regret (Pio): for each candidate
  action estimate EV, downside, opportunity cost, max regret, counterfactual
  regret, tail regret, information value and the value of waiting
* multi-agent (Monker): model many actors (company, competitors, regulators,
  customers, suppliers, investors, short sellers, macro, governments, index
  flows) — not a simplistic bull-vs-bear game
* exploitability: how easily the recommendation fails if ONE major assumption
  or opposing actor behaves differently

Original CFR-style math; no proprietary solver is used or imitated.
"""
from __future__ import annotations

import math
from typing import Any

try:
    from scripts.simulation_intelligence.lenses.base import Lens, clamp, mean, stdev, prov
    from scripts.simulation_intelligence.contracts import (
        LensResult, MarketObservation, AdvisoryVote, EvidenceLabel,
    )
    from scripts.simulation_intelligence.deterministic_rng import DeterministicRNG
except ModuleNotFoundError:  # pragma: no cover
    from simulation_intelligence.lenses.base import Lens, clamp, mean, stdev, prov  # type: ignore[no-redef]
    from simulation_intelligence.contracts import (  # type: ignore[no-redef]
        LensResult, MarketObservation, AdvisoryVote, EvidenceLabel,
    )
    from simulation_intelligence.deterministic_rng import DeterministicRNG  # type: ignore[no-redef]

# Advisory "actions" the poker tree evaluates (timing/attention stances).
_ACTIONS = (
    AdvisoryVote.WATCH.value, AdvisoryVote.WAIT.value, AdvisoryVote.AVOID.value,
)

# Multi-agent actors (Monker): each can push the outcome + or -.
_ACTORS = (
    "company", "competitors", "regulators", "customers", "suppliers",
    "investors", "short_sellers", "macro", "governments", "index_flows",
)


def _action_payoff(action: str, outcome: float) -> float:
    """Payoff of an advisory stance given a realized outcome (return)."""
    exposure = {
        AdvisoryVote.WATCH.value: 0.6,
        AdvisoryVote.WAIT.value: 0.1,
        AdvisoryVote.AVOID.value: 0.0,
    }.get(action, 0.1)
    # Asymmetric: WAIT/AVOID also avoid downside; WATCH captures upside + downside.
    return exposure * outcome


class PokerLens(Lens):
    domain = "POKER"
    name = "poker"
    required_fields = ("returns",)

    def _actor_pressures(self, obs: MarketObservation, drift: float, vol: float) -> dict[str, float]:
        """Signed pressure each actor exerts on the outcome (bounded -1..1).

        Inferred from public proxies only — never claims to know actor intent.
        """
        n_sources = max(obs.source_count, len(obs.narrative_sources))
        catalysts = sum(1 for c in obs.catalysts)
        return {
            "company": clamp(drift / (vol + 1e-6), -1, 1) * 0.5,
            "competitors": -0.2 * clamp(vol / 0.05),
            "regulators": -0.3 if any("reg" in str(c).lower() for c in obs.catalysts) else -0.05,
            "customers": clamp(drift / (vol + 1e-6), -1, 1) * 0.3,
            "suppliers": -0.1 * clamp(vol / 0.05),
            "investors": clamp(0.2 * min(1.0, n_sources / 6.0), -1, 1),
            "short_sellers": -0.4 * clamp(vol / 0.06),
            "macro": clamp(-0.2 * clamp(vol / 0.05), -1, 1),
            "governments": -0.1,
            "index_flows": clamp(0.15 * catalysts, -1, 1),
        }

    def _cfr(self, drift: float, vol: float, seed: int) -> dict[str, Any]:
        """Bounded counterfactual-regret estimate over the action set.

        Samples outcome scenarios, computes each action's EV and the regret vs
        the best action per scenario (counterfactual regret), then averages.
        """
        rng = DeterministicRNG(seed, "poker/cfr")
        n = 400
        scenarios = [rng.student_t(df=4.0, mu=drift, sigma=max(0.005, vol)) for _ in range(n)]
        ev = {a: 0.0 for a in _ACTIONS}
        downside = {a: 0.0 for a in _ACTIONS}
        regret = {a: 0.0 for a in _ACTIONS}
        tail_regret = {a: 0.0 for a in _ACTIONS}
        sorted_sc = sorted(scenarios)
        tail_cut = sorted_sc[max(0, int(0.05 * n))]  # 5th percentile
        for outcome in scenarios:
            payoffs = {a: _action_payoff(a, outcome) for a in _ACTIONS}
            best = max(payoffs.values())
            for a in _ACTIONS:
                ev[a] += payoffs[a]
                if payoffs[a] < 0:
                    downside[a] += payoffs[a]
                regret[a] += (best - payoffs[a])  # counterfactual regret
                if outcome <= tail_cut:
                    tail_regret[a] += (best - payoffs[a])
        for a in _ACTIONS:
            ev[a] = round(ev[a] / n, 6)
            downside[a] = round(downside[a] / n, 6)
            regret[a] = round(regret[a] / n, 6)
            tail_regret[a] = round(tail_regret[a] / max(1, int(0.05 * n)), 6)
        return {"ev": ev, "downside": downside, "regret": regret, "tail_regret": tail_regret}

    def _evaluate(self, obs: MarketObservation, request, seed: int) -> LensResult:
        rets = [float(r) for r in obs.returns if r == r]
        drift = mean(rets[-10:]) if rets else 0.0
        vol = stdev(rets) or (obs.volatility or 0.03)
        vol = min(0.25, max(0.005, vol))

        cfr = self._cfr(drift, vol, seed)
        ev, regret, tail_regret = cfr["ev"], cfr["regret"], cfr["tail_regret"]

        # Choose the minimum-regret action (Pio-style).
        best_action = min(regret, key=regret.get)
        max_regret = max(regret.values())
        min_regret = regret[best_action]

        # Opportunity cost & value of waiting.
        opportunity_cost = round(ev[AdvisoryVote.WATCH.value] - ev[best_action], 6)
        value_of_waiting = round(ev[AdvisoryVote.WAIT.value] - ev[AdvisoryVote.WATCH.value], 6)
        # Information value: how much a converged view would reduce regret spread.
        information_value = round(max_regret - min_regret, 6)

        # -- Multi-agent + exploitability (Monker) ----------------------------
        pressures = self._actor_pressures(obs, drift, vol)
        net_pressure = sum(pressures.values())
        # Exploitability: flip the single most-negative actor's assumption and
        # see how much the recommended action's EV degrades.
        worst_actor = min(pressures, key=pressures.get)
        stressed_drift = drift + pressures[worst_actor] * vol  # actor deviates adversely
        stressed_ev = _action_payoff(best_action, stressed_drift)
        base_ev = ev[best_action]
        exploitability = clamp(abs(base_ev - stressed_ev) / (abs(base_ev) + 1e-6), 0.0, 1.0)

        # -- GTO equilibrium classification -----------------------------------
        ev_spread = max(ev.values()) - min(ev.values())
        if ev_spread < 1e-4:
            equilibrium_class = "NO_ACTION_EDGE"
        elif exploitability >= 0.6:
            equilibrium_class = "ASSUMPTION_DEPENDENT"
        elif information_value < 0.01 and max_regret < 0.01:
            equilibrium_class = "ROBUST"
        elif best_action == AdvisoryVote.WATCH.value and net_pressure < 0:
            equilibrium_class = "EXPLOITATIVE"
        elif ev[best_action] < min(ev.values()) + 1e-6:
            equilibrium_class = "DOMINATED"
        else:
            equilibrium_class = "ASSUMPTION_DEPENDENT"

        # -- Vote --------------------------------------------------------------
        if equilibrium_class == "NO_ACTION_EDGE":
            vote = AdvisoryVote.WAIT.value
        elif exploitability >= 0.7:
            vote = AdvisoryVote.AVOID.value
        else:
            vote = best_action

        fragility = clamp(0.6 * exploitability + 0.4 * clamp(information_value / 0.05))
        robustness = clamp(1.0 - fragility)
        confidence = clamp(0.4 * (1.0 - exploitability) + 0.3 * robustness + 0.3 * min(1.0, len(rets) / 20.0))
        uncertainty = clamp(0.5 * exploitability + 0.5 * clamp(information_value / 0.05))

        label = EvidenceLabel.MODEL_INFERRED.value
        # Poker leans on catalysts (regulatory / actor pressures).
        evidence = self._evidence(obs, f"equilibrium={equilibrium_class}, action={vote}", label,
                                  external_keys=self.catalyst_keys(obs))

        tail_warning = ""
        if max(tail_regret.values()) >= 0.05:
            tail_warning = "high tail regret: recommended stance suffers badly in the worst 5% of outcomes"

        return LensResult(
            lens=self.domain,
            state_interpretation=f"equilibrium classification: {equilibrium_class} → {vote}",
            scenario_branches=[f"{a}: EV {ev[a]:+.4f}, regret {regret[a]:.4f}" for a in _ACTIONS],
            main_risk=(f"exploitable by {worst_actor} deviation" if exploitability >= 0.4
                       else "opportunity cost of waiting"),
            main_opportunity=("low-regret robust stance" if equilibrium_class == "ROBUST"
                              else "information value from waiting for confirmation"),
            advisory_vote=vote,
            confidence=confidence,
            evidence_label=label,
            uncertainty=uncertainty,
            robustness=robustness,
            fragility=fragility,
            regret=clamp(max_regret / 0.1),
            exploitability=exploitability,
            evidence=evidence,
            freshness_status=obs.freshness_status,
            tail_warning=tail_warning,
            detail={
                "equilibrium_class": equilibrium_class,
                "ev": ev,
                "regret": regret,
                "tail_regret": tail_regret,
                "max_regret": round(max_regret, 6),
                "opportunity_cost": opportunity_cost,
                "value_of_waiting": value_of_waiting,
                "information_value": information_value,
                "actor_pressures": {k: round(v, 4) for k, v in pressures.items()},
                "net_pressure": round(net_pressure, 4),
                "most_adverse_actor": worst_actor,
                "exploitability": round(exploitability, 4),
            },
        )


__all__ = ["PokerLens"]
