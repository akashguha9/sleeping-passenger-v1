"""Adapter registry — enumerates all eighteen engines with honest status.

Two adapters can be real (COPASI native lib, Stockfish subprocess); the other
sixteen are :class:`ConceptTransplantAdapter` (or REJECTED) that never invoke a
real engine.  The registry is the single source the API's
``GET /api/simulation/engines`` reads for live availability, joined with the
static :mod:`engine_manifest`.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.simulation_intelligence.adapters.base import (
        SimulationEngineAdapter, ConceptTransplantAdapter, AdapterReport,
    )
    from scripts.simulation_intelligence.adapters.copasi_adapter import CopasiAdapter
    from scripts.simulation_intelligence.adapters.stockfish_adapter import StockfishAdapter
    from scripts.simulation_intelligence import engine_manifest as em
except ModuleNotFoundError:  # pragma: no cover
    from simulation_intelligence.adapters.base import (  # type: ignore[no-redef]
        SimulationEngineAdapter, ConceptTransplantAdapter, AdapterReport,
    )
    from simulation_intelligence.adapters.copasi_adapter import CopasiAdapter  # type: ignore[no-redef]
    from simulation_intelligence.adapters.stockfish_adapter import StockfishAdapter  # type: ignore[no-redef]
    from simulation_intelligence import engine_manifest as em  # type: ignore[no-redef]

# The two real optional adapters, keyed by manifest engine name.
_REAL_ADAPTERS: dict[str, SimulationEngineAdapter] = {
    "COPASI": CopasiAdapter(),
    "Stockfish": StockfishAdapter(),
}


def build_adapters() -> list[SimulationEngineAdapter]:
    """One adapter per manifest engine (18 total), honest status each."""
    out: list[SimulationEngineAdapter] = []
    for entry in em.MANIFEST:
        real = _REAL_ADAPTERS.get(entry.engine)
        if real is not None:
            out.append(real)
        else:
            out.append(ConceptTransplantAdapter(
                engine=entry.engine,
                integration_mode=entry.integration_mode,
                transplanted_into=entry.transplanted_into,
                detail=entry.reason[:200],
            ))
    return out


def availability_report() -> dict[str, Any]:
    """Machine-readable availability across all eighteen engines."""
    reports = [a.report() for a in build_adapters()]
    available = [r.engine for r in reports if r.status == "AVAILABLE"]
    return {
        "engine_count": len(reports),
        "available_now": available,
        "available_count": len(available),
        "adapters": [r.to_dict() for r in reports],
        "note": (
            "Only COPASI (if pip-installed + SIL_COPASI_ENABLED) and Stockfish "
            "(if on PATH + SIL_STOCKFISH_ENABLED) can be AVAILABLE. All others "
            "are CONCEPT_TRANSPLANT/REJECTED and never invoke a real engine."
        ),
    }


def engine_availability_map() -> dict[str, str]:
    """Compact {engine: status} map for embedding in a council result."""
    return {a.report().engine: a.report().status for a in build_adapters()}


__all__ = [
    "build_adapters", "availability_report", "engine_availability_map",
]
