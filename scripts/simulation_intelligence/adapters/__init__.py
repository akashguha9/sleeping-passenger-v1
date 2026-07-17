"""Engine adapters — honest availability for all eighteen named engines."""
from __future__ import annotations

try:
    from scripts.simulation_intelligence.adapters.base import (
        SimulationEngineAdapter, ConceptTransplantAdapter, AdapterStatus, AdapterReport,
    )
    from scripts.simulation_intelligence.adapters.registry import (
        build_adapters, availability_report, engine_availability_map,
    )
except ModuleNotFoundError:  # pragma: no cover
    from simulation_intelligence.adapters.base import (  # type: ignore[no-redef]
        SimulationEngineAdapter, ConceptTransplantAdapter, AdapterStatus, AdapterReport,
    )
    from simulation_intelligence.adapters.registry import (  # type: ignore[no-redef]
        build_adapters, availability_report, engine_availability_map,
    )

__all__ = [
    "SimulationEngineAdapter", "ConceptTransplantAdapter", "AdapterStatus",
    "AdapterReport", "build_adapters", "availability_report", "engine_availability_map",
]
