"""Clean adapter contract for external simulation engines.

The cardinal honesty rule of this whole layer lives here: an adapter existing
does NOT mean an engine is integrated.  Every adapter reports a truthful
:class:`AdapterStatus`.  Only two adapters can ever report ``AVAILABLE``:

* :mod:`copasi_adapter`   — real optional NATIVE_LIBRARY (Artistic-2.0, pip)
* :mod:`stockfish_adapter` — real optional EXTERNAL_PROCESS (GPLv3 subprocess)

Both are OFF by default and behind feature flags; the base workflow runs with
both unavailable.  Every other engine is a CONCEPT_TRANSPLANT (its principle is
reimplemented in a lens) or REJECTED, and its adapter reports
``CONCEPT_TRANSPLANT`` / ``REJECTED`` with the lens it was transplanted into —
it never pretends to invoke the real engine.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AdapterStatus(str, Enum):
    AVAILABLE = "AVAILABLE"          # a real engine is installed & callable
    UNAVAILABLE = "UNAVAILABLE"      # a real integration exists but is not present
    DISABLED = "DISABLED"            # gated off by a feature flag
    CONCEPT_TRANSPLANT = "CONCEPT_TRANSPLANT"  # principle reimplemented natively
    REJECTED = "REJECTED"            # deliberately not integrated
    ERROR = "ERROR"


@dataclass(slots=True)
class AdapterReport:
    engine: str
    integration_mode: str
    status: str
    transplanted_into: str = ""
    detail: str = ""
    real_execution_allowed: bool = False  # ALWAYS False — never trades
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        # Hard invariant: an adapter can never grant real execution.
        d["real_execution_allowed"] = False
        return d


class SimulationEngineAdapter:
    """Base adapter — subclasses declare their engine + honest availability."""

    engine: str = "unknown"
    integration_mode: str = "CONCEPT_TRANSPLANT"
    transplanted_into: str = ""

    def is_available(self) -> bool:
        """Real engines override this; transplants/rejected always return False."""
        return False

    def status(self) -> AdapterStatus:
        return AdapterStatus.CONCEPT_TRANSPLANT

    def report(self) -> AdapterReport:
        return AdapterReport(
            engine=self.engine,
            integration_mode=self.integration_mode,
            status=self.status().value,
            transplanted_into=self.transplanted_into,
        )


class ConceptTransplantAdapter(SimulationEngineAdapter):
    """Honest stand-in for an engine whose *principle* was transplanted.

    It never invokes the real engine; it exists so the registry can enumerate
    all eighteen engines with a truthful status and point at the lens that
    carries the transplanted principle.
    """

    def __init__(self, engine: str, integration_mode: str, transplanted_into: str,
                 detail: str = "") -> None:
        self.engine = engine
        self.integration_mode = integration_mode
        self.transplanted_into = transplanted_into
        self._detail = detail

    def status(self) -> AdapterStatus:
        if self.integration_mode == "REJECTED":
            return AdapterStatus.REJECTED
        return AdapterStatus.CONCEPT_TRANSPLANT

    def report(self) -> AdapterReport:
        return AdapterReport(
            engine=self.engine,
            integration_mode=self.integration_mode,
            status=self.status().value,
            transplanted_into=self.transplanted_into,
            detail=self._detail,
        )


__all__ = [
    "AdapterStatus", "AdapterReport", "SimulationEngineAdapter",
    "ConceptTransplantAdapter",
]
