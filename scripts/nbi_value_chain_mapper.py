"""NBI value-chain graph v1 — Event -> ... -> Ticker exposure, evidence-gated.

Replaces nbi-v1.0's hand-tagged exposure lists with a graph:

    Event -> Country -> Sector -> Industry -> ChainNode -> Company -> Ticker

Exposure per ticker:

    VCE_i = sum over paths(Event -> i) of
            prod(edge weights) * NodeCriticality(path) * EvidenceFactor(path)

Evidence gating (cite-or-drop, tested): an edge without an ``evidence_ref``
contributes weight 0 — an uncited path can never raise exposure.  Path
evidence refs propagate onto the generated exposure rows so the engine's
per-ticker provenance chain stays intact.

Exposure types map onto the engine's catalyst channels (symbolic vs
substantive split), so a venue collapse rotates the basket through the
GRAPH, not through hardcoded ticker lists:

    VENUE_SPECIFIC -> venue branch  | LOCAL_SYMBOLIC -> venue branch
    BROAD_THEMATIC / UPSTREAM / DOWNSTREAM -> core / sector branches
    DIRECT -> deals branch          | INDIRECT -> sector branch
    HEDGE_PAIR / BENCHMARK -> metadata only (never scored as exposure)

The v1 graph is manually curated + persisted as data (acceptable per spec)
— every edge cites its evidence.  Advisory-only; pure functions, no network.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

from scripts.narrative_branch_engine import CATALYST_CHANNELS

VALUE_CHAIN_VERSION = "nbi-vcg-v1.0"

NODE_KINDS: tuple[str, ...] = (
    "EVENT", "COUNTRY", "SECTOR", "INDUSTRY", "CHAIN_NODE", "COMPANY", "TICKER",
)
EXPOSURE_TYPES: tuple[str, ...] = (
    "UPSTREAM", "DOWNSTREAM", "DIRECT", "INDIRECT",
    "LOCAL_SYMBOLIC", "VENUE_SPECIFIC", "BROAD_THEMATIC",
    "HEDGE_PAIR", "BENCHMARK",
)
# Exposure type -> engine catalyst channel.  HEDGE_PAIR/BENCHMARK are
# metadata: they never become scored exposures.
EXPOSURE_TYPE_TO_CHANNEL: dict[str, str] = {
    "UPSTREAM": "BROAD_THEMATIC",
    "DOWNSTREAM": "INDIRECT_VALUE_CHAIN",
    "DIRECT": "DIRECT_COMPANY",
    "INDIRECT": "INDIRECT_VALUE_CHAIN",
    "LOCAL_SYMBOLIC": "SYMBOLIC_LOCAL",
    "VENUE_SPECIFIC": "VENUE_SPECIFIC",
    "BROAD_THEMATIC": "BROAD_THEMATIC",
}
_MAX_PATH_DEPTH = 8


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def normalize_graph(graph: Any) -> dict[str, Any]:
    """Validate {nodes: [{id, kind, ...}], edges: [{src, dst, weight,
    exposure_type, evidence_ref, criticality?}]} into an adjacency map."""
    data = graph if isinstance(graph, dict) else {}
    nodes: dict[str, dict[str, Any]] = {}
    for n in data.get("nodes", []) if isinstance(data.get("nodes"), list) else []:
        if not isinstance(n, dict):
            continue
        node_id = str(n.get("id") or "").strip()
        kind = str(n.get("kind") or "").strip().upper()
        if node_id and kind in NODE_KINDS:
            nodes[node_id] = {**n, "id": node_id, "kind": kind}
    adjacency: dict[str, list[dict[str, Any]]] = {}
    dropped: list[str] = []
    for e in data.get("edges", []) if isinstance(data.get("edges"), list) else []:
        if not isinstance(e, dict):
            continue
        src, dst = str(e.get("src") or ""), str(e.get("dst") or "")
        if src not in nodes or dst not in nodes:
            dropped.append(f"edge {src}->{dst}: unknown node")
            continue
        exposure_type = str(e.get("exposure_type") or "").upper()
        if exposure_type not in EXPOSURE_TYPES:
            dropped.append(f"edge {src}->{dst}: unknown exposure_type")
            continue
        try:
            weight = float(e.get("weight", 0.0))
        except (TypeError, ValueError):
            weight = 0.0
        evidence_ref = str(e.get("evidence_ref") or "").strip()
        if not evidence_ref:
            # Cite-or-drop: an uncited edge carries zero weight, disclosed.
            weight = 0.0
            dropped.append(f"edge {src}->{dst}: no evidence_ref -> weight 0")
        adjacency.setdefault(src, []).append({
            "src": src, "dst": dst,
            "weight": _clamp(weight, 0.0, 1.0),
            "exposure_type": exposure_type,
            "evidence_ref": evidence_ref,
            "criticality": _clamp(float(e.get("criticality", 1.0) or 1.0), 0.0, 1.0),
        })
    return {"nodes": nodes, "adjacency": adjacency, "dropped_edges": dropped}


def _walk_paths(
    normalized: dict[str, Any], start: str,
) -> list[dict[str, Any]]:
    """All acyclic Event->TICKER paths (bounded depth), with products."""
    paths: list[dict[str, Any]] = []
    nodes = normalized["nodes"]
    adjacency = normalized["adjacency"]

    def visit(node_id: str, product: float, criticality: float,
              exposure_types: list[str], refs: list[str],
              trail: list[str]) -> None:
        if len(trail) > _MAX_PATH_DEPTH:
            return
        for edge in adjacency.get(node_id, []):
            dst = edge["dst"]
            if dst in trail:
                continue  # cycle guard
            new_product = product * edge["weight"]
            new_crit = min(criticality, edge["criticality"])
            new_types = exposure_types + [edge["exposure_type"]]
            new_refs = refs + ([edge["evidence_ref"]] if edge["evidence_ref"] else [])
            if nodes[dst]["kind"] == "TICKER":
                if new_product > 0:
                    paths.append({
                        "ticker": dst,
                        "product": new_product,
                        "criticality": new_crit,
                        "exposure_types": new_types,
                        "evidence_refs": new_refs,
                        "path": trail + [dst],
                    })
            else:
                visit(dst, new_product, new_crit, new_types, new_refs,
                      trail + [dst])

    visit(start, 1.0, 1.0, [], [], [start])
    return paths


def _dominant_channel(exposure_types: list[str]) -> str | None:
    """Channel of a path = its most specific (last mappable) exposure type."""
    for etype in reversed(exposure_types):
        channel = EXPOSURE_TYPE_TO_CHANNEL.get(etype)
        if channel:
            return channel
    return None


def compute_vce(graph: Any, event_node: str) -> dict[str, dict[str, Any]]:
    """Per-ticker, per-channel VCE from all evidence-backed paths."""
    normalized = normalize_graph(graph)
    per_ticker: dict[str, dict[str, Any]] = {}
    for path in _walk_paths(normalized, event_node):
        channel = _dominant_channel(path["exposure_types"])
        if channel is None:
            continue  # HEDGE_PAIR / BENCHMARK metadata path
        entry = per_ticker.setdefault(path["ticker"], {
            "ticker": path["ticker"], "channels": {}, "evidence_refs": [],
            "paths": 0,
        })
        contribution = path["product"] * path["criticality"]
        entry["channels"][channel] = round(
            entry["channels"].get(channel, 0.0) + contribution, 6
        )
        entry["evidence_refs"] = sorted(
            set(entry["evidence_refs"]) | set(path["evidence_refs"])
        )
        entry["paths"] += 1
    return per_ticker


def build_exposures_from_graph(
    graph: Any,
    event_node: str,
    *,
    ticker_metadata: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Graph -> engine-ready exposure rows (one per ticker per channel).

    base_relevance = 10 * min(1, VCE_channel).  Liquidity / filing / price
    fields come from ``ticker_metadata`` (fail-closed defaults when absent:
    liquidity unknown, filing unconfirmed, no price data -> the engine will
    haircut/WATCH_ONLY them exactly as doctrine requires).
    """
    metadata = ticker_metadata or {}
    exposures: list[dict[str, Any]] = []
    for ticker, entry in sorted(compute_vce(graph, event_node).items()):
        meta = metadata.get(ticker, {})
        for channel, vce in sorted(entry["channels"].items()):
            if channel not in CATALYST_CHANNELS or vce <= 0:
                continue
            exposures.append({
                "ticker": ticker,
                "channel": channel,
                "base_relevance": round(10.0 * _clamp(vce, 0.0, 1.0), 4),
                "evidence_confidence": _clamp(
                    float(meta.get("evidence_confidence", 0.7)), 0.0, 1.0
                ),
                "evidence_refs": entry["evidence_refs"],
                "vce_raw": vce,
                "filing_confirmed": bool(meta.get("filing_confirmed", False)),
                "liquidity_ok": meta.get("liquidity_ok"),
                "days_since_last_verified": meta.get("days_since_last_verified"),
                "model_probability": meta.get("model_probability"),
                "market_implied_probability": meta.get("market_implied_probability"),
                "realized_move_zscore": meta.get("realized_move_zscore"),
                "exposure_source": f"value_chain_graph:{VALUE_CHAIN_VERSION}",
            })
    return exposures


# ---------------------------------------------------------------------------
# Demo graph — the Guwahati -> Delhi case as a value chain (fixture data)
# ---------------------------------------------------------------------------

DEMO_GRAPH: dict[str, Any] = {
    "nodes": [
        {"id": "EV:JP-IN-SUMMIT", "kind": "EVENT"},
        {"id": "C:IN", "kind": "COUNTRY"}, {"id": "C:JP", "kind": "COUNTRY"},
        {"id": "S:INFRA", "kind": "SECTOR"}, {"id": "S:MACHINERY", "kind": "SECTOR"},
        {"id": "S:AUTO", "kind": "SECTOR"}, {"id": "S:SEMI", "kind": "SECTOR"},
        {"id": "N:ASSAM-VENUE", "kind": "CHAIN_NODE"},
        {"id": "N:EXPORT-CHAIN", "kind": "CHAIN_NODE"},
        {"id": "N:AUTO-SUPPLY", "kind": "CHAIN_NODE"},
        {"id": "N:SEMI-FAB", "kind": "CHAIN_NODE"},
        {"id": "ASSAMINFRA", "kind": "TICKER"},
        {"id": "NE_CEMENT", "kind": "TICKER"},
        {"id": "JPMACH", "kind": "TICKER"},
        {"id": "INDAUTO", "kind": "TICKER"},
        {"id": "TATAELEC_PROXY", "kind": "TICKER"},
    ],
    "edges": [
        {"src": "EV:JP-IN-SUMMIT", "dst": "C:IN", "weight": 1.0,
         "exposure_type": "BROAD_THEMATIC",
         "evidence_ref": "https://example.com/fixture/summit-scope"},
        {"src": "EV:JP-IN-SUMMIT", "dst": "C:JP", "weight": 1.0,
         "exposure_type": "BROAD_THEMATIC",
         "evidence_ref": "https://example.com/fixture/summit-scope"},
        {"src": "C:IN", "dst": "S:INFRA", "weight": 0.9,
         "exposure_type": "BROAD_THEMATIC",
         "evidence_ref": "https://example.com/fixture/infra-theme"},
        {"src": "S:INFRA", "dst": "N:ASSAM-VENUE", "weight": 0.9,
         "exposure_type": "VENUE_SPECIFIC",
         "evidence_ref": "https://example.com/fixture/guwahati-venue-note"},
        {"src": "N:ASSAM-VENUE", "dst": "ASSAMINFRA", "weight": 0.9,
         "exposure_type": "VENUE_SPECIFIC",
         "evidence_ref": "https://example.com/fixture/assam-infra-note"},
        {"src": "N:ASSAM-VENUE", "dst": "NE_CEMENT", "weight": 0.8,
         "exposure_type": "LOCAL_SYMBOLIC",
         "evidence_ref": "https://example.com/fixture/ne-cement-note"},
        {"src": "C:JP", "dst": "S:MACHINERY", "weight": 0.9,
         "exposure_type": "UPSTREAM",
         "evidence_ref": "https://example.com/fixture/machinery-theme"},
        {"src": "S:MACHINERY", "dst": "N:EXPORT-CHAIN", "weight": 0.9,
         "exposure_type": "UPSTREAM",
         "evidence_ref": "https://example.com/fixture/export-chain"},
        {"src": "N:EXPORT-CHAIN", "dst": "JPMACH", "weight": 0.9,
         "exposure_type": "BROAD_THEMATIC",
         "evidence_ref": "https://example.com/fixture/jpmach-filing"},
        {"src": "C:IN", "dst": "S:AUTO", "weight": 0.8,
         "exposure_type": "DOWNSTREAM",
         "evidence_ref": "https://example.com/fixture/auto-theme"},
        {"src": "S:AUTO", "dst": "N:AUTO-SUPPLY", "weight": 0.9,
         "exposure_type": "INDIRECT",
         "evidence_ref": "https://example.com/fixture/auto-supply"},
        {"src": "N:AUTO-SUPPLY", "dst": "INDAUTO", "weight": 0.9,
         "exposure_type": "INDIRECT",
         "evidence_ref": "https://example.com/fixture/indauto-filing"},
        {"src": "C:IN", "dst": "S:SEMI", "weight": 0.9,
         "exposure_type": "DIRECT",
         "evidence_ref": "https://example.com/fixture/semi-theme"},
        {"src": "S:SEMI", "dst": "N:SEMI-FAB", "weight": 0.9,
         "exposure_type": "DIRECT",
         "evidence_ref": "https://example.com/fixture/semi-fab"},
        {"src": "N:SEMI-FAB", "dst": "TATAELEC_PROXY", "weight": 0.9,
         "exposure_type": "DIRECT",
         "evidence_ref": "https://example.com/fixture/tata-assam-note"},
    ],
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="NBI value-chain graph v1: graph -> engine exposures."
    )
    parser.add_argument("--graph-json", help="Path to a graph JSON file")
    parser.add_argument("--event-node", default="EV:JP-IN-SUMMIT")
    parser.add_argument("--demo", action="store_true", help="Use the fixture graph")
    args = parser.parse_args(argv)
    if args.demo:
        graph: Any = DEMO_GRAPH
    elif args.graph_json:
        with open(args.graph_json, "r", encoding="utf-8") as fh:
            graph = json.load(fh)
    else:
        parser.print_help()
        return 2
    exposures = build_exposures_from_graph(graph, args.event_node)
    print(json.dumps(exposures, indent=2))
    print(f"\n# {len(exposures)} exposures | ADVISORY_ONLY")
    return 0


__all__ = [
    "VALUE_CHAIN_VERSION", "NODE_KINDS", "EXPOSURE_TYPES",
    "EXPOSURE_TYPE_TO_CHANNEL", "DEMO_GRAPH",
    "normalize_graph", "compute_vce", "build_exposures_from_graph", "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
