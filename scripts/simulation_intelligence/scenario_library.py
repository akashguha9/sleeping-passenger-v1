"""Reusable stress-test / scenario library for India & US equities.

Each scenario is a deterministic definition (id, name, shock parameters) that a
lens or the stress framework can apply.  Scenarios cover the market shocks named
in the sprint plus the *operational* failure modes specific to Sleeping
Passenger (model degradation, Sheets outage, stale feed, duplicate ingestion).

Definitions are pure data.  Applying a scenario stochastically is done by the
stress framework with a seeded RNG so runs are reproducible.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.simulation_intelligence.contracts import (
        SimulationScenario,
        SimulationAssumption,
    )
except ModuleNotFoundError:  # pragma: no cover
    from simulation_intelligence.contracts import (  # type: ignore[no-redef]
        SimulationScenario,
        SimulationAssumption,
    )


# Each entry: (id, name, description, shock_parameters, tags)
# shock_parameters use signed *fractional* conventions:
#   ret_shock       — one-shot return shock (e.g. -0.12 = -12%)
#   vol_mult        — volatility multiplier (2.0 = doubling)
#   liquidity_mult  — liquidity multiplier (<1 = evaporation)
#   corr_shock      — correlation increase toward 1 (0..1)
#   is_operational  — 1.0 if this is a system/ops failure, else 0.0
_DEFS: tuple[tuple[str, str, str, dict[str, float], list[str]], ...] = (
    ("broad_market_crash", "Broad-market crash",
     "Index-wide risk-off; correlations spike toward 1.",
     {"ret_shock": -0.12, "vol_mult": 2.5, "liquidity_mult": 0.6, "corr_shock": 0.8}, ["market", "IN", "US"]),
    ("sector_crash", "Sector crash",
     "Sector-specific de-rating while the broad index holds.",
     {"ret_shock": -0.18, "vol_mult": 2.0, "liquidity_mult": 0.7, "corr_shock": 0.5}, ["market", "IN", "US"]),
    ("rate_shock", "Interest-rate shock",
     "Surprise policy-rate move; duration-sensitive names hit hardest.",
     {"ret_shock": -0.07, "vol_mult": 1.8, "liquidity_mult": 0.85, "corr_shock": 0.6}, ["macro", "IN", "US"]),
    ("inflation_shock", "Inflation shock",
     "Hot CPI print; margins and multiples compress.",
     {"ret_shock": -0.06, "vol_mult": 1.6, "liquidity_mult": 0.9, "corr_shock": 0.5}, ["macro", "IN", "US"]),
    ("currency_shock", "Currency shock",
     "Sharp INR/USD move; importers/exporters diverge.",
     {"ret_shock": -0.05, "vol_mult": 1.5, "liquidity_mult": 0.9, "corr_shock": 0.4}, ["macro", "IN"]),
    ("oil_shock", "Oil-price shock",
     "Crude spike; energy-sensitive economies (India) pressured.",
     {"ret_shock": -0.05, "vol_mult": 1.5, "liquidity_mult": 0.9, "corr_shock": 0.4}, ["commodity", "IN", "US"]),
    ("commodity_shock", "Commodity shock",
     "Broad commodity move; input-cost repricing.",
     {"ret_shock": -0.05, "vol_mult": 1.4, "liquidity_mult": 0.9, "corr_shock": 0.4}, ["commodity", "IN", "US"]),
    ("regulatory_intervention", "Regulatory intervention",
     "SEBI/SEC action or probe; overhang and forced disclosure.",
     {"ret_shock": -0.15, "vol_mult": 2.2, "liquidity_mult": 0.6, "corr_shock": 0.3}, ["idiosyncratic", "IN", "US"]),
    ("earnings_miss", "Earnings miss",
     "Reported below consensus; immediate re-rating.",
     {"ret_shock": -0.10, "vol_mult": 1.9, "liquidity_mult": 0.8, "corr_shock": 0.2}, ["idiosyncratic", "IN", "US"]),
    ("beat_bad_guidance", "Earnings beat, negative guidance",
     "Beat on the quarter but cut forward guidance; narrative reversal.",
     {"ret_shock": -0.08, "vol_mult": 1.8, "liquidity_mult": 0.8, "corr_shock": 0.2}, ["idiosyncratic", "IN", "US"]),
    ("fraud_allegation", "Fraud allegation",
     "Short-seller/whistleblower fraud claim; tail-risk repricing.",
     {"ret_shock": -0.30, "vol_mult": 3.0, "liquidity_mult": 0.4, "corr_shock": 0.2}, ["tail", "IN", "US"]),
    ("governance_failure", "Governance failure",
     "Board/promoter governance breakdown; trust discount.",
     {"ret_shock": -0.20, "vol_mult": 2.4, "liquidity_mult": 0.5, "corr_shock": 0.2}, ["tail", "IN", "US"]),
    ("liquidity_evaporation", "Liquidity evaporation",
     "Bid/ask blows out; unable to exit at quoted price.",
     {"ret_shock": -0.06, "vol_mult": 2.0, "liquidity_mult": 0.25, "corr_shock": 0.5}, ["liquidity", "IN", "US"]),
    ("gap_down_open", "Gap-down opening",
     "Overnight gap through stops; no continuous fill.",
     {"ret_shock": -0.09, "vol_mult": 2.1, "liquidity_mult": 0.6, "corr_shock": 0.5}, ["tail", "IN", "US"]),
    ("correlation_spike", "Correlation spike",
     "Diversification fails as everything moves together.",
     {"ret_shock": -0.05, "vol_mult": 1.8, "liquidity_mult": 0.8, "corr_shock": 0.95}, ["market", "IN", "US"]),
    ("vol_regime_shift", "Volatility-regime shift",
     "Persistent step-change to a high-vol regime.",
     {"ret_shock": -0.03, "vol_mult": 2.2, "liquidity_mult": 0.85, "corr_shock": 0.6}, ["regime", "IN", "US"]),
    ("war_escalation", "War escalation",
     "Geopolitical escalation; risk-off and commodity spikes.",
     {"ret_shock": -0.10, "vol_mult": 2.3, "liquidity_mult": 0.6, "corr_shock": 0.8}, ["geopolitical", "IN", "US"]),
    ("sanctions", "Sanctions",
     "Sanctions regime hits specific sectors/counterparties.",
     {"ret_shock": -0.12, "vol_mult": 2.0, "liquidity_mult": 0.6, "corr_shock": 0.5}, ["geopolitical", "IN", "US"]),
    ("supply_chain_interruption", "Supply-chain interruption",
     "Key input/logistics disruption; delivery risk.",
     {"ret_shock": -0.08, "vol_mult": 1.7, "liquidity_mult": 0.85, "corr_shock": 0.4}, ["idiosyncratic", "IN", "US"]),
    ("cyber_incident", "Cyber incident",
     "Breach/outage at the company; operational + trust hit.",
     {"ret_shock": -0.11, "vol_mult": 1.9, "liquidity_mult": 0.7, "corr_shock": 0.2}, ["idiosyncratic", "IN", "US"]),
    ("index_inclusion", "Index inclusion",
     "Passive inflow tailwind on inclusion.",
     {"ret_shock": 0.06, "vol_mult": 1.4, "liquidity_mult": 1.2, "corr_shock": 0.3}, ["flow", "IN", "US"]),
    ("index_exclusion", "Index exclusion",
     "Forced passive selling on exclusion.",
     {"ret_shock": -0.08, "vol_mult": 1.6, "liquidity_mult": 0.8, "corr_shock": 0.3}, ["flow", "IN", "US"]),
    ("short_squeeze", "Short squeeze",
     "Crowded short forced to cover; violent upside then reversal.",
     {"ret_shock": 0.20, "vol_mult": 3.0, "liquidity_mult": 0.7, "corr_shock": 0.2}, ["tail", "IN", "US"]),
    ("narrative_reversal", "Narrative reversal",
     "The dominant thesis flips; positioning unwinds.",
     {"ret_shock": -0.12, "vol_mult": 2.0, "liquidity_mult": 0.75, "corr_shock": 0.3}, ["narrative", "IN", "US"]),
    ("crowded_unwind", "Crowded positioning unwind",
     "Consensus long unwinds; reflexive selling.",
     {"ret_shock": -0.14, "vol_mult": 2.1, "liquidity_mult": 0.7, "corr_shock": 0.6}, ["positioning", "IN", "US"]),
    # -------- operational / system failure scenarios (Sleeping Passenger) -----
    ("data_source_failure", "Data-source failure",
     "A primary data source goes dark; freshness degrades. FAIL-CLOSED expected.",
     {"ret_shock": 0.0, "vol_mult": 1.0, "liquidity_mult": 1.0, "corr_shock": 0.0, "is_operational": 1.0}, ["operational"]),
    ("model_provider_failure", "Model-provider failure",
     "One of five models is unreachable; synthesis degrades.",
     {"ret_shock": 0.0, "vol_mult": 1.0, "liquidity_mult": 1.0, "corr_shock": 0.0, "is_operational": 1.0}, ["operational"]),
    ("four_of_five_degradation", "Four-of-five model degradation",
     "Four of five models degrade; consensus is an illusion of one model.",
     {"ret_shock": 0.0, "vol_mult": 1.0, "liquidity_mult": 1.0, "corr_shock": 0.0, "is_operational": 1.0}, ["operational"]),
    ("sheets_outage", "Google Sheets outage",
     "Reconciliation source unavailable; outcome ledger stalls.",
     {"ret_shock": 0.0, "vol_mult": 1.0, "liquidity_mult": 1.0, "corr_shock": 0.0, "is_operational": 1.0}, ["operational"]),
    ("stale_price_feed", "Stale-price feed",
     "Prices stop updating; downstream reads must fail closed.",
     {"ret_shock": 0.0, "vol_mult": 1.0, "liquidity_mult": 1.0, "corr_shock": 0.0, "is_operational": 1.0}, ["operational"]),
    ("duplicate_event_ingestion", "Duplicate-event ingestion",
     "The same event ingested twice; evidence double-counting risk.",
     {"ret_shock": 0.0, "vol_mult": 1.0, "liquidity_mult": 1.0, "corr_shock": 0.0, "is_operational": 1.0}, ["operational"]),
    ("conflicting_filings", "Conflicting corporate filings",
     "Two filings disagree; provenance conflict must surface.",
     {"ret_shock": 0.0, "vol_mult": 1.0, "liquidity_mult": 1.0, "corr_shock": 0.0, "is_operational": 1.0}, ["operational"]),
)


def _to_scenario(row: tuple) -> SimulationScenario:
    sid, name, desc, shocks, tags = row
    assumptions = [
        SimulationAssumption(name=k, value=float(v), unit="fraction",
                             rationale=f"{name} shock parameter")
        for k, v in shocks.items()
    ]
    return SimulationScenario(
        scenario_id=sid, name=name, description=desc,
        assumptions=assumptions, shock_parameters=dict(shocks),
        deterministic=True, tags=list(tags),
    )


_SCENARIOS: dict[str, SimulationScenario] = {
    row[0]: _to_scenario(row) for row in _DEFS
}


def all_scenarios() -> list[SimulationScenario]:
    return list(_SCENARIOS.values())


def get_scenario(scenario_id: str) -> SimulationScenario | None:
    return _SCENARIOS.get(scenario_id)


def scenarios_for_market(market: str) -> list[SimulationScenario]:
    """Scenarios tagged for a market (plus market-agnostic operational ones)."""
    m = (market or "").upper()
    out = []
    for s in _SCENARIOS.values():
        tags = {t.upper() for t in s.tags}
        if "OPERATIONAL" in tags or not {"IN", "US"} & tags or m in tags:
            out.append(s)
    return out


def default_scenario_ids() -> list[str]:
    """A compact, high-value default stress set for a first-pass run."""
    return [
        "broad_market_crash", "sector_crash", "fraud_allegation",
        "liquidity_evaporation", "gap_down_open", "correlation_spike",
        "earnings_miss", "narrative_reversal",
        "four_of_five_degradation", "stale_price_feed",
    ]


def catalog() -> list[dict[str, Any]]:
    return [
        {
            "scenario_id": s.scenario_id,
            "name": s.name,
            "description": s.description,
            "tags": s.tags,
            "operational": bool(s.shock_parameters.get("is_operational", 0.0)),
            "shock_parameters": s.shock_parameters,
        }
        for s in _SCENARIOS.values()
    ]


__all__ = [
    "all_scenarios", "get_scenario", "scenarios_for_market",
    "default_scenario_ids", "catalog",
]
