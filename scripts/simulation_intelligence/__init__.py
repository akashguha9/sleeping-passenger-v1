"""Simulation Intelligence Layer (SIL) — advisory-only six-lens simulation council.

An advisory-only, human-execution-required subsystem that reinterprets a market
candidate through six independent domain lenses (physics, chemistry, biology,
racing, chess, poker), each transplanting the strongest *decision principle* of
its named engines, and aggregates them without naive averaging.

Purity + safety contract:
* pure compute — no sqlite3, no network, no broker, no frontend imports
* canonical persistence lives in ``scripts/persistence.py`` (the SIL never
  writes the DB itself)
* every output is SIMULATED_ONLY / PROXY_DERIVED / MODEL_INFERRED and NEVER
  feeds calibration or claims measured accuracy
* fails closed on missing / stale / insufficient data
* all optional engines (COPASI, Stockfish) are OFF by default; the council runs
  fully without them

Nothing here can place an order, call a broker, or grant execution permission.
"""
from __future__ import annotations

CONTRACT_VERSION = "sil-1.0.0"

try:
    from scripts.simulation_intelligence.contracts import (
        SimulationRequest, MarketObservation, SimulationCouncilResult, LensResult,
    )
    from scripts.simulation_intelligence.council import run_council
    from scripts.simulation_intelligence import engine_manifest
    from scripts.simulation_intelligence import feature_flags
except ModuleNotFoundError:  # pragma: no cover
    from simulation_intelligence.contracts import (  # type: ignore[no-redef]
        SimulationRequest, MarketObservation, SimulationCouncilResult, LensResult,
    )
    from simulation_intelligence.council import run_council  # type: ignore[no-redef]
    from simulation_intelligence import engine_manifest  # type: ignore[no-redef]
    from simulation_intelligence import feature_flags  # type: ignore[no-redef]

__all__ = [
    "CONTRACT_VERSION",
    "SimulationRequest", "MarketObservation", "SimulationCouncilResult", "LensResult",
    "run_council", "engine_manifest", "feature_flags",
]
