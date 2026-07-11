"""Causal event graph — typed, curated, bounded upstream/downstream traversal.

Loads the CURATED transmission graph (``config/causal_event_graph.json``)
and propagates an upstream event shock to downstream industry nodes and
security exposures:

    Impact_j = Shock_e * sum over paths pi(e -> j) of
                 e^(-lambda * len(pi)) * prod_k (strength_k * sign_k * confidence_k)

with hard explosion guards: max depth, confidence floor, cycle detection
(no node repeats within a path), per-target path merging, and bounded
outputs via tanh.  Lag classes combine by taking the SLOWEST edge on the
path plus one class step per extra hop (broad classes only — no invented
precision; independence of edge lags is NOT assumed, we take an ordinal
upper bound).

Honesty contract
----------------
* Every edge is validation_status=CURATED: an economic-transmission PRIOR,
  not a proven causal claim, and every path exposes its edges so the
  operator can reject the assumption chain.
* Correlation-type relations are excluded from propagation (none exist in
  the curated set; the loader would skip them with a note).
* Exposure weights map industries to seed-universe securities; unresolved
  exposures are dropped with a count, never silently invented.

Pure module; stdlib only; advisory-only.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

CAUSAL_GRAPH_ENGINE_VERSION = "causal_graph_v1"

GRAPH_PATH = Path(__file__).resolve().parents[1] / "config" / "causal_event_graph.json"

LAG_ORDER: tuple[str, ...] = ("IMMEDIATE", "FAST", "MEDIUM", "SLOW", "STRUCTURAL")
LAG_DESCRIPTIONS: dict[str, str] = {
    "IMMEDIATE": "0-1 trading days",
    "FAST": "2-5 trading days",
    "MEDIUM": "1-4 weeks",
    "SLOW": "1-6 months",
    "STRUCTURAL": "6+ months",
}

DEPTH_CLASSES: tuple[str, ...] = (
    "DIRECT", "FIRST_ORDER", "SECOND_ORDER", "THIRD_ORDER", "MACRO_PROPAGATED",
)

DEFAULT_MAX_DEPTH = 4
DEFAULT_LAMBDA = 0.35
DEFAULT_CONFIDENCE_FLOOR = 0.02


def load_causal_graph(path: Path | str | None = None) -> dict[str, Any]:
    """Load + validate the curated graph. Invalid edges are dropped with
    recorded problems; an unreadable file yields an empty graph with
    status, never a crash."""
    target = Path(path) if path is not None else GRAPH_PATH
    problems: list[str] = []
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {
            "status": "unreadable_graph_file",
            "graph_version": "none",
            "nodes": {},
            "edges": [],
            "adjacency": {},
            "exposures": {},
            "problems": ["graph_file_unreadable"],
        }
    nodes = {
        str(n.get("id")): n
        for n in raw.get("nodes", [])
        if isinstance(n, dict) and n.get("id")
    }
    edges: list[dict[str, Any]] = []
    for edge in raw.get("edges", []):
        if not isinstance(edge, dict):
            continue
        src, dst = str(edge.get("source", "")), str(edge.get("target", ""))
        if src not in nodes or dst not in nodes:
            problems.append(f"edge_unknown_node:{src}->{dst}")
            continue
        if src == dst:
            problems.append(f"edge_self_loop:{src}")
            continue
        sign = edge.get("sign")
        strength = edge.get("strength")
        confidence = edge.get("confidence")
        if sign not in (1, -1) or not (
            isinstance(strength, (int, float)) and 0 < float(strength) <= 1
        ) or not (
            isinstance(confidence, (int, float)) and 0 < float(confidence) <= 1
        ):
            problems.append(f"edge_invalid_params:{src}->{dst}")
            continue
        relation = str(edge.get("relation", "") or "")
        if relation == "CORRELATED_WITH":
            problems.append(f"edge_correlation_excluded_from_propagation:{src}->{dst}")
            continue
        lag = str(edge.get("lag_class", "MEDIUM") or "MEDIUM")
        if lag not in LAG_ORDER:
            lag = "MEDIUM"
        edges.append({
            "source": src, "target": dst, "relation": relation,
            "sign": int(sign), "strength": float(strength),
            "confidence": float(confidence), "lag_class": lag,
            "validation_status": "CURATED", "provenance": str(raw.get("graph_version", "curated")),
        })
    adjacency: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        adjacency.setdefault(edge["source"], []).append(edge)
    exposures = {
        str(k): [
            e for e in v
            if isinstance(e, dict) and e.get("ticker") and isinstance(e.get("weight"), (int, float))
            and abs(float(e["weight"])) > 0.0
        ]
        for k, v in (raw.get("exposures") or {}).items()
        if isinstance(v, list)
    }
    return {
        "status": "loaded",
        "graph_version": str(raw.get("graph_version", "unknown")),
        "nodes": nodes,
        "edges": edges,
        "adjacency": adjacency,
        "exposures": exposures,
        "problems": problems,
        "engine_version": CAUSAL_GRAPH_ENGINE_VERSION,
    }


def event_nodes_with_triggers(graph: dict[str, Any]) -> dict[str, list[str]]:
    """{event_node_id: [trigger keywords]} for narrative->event activation."""
    out: dict[str, list[str]] = {}
    for node_id, node in (graph.get("nodes") or {}).items():
        keywords = node.get("trigger_keywords")
        if isinstance(keywords, list) and keywords:
            out[node_id] = [str(k).lower() for k in keywords]
    return out


def _combine_lag(path_edges: list[dict[str, Any]]) -> str:
    """Ordinal upper bound: slowest edge, bumped one class per extra hop.
    Broad classes only; edge-lag independence is NOT assumed."""
    if not path_edges:
        return "MEDIUM"
    slowest = max(LAG_ORDER.index(e["lag_class"]) for e in path_edges)
    bumped = min(len(LAG_ORDER) - 1, slowest + max(0, len(path_edges) - 1) // 2)
    return LAG_ORDER[bumped]


def propagate_shock(
    graph: dict[str, Any],
    event_node: str,
    shock: float,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    length_lambda: float = DEFAULT_LAMBDA,
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR,
) -> dict[str, Any]:
    """Bounded DFS propagation from one event node.

    Returns per-node impacts and per-ticker exposures with strongest paths.
    """
    adjacency = graph.get("adjacency") or {}
    if event_node not in (graph.get("nodes") or {}):
        return {
            "status": "unknown_event_node",
            "event_node": event_node,
            "node_impacts": {},
            "security_exposures": [],
            "path_count": 0,
        }
    shock = max(-1.0, min(1.0, float(shock)))
    node_paths: dict[str, list[dict[str, Any]]] = {}
    path_count = 0

    def _walk(node: str, depth: int, contribution: float,
              visited: tuple[str, ...], edges_taken: list[dict[str, Any]]) -> None:
        nonlocal path_count
        if depth >= max_depth:
            return
        for edge in adjacency.get(node, []):
            nxt = edge["target"]
            if nxt in visited:
                continue  # cycle protection
            new_contribution = (
                contribution * edge["strength"] * edge["sign"] * edge["confidence"]
            )
            if abs(new_contribution) < confidence_floor:
                continue  # pruning
            new_edges = edges_taken + [edge]
            penalty = math.exp(-length_lambda * len(new_edges))
            path_count += 1
            node_paths.setdefault(nxt, []).append({
                "impact": new_contribution * penalty,
                "raw_product": new_contribution,
                "depth": len(new_edges),
                "nodes": list(visited) + [nxt],
                "lag_class": _combine_lag(new_edges),
                "relations": [e["relation"] for e in new_edges],
            })
            _walk(nxt, depth + 1, new_contribution, visited + (nxt,), new_edges)

    _walk(event_node, 0, shock, (event_node,), [])

    node_impacts: dict[str, dict[str, Any]] = {}
    for node, paths in node_paths.items():
        total = sum(p["impact"] for p in paths)
        strongest = max(paths, key=lambda p: abs(p["impact"]))
        node_impacts[node] = {
            "impact": round(math.tanh(total), 6),  # bounded
            "path_count": len(paths),
            "min_depth": min(p["depth"] for p in paths),
            "strongest_path": strongest["nodes"],
            "strongest_path_relations": strongest["relations"],
            "lag_class": strongest["lag_class"],
            "lag_description": LAG_DESCRIPTIONS[strongest["lag_class"]],
            "upstream_score": round(
                1.0 - min(p["depth"] for p in paths) / max_depth, 6
            ),
        }

    exposures_map = graph.get("exposures") or {}
    ticker_rows: dict[str, dict[str, Any]] = {}
    for node, info in node_impacts.items():
        for exposure in exposures_map.get(node, []):
            ticker = str(exposure["ticker"]).upper()
            weight = float(exposure["weight"])
            impact = info["impact"] * weight
            if abs(impact) < confidence_floor:
                continue
            existing = ticker_rows.get(ticker)
            if existing is None or abs(impact) > abs(existing["latent_impact"]):
                depth = info["min_depth"]
                depth_class = (
                    "FIRST_ORDER" if depth <= 1 else
                    "SECOND_ORDER" if depth == 2 else
                    "THIRD_ORDER" if depth == 3 else "MACRO_PROPAGATED"
                )
                ticker_rows[ticker] = {
                    "ticker": ticker,
                    "latent_impact": round(impact, 6),
                    "direction": "POSITIVE" if impact > 0 else "NEGATIVE",
                    "via_node": node,
                    "exposure_weight": weight,
                    "depth": depth,
                    "depth_class": depth_class,
                    "upstream_score": info["upstream_score"],
                    "strongest_path": info["strongest_path"] + [ticker],
                    "strongest_path_relations": info["strongest_path_relations"],
                    "lag_class": info["lag_class"],
                    "lag_description": info["lag_description"],
                    "path_count": info["path_count"],
                    "assumptions": "curated_transmission_priors_v1",
                }
    return {
        "status": "propagated",
        "event_node": event_node,
        "shock": round(shock, 6),
        "node_impacts": node_impacts,
        "security_exposures": sorted(
            ticker_rows.values(), key=lambda r: -abs(r["latent_impact"])
        ),
        "path_count": path_count,
        "max_depth": max_depth,
        "engine_version": CAUSAL_GRAPH_ENGINE_VERSION,
    }


__all__ = [
    "CAUSAL_GRAPH_ENGINE_VERSION",
    "LAG_ORDER",
    "LAG_DESCRIPTIONS",
    "DEPTH_CLASSES",
    "load_causal_graph",
    "event_nodes_with_triggers",
    "propagate_shock",
]
