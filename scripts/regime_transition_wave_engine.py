"""Regime-transition sprint — temporal economic wave graph + wavefront.

Answers ONE question (reflection §10–15, 41; components 17/24/27):

    Given a shock at an origin node, WHICH nodes does it reach, WHEN does
    it arrive at each, and which nodes have NOT yet absorbed it?

Distinct from ``nbi_value_chain_mapper.py`` (static Event→Ticker exposure
weights) and ``fission_branch_mapper.py`` (branch families): this graph
adds TIME (per-edge lag days), DIRECTIONALITY (demand shocks travel
upstream, supply shocks downstream — reflection failure 6) and
feedback/backwash detection.  Edge evidence discipline is cite-or-drop,
identical to the NBI mapper: an uncited edge transmits nothing.

Pure/deterministic, no network.  Advisory-only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
REAL_MONEY = "PROHIBITED"
OK = "OK"
UNKNOWN = "UNKNOWN"

DEMAND_SHOCK = "DEMAND"     # travels UPSTREAM (customer → supplier)
SUPPLY_SHOCK = "SUPPLY"     # travels DOWNSTREAM (supplier → customer)

# Wavefront states per node.
ABSORBED = "ABSORBED"
ARRIVING = "ARRIVING"
NOT_YET_REACHED = "NOT_YET_REACHED"
UNREACHED = "UNREACHED"     # no causal path from the shock origin

_IMPACT_FLOOR = 0.01
_MAX_HOPS = 6
_MAX_NODE_VISITS = 2        # loop tolerance; enables feedback detection


@dataclass
class WaveEdge:
    """Directed supply-flow edge: ``src`` supplies ``dst``.

    ``exposure`` [0,1] — economic weight of the link.
    ``lag_days`` — transmission delay (temporal graph, reflection §41).
    ``elasticity`` [0,1] — how much of the disturbance survives the hop.
    ``confidence`` [0,1] — evidence confidence in the edge itself.
    ``evidence_ref`` — cite-or-drop: None ⇒ edge transmits nothing.
    """

    src: str
    dst: str
    exposure: float
    lag_days: int
    elasticity: float = 1.0
    confidence: float = 1.0
    evidence_ref: str | None = None


@dataclass
class WaveGraph:
    edges: list[WaveEdge] = field(default_factory=list)

    def _adjacency(self, shock_kind: str) -> dict[str, list[WaveEdge]]:
        """Demand shocks traverse edges upstream (dst→src); supply shocks
        traverse downstream (src→dst)."""
        adj: dict[str, list[WaveEdge]] = {}
        for e in self.edges:
            if not e.evidence_ref:
                continue  # cite-or-drop
            key = e.dst if shock_kind == DEMAND_SHOCK else e.src
            adj.setdefault(key, []).append(e)
        return adj

    def propagate(self, *, origin: str, shock_kind: str,
                  magnitude: float, shock_day: int) -> dict[str, Any]:
        """Breadth-first temporal propagation from the shock origin.

        Returns per-node expected ``arrival_day`` and ``impact`` (product
        of exposure × elasticity × confidence along the strongest path),
        plus any feedback loops encountered (backwash candidates).
        """
        if shock_kind not in (DEMAND_SHOCK, SUPPLY_SHOCK):
            raise ValueError(f"unknown shock kind: {shock_kind}")
        adj = self._adjacency(shock_kind)
        dropped_uncited = sum(1 for e in self.edges if not e.evidence_ref)
        best: dict[str, dict[str, Any]] = {
            origin: {"impact": max(0.0, magnitude), "arrival_day": shock_day,
                     "hops": 0, "path": [origin]}}
        feedback_loops: list[list[str]] = []
        frontier = [origin]
        visits: dict[str, int] = {origin: 1}
        while frontier:
            nxt: list[str] = []
            for node in frontier:
                state = best[node]
                if state["hops"] >= _MAX_HOPS:
                    continue
                for e in adj.get(node, ()):
                    neighbor = e.src if shock_kind == DEMAND_SHOCK else e.dst
                    impact = (state["impact"]
                              * max(0.0, min(1.0, e.exposure))
                              * max(0.0, min(1.0, e.elasticity))
                              * max(0.0, min(1.0, e.confidence)))
                    if impact < _IMPACT_FLOOR:
                        continue
                    if neighbor in state["path"]:
                        loop = state["path"] + [neighbor]
                        if loop not in feedback_loops:
                            feedback_loops.append(loop)
                        continue
                    arrival = state["arrival_day"] + max(0, e.lag_days)
                    prev = best.get(neighbor)
                    if prev is not None and prev["impact"] >= impact:
                        continue
                    if visits.get(neighbor, 0) >= _MAX_NODE_VISITS:
                        continue
                    visits[neighbor] = visits.get(neighbor, 0) + 1
                    best[neighbor] = {"impact": impact, "arrival_day": arrival,
                                      "hops": state["hops"] + 1,
                                      "path": state["path"] + [neighbor]}
                    nxt.append(neighbor)
            frontier = nxt
        nodes = {n: {"impact": round(s["impact"], 6),
                     "arrival_day": s["arrival_day"], "hops": s["hops"],
                     "path": s["path"]}
                 for n, s in best.items()}
        return {"status": OK, "origin": origin, "shock_kind": shock_kind,
                "shock_day": shock_day, "nodes": nodes,
                "feedback_loops": feedback_loops,
                "dropped_uncited_edges": dropped_uncited,
                "safety": {"advisory_status": ADVISORY_STATUS,
                           "real_money": REAL_MONEY}}


def wavefront(propagation: dict[str, Any], *, today: int,
              absorption: dict[str, float] | None = None,
              ) -> dict[str, Any]:
    """Classify every reached node relative to the advancing wavefront.

    ``absorption`` maps node → observed price-absorption fraction [0, 1]
    (from the propagation-gap engine or an operator estimate).  A node
    with no absorption estimate whose arrival day has passed is ARRIVING,
    not silently ABSORBED — unknown ≠ done.
    """
    absorption = absorption or {}
    states: dict[str, dict[str, Any]] = {}
    ahead: list[str] = []
    for node, info in propagation.get("nodes", {}).items():
        if info["arrival_day"] > today:
            state = NOT_YET_REACHED
        else:
            frac = absorption.get(node)
            if frac is None:
                state = ARRIVING
            elif frac >= 0.75:
                state = ABSORBED
            else:
                state = ARRIVING
        states[node] = {**info, "wavefront_state": state,
                        "absorption": absorption.get(node)}
        if state in (NOT_YET_REACHED, ARRIVING) and info["hops"] > 0:
            ahead.append(node)
    ahead.sort(key=lambda n: -states[n]["impact"])
    return {"status": OK, "today": today, "nodes": states,
            "ahead_of_wavefront": ahead}


def backwash_diagnostic(propagation: dict[str, Any]) -> dict[str, Any]:
    """DIAGNOSTIC ONLY — flag endogenous counter-reaction potential.

    A feedback loop returning to the origin (e.g. shortage → capex →
    supply → price normalization, reflection §15) means the initial move
    may reverse; the diagnostic reports the loop and its round-trip lag
    so a human can judge.  Never feeds rankings.
    """
    loops = propagation.get("feedback_loops", [])
    if not loops:
        return {"status": OK, "diagnostic_only": True,
                "backwash_risk": "NONE_DETECTED", "loops": []}
    return {"status": OK, "diagnostic_only": True,
            "backwash_risk": "FEEDBACK_LOOP_PRESENT",
            "loops": loops,
            "note": "initial beneficiaries may suffer from their own "
                    "induced response; human review required"}
