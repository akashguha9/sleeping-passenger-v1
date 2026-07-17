"""Sparse dependency graph + bounded shock propagation (Project Chrono lens).

Models the candidate as one node in a multi-body system of company / sector /
index / suppliers / customers / competitors / commodities / rates / currencies
/ geopolitical nodes, and propagates a shock through the graph with distance
damping.

Design constraints (LAMMPS lens — avoid O(n²)):
* adjacency lists, not a dense matrix
* BFS with a bounded hop radius and per-hop damping
* a hard cap on node/edge counts

Pure module: no numpy required, no I/O.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

_MAX_NODES = 512
_MAX_HOPS = 4


@dataclass(slots=True)
class DependencyEdge:
    src: str
    dst: str
    weight: float  # 0..1 transmission strength
    kind: str = "generic"


@dataclass(slots=True)
class DependencyGraph:
    nodes: set[str] = field(default_factory=set)
    adj: dict[str, list[DependencyEdge]] = field(default_factory=dict)

    def add_edge(self, src: str, dst: str, weight: float, kind: str = "generic") -> None:
        if len(self.nodes) >= _MAX_NODES:
            return
        w = max(0.0, min(1.0, float(weight)))
        self.nodes.add(src)
        self.nodes.add(dst)
        self.adj.setdefault(src, []).append(DependencyEdge(src, dst, w, kind))
        # Shocks propagate both ways (a supplier hit reflects onto the customer)
        # but with the same edge weight; we add the reverse for undirected reach.
        self.adj.setdefault(dst, []).append(DependencyEdge(dst, src, w, kind))

    def propagate(
        self,
        origin: str,
        magnitude: float,
        damping: float = 0.55,
        max_hops: int = _MAX_HOPS,
    ) -> dict[str, float]:
        """BFS shock propagation with per-hop damping.

        Returns a map node -> received shock magnitude.  Each hop multiplies by
        ``damping * edge_weight``; a node keeps the *strongest* path it receives
        (max, not sum) so cycles cannot amplify without bound.
        """
        if origin not in self.nodes:
            return {origin: float(magnitude)}
        received: dict[str, float] = {origin: abs(float(magnitude))}
        # (node, magnitude, hop)
        q: deque[tuple[str, float, int]] = deque([(origin, abs(float(magnitude)), 0)])
        max_hops = max(1, min(int(max_hops), _MAX_HOPS))
        while q:
            node, mag, hop = q.popleft()
            if hop >= max_hops:
                continue
            for edge in self.adj.get(node, []):
                transmitted = mag * damping * edge.weight
                if transmitted < 1e-4:
                    continue
                prev = received.get(edge.dst, 0.0)
                if transmitted > prev:
                    received[edge.dst] = transmitted
                    q.append((edge.dst, transmitted, hop + 1))
        return {k: round(v, 6) for k, v in received.items()}

    def systemic_fragility(self, origin: str, magnitude: float = 1.0) -> float:
        """Fraction of graph 'energy' that reflects back toward the origin.

        High values => the candidate sits in a tightly-coupled cluster where a
        shock echoes back (collision/contagion risk).  Bounded 0..1.
        """
        reach = self.propagate(origin, magnitude)
        if len(reach) <= 1:
            return 0.0
        total = sum(reach.values())
        neighbours = total - reach.get(origin, 0.0)
        return round(min(1.0, neighbours / (total + 1e-9)), 4)


def build_default_graph(
    ticker: str,
    sector: str = "",
    dependencies: list[dict[str, Any]] | None = None,
) -> DependencyGraph:
    """Build a small canonical dependency graph around a candidate.

    Uses caller-supplied dependencies when present; otherwise a minimal
    sector/index/macro skeleton so the lens always has *some* structure without
    inventing specific counterparties.
    """
    g = DependencyGraph()
    t = ticker.upper().strip() or "CANDIDATE"
    sec = (sector or "SECTOR").upper().strip() or "SECTOR"
    # Skeleton: candidate -> sector -> index; candidate -> macro nodes.
    g.add_edge(t, f"SECTOR::{sec}", 0.7, "sector")
    g.add_edge(f"SECTOR::{sec}", "INDEX", 0.6, "index")
    g.add_edge(t, "RATES", 0.35, "macro")
    g.add_edge(t, "CURRENCY", 0.3, "macro")
    g.add_edge(t, "COMMODITY", 0.25, "macro")
    for dep in (dependencies or []):
        name = str(dep.get("name") or dep.get("ticker") or "").strip()
        if not name:
            continue
        weight = dep.get("weight", 0.4)
        kind = str(dep.get("kind", "dependency"))
        g.add_edge(t, name.upper(), float(weight) if isinstance(weight, (int, float)) else 0.4, kind)
    return g


__all__ = [
    "DependencyEdge", "DependencyGraph", "build_default_graph",
]
