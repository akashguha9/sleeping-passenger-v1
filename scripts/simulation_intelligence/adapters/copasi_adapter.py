"""Optional COPASI / basico adapter — the ONE real NATIVE_LIBRARY integration.

COPASI (via ``copasi-basico``, Artistic-License-2.0) is the only chemistry/
biology engine honestly installable natively on Windows + Linux + Python 3.13.
It is behind the ``SIL_COPASI_ENABLED`` flag and the optional ``sil-copasi``
extra; when either is missing the biology lens uses its native feedback model.

This adapter lazily imports ``basico`` inside the call so importing the SIL
package never requires it, and it degrades cleanly to ``available=False`` when
the library is absent — no exception escapes.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.simulation_intelligence.adapters.base import (
        SimulationEngineAdapter, AdapterStatus, AdapterReport,
    )
    from scripts.simulation_intelligence import feature_flags as flags
except ModuleNotFoundError:  # pragma: no cover
    from simulation_intelligence.adapters.base import (  # type: ignore[no-redef]
        SimulationEngineAdapter, AdapterStatus, AdapterReport,
    )
    from simulation_intelligence import feature_flags as flags  # type: ignore[no-redef]


def _basico_importable() -> bool:
    try:
        import importlib.util
        return importlib.util.find_spec("basico") is not None
    except Exception:  # pragma: no cover
        return False


class CopasiAdapter(SimulationEngineAdapter):
    engine = "COPASI"
    integration_mode = "NATIVE_LIBRARY"
    transplanted_into = "biology"

    def is_available(self) -> bool:
        return flags.copasi_enabled() and _basico_importable()

    def status(self) -> AdapterStatus:
        if not flags.copasi_enabled():
            return AdapterStatus.DISABLED
        if not _basico_importable():
            return AdapterStatus.UNAVAILABLE
        return AdapterStatus.AVAILABLE

    def report(self) -> AdapterReport:
        st = self.status()
        detail = {
            AdapterStatus.DISABLED: "SIL_COPASI_ENABLED is off (default)",
            AdapterStatus.UNAVAILABLE: "copasi-basico not installed (pip install copasi-basico)",
            AdapterStatus.AVAILABLE: "basico present; biology lens may use ODE feedback solver",
        }.get(st, "")
        return AdapterReport(
            engine=self.engine, integration_mode=self.integration_mode,
            status=st.value, transplanted_into=self.transplanted_into, detail=detail,
        )


def solve_feedback_equilibrium(positive: float, negative: float) -> dict[str, Any]:
    """Solve a tiny positive/negative feedback ODE to a homeostatic equilibrium.

    If COPASI/basico is available and enabled, build a 2-species reaction network
    and integrate it; otherwise return ``available=False`` so the caller uses its
    native model.  Never raises.
    """
    adapter = CopasiAdapter()
    if not adapter.is_available():
        return {"available": False, "reason": adapter.status().value}
    try:  # pragma: no cover - exercised only when basico is installed
        import basico  # type: ignore
        model = basico.new_model(name="sil_feedback")
        basico.add_species("Attention", initial_concentration=1.0)
        basico.add_species("Resistance", initial_concentration=1.0)
        basico.add_reaction("grow", "Attention -> 2 * Attention")
        basico.set_reaction_parameters("(grow).k1", value=max(1e-3, float(positive)))
        basico.add_reaction("damp", "Attention -> Resistance")
        basico.set_reaction_parameters("(damp).k1", value=max(1e-3, float(negative)))
        result = basico.run_steadystate()
        att = float(basico.get_species("Attention").initial_concentration.iloc[0])
        equilibrium = max(0.0, min(1.0, 1.0 / (1.0 + att)))
        return {"available": True, "equilibrium": round(equilibrium, 4), "engine": "copasi"}
    except Exception as exc:
        return {"available": False, "reason": f"copasi_error:{type(exc).__name__}"}


__all__ = ["CopasiAdapter", "solve_feedback_equilibrium"]
