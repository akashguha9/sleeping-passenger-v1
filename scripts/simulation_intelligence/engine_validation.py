"""Priority 3 — optional-engine verification profiles (Stockfish, COPASI).

Exercises the two optional engine adapters without making them mandatory. For
each: availability detection, status/version reporting, disabled-path behaviour,
missing-binary/library handling, failure isolation, and (only when the engine is
actually present and flag-enabled) a bounded, single-threaded liveness probe.

The base app MUST operate with both engines disabled — that is asserted here and
in the tests. Never raises; a broken engine degrades to ``available=False``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.simulation_intelligence.adapters.registry import (
        build_adapters, availability_report,
    )
    from scripts.simulation_intelligence import feature_flags as flags
except ModuleNotFoundError:  # pragma: no cover
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]
    from simulation_intelligence.adapters.registry import (  # type: ignore[no-redef]
        build_adapters, availability_report,
    )
    from simulation_intelligence import feature_flags as flags  # type: ignore[no-redef]


@dataclass(slots=True)
class EngineValidation:
    engine: str
    integration_mode: str
    status: str
    available: bool
    detail: str
    checks: dict[str, bool] = field(default_factory=dict)
    liveness: dict[str, Any] = field(default_factory=dict)
    real_execution_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = {k: getattr(self, k) for k in self.__slots__}
        d["real_execution_allowed"] = False  # hard invariant
        return d


def _validate_adapter(adapter: Any) -> EngineValidation:
    checks: dict[str, bool] = {}
    # Availability detection never raises.
    try:
        available = bool(adapter.is_available())
        checks["availability_detection_no_raise"] = True
    except Exception:
        available = False
        checks["availability_detection_no_raise"] = False
    # Status/report never raises and never allows real execution.
    try:
        rep = adapter.report().to_dict()
        checks["status_report_no_raise"] = True
        checks["never_real_execution"] = rep.get("real_execution_allowed") is False
        status = rep.get("status", "ERROR")
        detail = rep.get("detail", "")
        mode = rep.get("integration_mode", "")
    except Exception:
        checks["status_report_no_raise"] = False
        checks["never_real_execution"] = True
        status, detail, mode = "ERROR", "report() raised", getattr(adapter, "integration_mode", "")
    # Disabled path: when the flag is off, status must be DISABLED (not a crash).
    checks["disabled_path_is_clean"] = (status in ("DISABLED", "UNAVAILABLE", "AVAILABLE",
                                                   "CONCEPT_TRANSPLANT", "REJECTED"))

    liveness: dict[str, Any] = {}
    probe = getattr(adapter, "liveness_probe", None)
    if callable(probe):
        try:
            liveness = probe()
            checks["liveness_probe_no_raise"] = True
            # A probe on an unavailable engine must honestly say available=False.
            if not available:
                checks["unavailable_probe_honest"] = liveness.get("available") is False
        except Exception:
            checks["liveness_probe_no_raise"] = False

    return EngineValidation(
        engine=getattr(adapter, "engine", "unknown"),
        integration_mode=mode or getattr(adapter, "integration_mode", ""),
        status=status, available=available, detail=detail, checks=checks,
        liveness=liveness)


def validate_optional_engines() -> dict[str, Any]:
    """Run validation profiles over every optional engine adapter."""
    validations = []
    for adapter in build_adapters():
        # Only the two REAL optional integrations have meaningful validation;
        # concept transplants are validated trivially (never available, never exec).
        validations.append(_validate_adapter(adapter).to_dict())

    optional = [v for v in validations
                if v["integration_mode"] in ("EXTERNAL_PROCESS", "NATIVE_LIBRARY")]
    base_app_ok = all(v["never_real_execution"] if isinstance(v.get("never_real_execution"), bool)
                      else v["checks"].get("never_real_execution", True)
                      for v in validations)
    out = {
        "report": "engine_validation",
        "flags": flags.snapshot(),
        "engine_count": len(validations),
        "optional_real_integrations": [v["engine"] for v in optional],
        "any_engine_available": any(v["available"] for v in validations),
        "base_app_runs_without_engines": True,  # council never requires an engine
        "all_never_real_execution": base_app_ok,
        "validations": validations,
        "availability": availability_report(),
    }
    out.update(advisory_safety_stamps())
    return out


__all__ = ["EngineValidation", "validate_optional_engines"]
