"""Pure API surface for the Simulation Intelligence Layer.

These functions return JSON-serializable dicts with advisory stamps.  They do
NOT touch SQLite (the FastAPI route persists via ``scripts/persistence.py``),
keeping this whole package pure and side-effect-free.  Every function is
bounded, validates its inputs, and fails closed.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.simulation_intelligence.contracts import (
        SimulationRequest, MarketObservation, FreshnessStatus, stamp_advisory,
        CONTRACT_VERSION,
    )
    from scripts.simulation_intelligence.council import run_council
    from scripts.simulation_intelligence import engine_manifest as em
    from scripts.simulation_intelligence import scenario_library as scenarios
    from scripts.simulation_intelligence import feature_flags as flags
    from scripts.simulation_intelligence.adapters.registry import availability_report
except ModuleNotFoundError:  # pragma: no cover
    from simulation_intelligence.contracts import (  # type: ignore[no-redef]
        SimulationRequest, MarketObservation, FreshnessStatus, stamp_advisory,
        CONTRACT_VERSION,
    )
    from simulation_intelligence.council import run_council  # type: ignore[no-redef]
    from simulation_intelligence import engine_manifest as em  # type: ignore[no-redef]
    from simulation_intelligence import scenario_library as scenarios  # type: ignore[no-redef]
    from simulation_intelligence import feature_flags as flags  # type: ignore[no-redef]
    from simulation_intelligence.adapters.registry import availability_report  # type: ignore[no-redef]

_MAX_RETURNS = 512
_MAX_NARRATIVES = 64
_MAX_CATALYSTS = 64


def _num_list(value: Any, cap: int) -> list[float]:
    out: list[float] = []
    if not isinstance(value, (list, tuple)):
        return out
    for v in value[:cap]:
        try:
            f = float(v)
            if f == f:  # not NaN
                out.append(f)
        except (TypeError, ValueError):
            continue
    return out


def build_observation(payload: dict[str, Any]) -> MarketObservation:
    """Build a bounded, fail-closed MarketObservation from a request dict.

    Unknown/absent numeric fields stay ``None`` and are recorded in
    ``missing_fields`` so lenses fail closed rather than inventing values.
    """
    payload = payload or {}
    ticker = str(payload.get("ticker", "")).strip()[:32] or "UNKNOWN"
    market = str(payload.get("market", "UNKNOWN")).strip().upper()[:8] or "UNKNOWN"
    returns = _num_list(payload.get("returns"), _MAX_RETURNS)
    volumes = _num_list(payload.get("volumes"), _MAX_RETURNS)
    narratives = [str(s)[:80] for s in (payload.get("narrative_sources") or [])][:_MAX_NARRATIVES]
    catalysts = []
    for c in (payload.get("catalysts") or [])[:_MAX_CATALYSTS]:
        if isinstance(c, dict):
            catalysts.append({
                "id": str(c.get("id", c.get("name", "catalyst")))[:64],
                "name": str(c.get("name", ""))[:80],
                "magnitude": float(c.get("magnitude", c.get("strength", 0.0)) or 0.0),
            })
    dependencies = []
    for d in (payload.get("dependencies") or [])[:_MAX_CATALYSTS]:
        if isinstance(d, dict):
            dependencies.append({
                "name": str(d.get("name", d.get("ticker", "")))[:64],
                "weight": float(d.get("weight", 0.4) or 0.4),
                "kind": str(d.get("kind", "dependency"))[:32],
            })

    def _opt_num(key: str) -> float | None:
        v = payload.get(key)
        if v is None:
            return None
        try:
            f = float(v)
            return f if f == f else None
        except (TypeError, ValueError):
            return None

    freshness = str(payload.get("freshness_status", "")).strip().upper()
    if freshness not in {s.value for s in FreshnessStatus}:
        freshness = FreshnessStatus.UNKNOWN.value

    missing = []
    if not returns:
        missing.append("returns")
    if _opt_num("price") is None:
        missing.append("price")

    return MarketObservation(
        ticker=ticker, market=market,
        as_of=str(payload.get("as_of", ""))[:40],
        data_cutoff=str(payload.get("data_cutoff", ""))[:40],
        price=_opt_num("price"), prev_close=_opt_num("prev_close"),
        returns=returns, volumes=volumes,
        volatility=_opt_num("volatility"), spread_bps=_opt_num("spread_bps"),
        adv_usd=_opt_num("adv_usd"), sector=str(payload.get("sector", ""))[:48],
        catalysts=catalysts, dependencies=dependencies,
        narrative_sources=narratives,
        source_count=int(payload.get("source_count", len(narratives)) or 0),
        freshness_status=freshness, missing_fields=missing,
        provenance={k: str(v)[:64] for k, v in (payload.get("provenance") or {}).items()},
    )


def build_request(payload: dict[str, Any]) -> SimulationRequest:
    payload = payload or {}
    obs = build_observation(payload.get("observation", payload))
    seed = int(payload.get("seed", 0) or 0)
    max_runs = max(8, min(int(payload.get("max_runs", 256) or 256), flags.max_runs()))
    scen = [str(s)[:48] for s in (payload.get("scenarios") or [])][:flags.max_scenarios()]
    lenses = [str(l).upper()[:16] for l in (payload.get("requested_lenses") or [])][:6]
    return SimulationRequest(
        ticker=obs.ticker, market=obs.market, observation=obs,
        scenarios=scen, seed=seed, max_runs=max_runs,
        parent_signal_id=str(payload.get("parent_signal_id", ""))[:64],
        requested_lenses=lenses,
    )


# ---------------------------------------------------------------------------
# Read surfaces
# ---------------------------------------------------------------------------
def engines_report() -> dict[str, Any]:
    """Manifest + live adapter availability for all eighteen engines."""
    return stamp_advisory({
        "report": "simulation_engines",
        "manifest_version": em.MANIFEST_VERSION,
        "summary": em.summary(),
        "engines": em.as_dicts(),
        "availability": availability_report(),
    })


def scenarios_report() -> dict[str, Any]:
    return stamp_advisory({
        "report": "simulation_scenarios",
        "count": len(scenarios.catalog()),
        "default_scenario_ids": scenarios.default_scenario_ids(),
        "scenarios": scenarios.catalog(),
    })


def health_report() -> dict[str, Any]:
    avail = availability_report()
    return stamp_advisory({
        "report": "simulation_health",
        "contract_version": CONTRACT_VERSION,
        "sil_enabled": flags.sil_enabled(),
        "feature_flags": flags.snapshot(),
        "engine_count": avail["engine_count"],
        "engines_available_now": avail["available_now"],
        "engines_available_count": avail["available_count"],
        "manifest_version": em.MANIFEST_VERSION,
        "degraded_ok": True,
        "note": "The council runs fully with every optional engine unavailable.",
    })


# ---------------------------------------------------------------------------
# Run surface (pure — the route persists the result)
# ---------------------------------------------------------------------------
def run_simulation(payload: dict[str, Any], run_stress: bool = True) -> dict[str, Any]:
    """Run the six-lens council for a request payload. Pure + deterministic.

    Returns the council result dict (advisory-stamped).  Fails closed with a
    structured error if SIL is disabled.
    """
    if not flags.sil_enabled():
        return stamp_advisory({
            "report": "simulation_run",
            "ok": False,
            "error": "sil_disabled",
            "reason": "SIL_ENABLED is off; the simulation layer is failed closed.",
        })
    request = build_request(payload)
    result = run_council(request, run_stress=run_stress)
    out = result.to_dict()
    out["ok"] = True
    out["report"] = "simulation_run"
    return out


def council_for_observation(payload: dict[str, Any]) -> dict[str, Any]:
    """Convenience: run and return the council result for a ticker payload."""
    return run_simulation(payload, run_stress=True)


__all__ = [
    "build_observation", "build_request", "engines_report", "scenarios_report",
    "health_report", "run_simulation", "council_for_observation",
]
