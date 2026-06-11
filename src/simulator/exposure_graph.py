"""Exposure graph v0: deterministic theme -> value chain -> ticker resolution.

Replaces "exposure is scored, not resolved" with a minimal local graph:

    theme -> value-chain node -> exposure edge -> ticker

Every edge carries provenance (source, confidence, lag, fragility,
explanation). Conservative scoring:

    exposure_confidence = 1 - Π(1 - edge_confidence_i)
    lag_decay           = 0.5 ** (mean_lag_days / LAG_HALF_LIFE_DAYS)
    fragility_adjusted  = exposure_confidence * (1 - mean_fragility) * lag_decay

This is NOT a complete real supply-chain graph: it is seeded, local, and
deterministic, built so a real data source can later populate the same
structures. Tickers resolved here are research candidates, ADVISORY_ONLY.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clamp01
from src.utils.validation_utils import normalized_score

EVIDENCE_DIRECT_REVENUE = "direct_revenue"
EVIDENCE_SUPPLIER_CUSTOMER = "supplier_customer_relationship"
EVIDENCE_CAPEX_BENEFICIARY = "capex_beneficiary"
EVIDENCE_REGULATION_BENEFICIARY = "regulation_beneficiary"
EVIDENCE_GEOGRAPHIC_CONCENTRATION = "geographic_concentration"
EVIDENCE_COMMODITY_LINK = "commodity_input_output"
EVIDENCE_SECOND_ORDER = "second_order_derivative_exposure"

EVIDENCE_TYPES: tuple[str, ...] = (
    EVIDENCE_DIRECT_REVENUE,
    EVIDENCE_SUPPLIER_CUSTOMER,
    EVIDENCE_CAPEX_BENEFICIARY,
    EVIDENCE_REGULATION_BENEFICIARY,
    EVIDENCE_GEOGRAPHIC_CONCENTRATION,
    EVIDENCE_COMMODITY_LINK,
    EVIDENCE_SECOND_ORDER,
)

LAG_HALF_LIFE_DAYS = 180.0


@dataclass(slots=True)
class ExposureEdge:
    """One evidence-bearing link from a value-chain node to a ticker."""

    ticker: str
    value_chain_node: str
    evidence_type: str
    source: str
    confidence: float
    lag_days: float
    fragility: float
    explanation: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ResolvedExposure:
    """All edges for one ticker under one theme, conservatively scored."""

    ticker: str
    theme: str
    exposure_confidence: float
    mean_fragility: float
    mean_lag_days: float
    lag_decay: float
    fragility_adjusted_exposure: float
    edge_count: int
    evidence_types: list[str] = field(default_factory=list)
    edges: list[ExposureEdge] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ExposureGraph:
    """A deterministic, seedable theme -> ticker exposure graph."""

    edges_by_theme: dict[str, list[ExposureEdge]] = field(default_factory=dict)

    def add_edge(self, theme: str, edge: ExposureEdge) -> None:
        if edge.evidence_type not in EVIDENCE_TYPES:
            raise ValueError(f"unknown evidence type: {edge.evidence_type!r}")
        self.edges_by_theme.setdefault(str(theme), []).append(edge)

    def themes(self) -> list[str]:
        return sorted(self.edges_by_theme)

    def tickers_for_theme(self, theme: str) -> list[str]:
        return sorted({e.ticker for e in self.edges_by_theme.get(str(theme), [])})

    def resolve(self, theme: str, ticker: str) -> ResolvedExposure:
        """Conservatively score one ticker's exposure to one theme."""
        wanted = str(ticker).upper()
        edges = [
            e
            for e in self.edges_by_theme.get(str(theme), [])
            if e.ticker.upper() == wanted
        ]
        if not edges:
            return ResolvedExposure(
                ticker=wanted,
                theme=str(theme),
                exposure_confidence=0.0,
                mean_fragility=0.0,
                mean_lag_days=0.0,
                lag_decay=0.0,
                fragility_adjusted_exposure=0.0,
                edge_count=0,
                reason_codes=["NO_GRAPH_EDGES"],
            )

        survival = 1.0
        for edge in edges:
            survival *= 1.0 - normalized_score(edge.confidence)
        confidence = clamp01(1.0 - survival)
        mean_fragility = sum(
            normalized_score(e.fragility) for e in edges
        ) / len(edges)
        mean_lag = sum(max(float(e.lag_days), 0.0) for e in edges) / len(edges)
        lag_decay = 0.5 ** (mean_lag / LAG_HALF_LIFE_DAYS)
        adjusted = clamp01(confidence * (1.0 - mean_fragility) * lag_decay)

        reasons: list[str] = []
        evidence_types = sorted({e.evidence_type for e in edges})
        if EVIDENCE_DIRECT_REVENUE in evidence_types:
            reasons.append("DIRECT_REVENUE_EDGE")
        if all(e.evidence_type == EVIDENCE_SECOND_ORDER for e in edges):
            reasons.append("SECOND_ORDER_ONLY")
        if mean_fragility >= 0.6:
            reasons.append("FRAGILE_EXPOSURE_CHAIN")
        if mean_lag >= LAG_HALF_LIFE_DAYS:
            reasons.append("SLOW_TRANSMISSION_CHAIN")
        if not reasons:
            reasons.append("GRAPH_RESOLVED")

        return ResolvedExposure(
            ticker=wanted,
            theme=str(theme),
            exposure_confidence=confidence,
            mean_fragility=mean_fragility,
            mean_lag_days=mean_lag,
            lag_decay=lag_decay,
            fragility_adjusted_exposure=adjusted,
            edge_count=len(edges),
            evidence_types=evidence_types,
            edges=edges,
            reason_codes=reasons,
        )

    def to_resolver_inputs(self, theme: str, ticker: str) -> dict[str, float]:
        """Bridge a resolved graph exposure into the legacy
        ``exposure_resolver.resolve_exposure`` component inputs.

        Each evidence type maps to the resolver component it supports;
        component strength is the best (highest-confidence, lag/fragility-
        adjusted) edge of that type. Missing evidence types stay 0 — the
        resolver remains conservative when the graph is silent.
        """
        resolved = self.resolve(theme, ticker)
        component_map = {
            EVIDENCE_DIRECT_REVENUE: "revenue_exposure",
            EVIDENCE_CAPEX_BENEFICIARY: "backlog_linkage",
            EVIDENCE_SUPPLIER_CUSTOMER: "customer_linkage",
            EVIDENCE_REGULATION_BENEFICIARY: "policy_fit",
            EVIDENCE_GEOGRAPHIC_CONCENTRATION: "geographic_fit",
            EVIDENCE_COMMODITY_LINK: "margin_sensitivity",
            EVIDENCE_SECOND_ORDER: "supply_chain_position",
        }
        inputs: dict[str, float] = {value: 0.0 for value in component_map.values()}
        for edge in resolved.edges:
            component = component_map[edge.evidence_type]
            edge_strength = clamp01(
                normalized_score(edge.confidence)
                * (1.0 - normalized_score(edge.fragility))
                * 0.5 ** (max(float(edge.lag_days), 0.0) / LAG_HALF_LIFE_DAYS)
            )
            inputs[component] = max(inputs[component], edge_strength)
        # No edges at all -> full weak-evidence penalty.
        inputs["weak_evidence_penalty"] = (
            1.0 if resolved.edge_count == 0 else clamp01(resolved.mean_fragility)
        )
        return inputs


def build_seed_graph() -> ExposureGraph:
    """Deterministic seed fixture: the AI-grid-buildout case study.

    SIMULATED DATA — these edges are illustrative research seeds, not an
    empirically fitted supply-chain dataset. They exist so the structure,
    scoring, and tests are real before a data source is wired in.
    """
    graph = ExposureGraph()
    theme = "ai_grid_buildout"
    seed = [
        ExposureEdge(
            ticker="GRIDCO", value_chain_node="transformers",
            evidence_type=EVIDENCE_DIRECT_REVENUE, source="seed_fixture_10q",
            confidence=0.7, lag_days=30, fragility=0.2,
            explanation="Transformer backlog disclosed in filings (seed).",
        ),
        ExposureEdge(
            ticker="GRIDCO", value_chain_node="grid_capex",
            evidence_type=EVIDENCE_CAPEX_BENEFICIARY, source="seed_fixture_policy",
            confidence=0.5, lag_days=120, fragility=0.4,
            explanation="Named beneficiary of grid capex programs (seed).",
        ),
        ExposureEdge(
            ticker="COPPERX", value_chain_node="copper",
            evidence_type=EVIDENCE_COMMODITY_LINK, source="seed_fixture_commodity",
            confidence=0.5, lag_days=180, fragility=0.5,
            explanation="Copper demand from grid build-out (seed).",
        ),
        ExposureEdge(
            ticker="COOLCO", value_chain_node="datacenter_cooling",
            evidence_type=EVIDENCE_SUPPLIER_CUSTOMER, source="seed_fixture_contracts",
            confidence=0.6, lag_days=60, fragility=0.3,
            explanation="Cooling supplier to hyperscale datacenters (seed).",
        ),
        ExposureEdge(
            ticker="HYPENAME", value_chain_node="grid_capex",
            evidence_type=EVIDENCE_SECOND_ORDER, source="seed_fixture_narrative",
            confidence=0.2, lag_days=365, fragility=0.8,
            explanation="Mentioned alongside the theme; no disclosed linkage (seed).",
        ),
    ]
    for edge in seed:
        graph.add_edge(theme, edge)
    return graph
