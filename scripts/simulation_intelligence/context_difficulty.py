"""Context Difficulty Score — how hard was the situation the component handled?

A 9/10 on an easy, complete-data run is not a 9/10 on an adversarial, stale,
contradictory, high-volatility run. This module scores the *difficulty* of a
run's context so credit can be adjusted — but only ever to reward *correctly
handling* a hard input, never merely to reward a bad input.

Pure: stdlib only. Deterministic. Bounded [0, 1] (0 = trivial, 1 = maximal).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    from scripts.simulation_intelligence.contracts import MarketObservation
except ModuleNotFoundError:  # pragma: no cover
    from simulation_intelligence.contracts import MarketObservation  # type: ignore[no-redef]


def _clip(v: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, f)) if f == f else lo


# Twelve difficulty factors, each in [0,1]. Weights are relative.
_FACTORS: dict[str, float] = {
    "data_incompleteness": 1.3,
    "data_staleness": 1.2,
    "evidence_contradiction": 1.2,
    "volatility": 1.1,
    "regime_instability": 1.0,
    "actor_interaction": 0.9,
    "source_concentration": 1.1,
    "model_disagreement": 1.1,
    "scenario_complexity": 0.9,
    "engine_unavailability": 0.7,
    "runtime_degradation": 0.8,
    "tail_severity": 1.2,
}


@dataclass(slots=True)
class ContextDifficulty:
    score: float
    factors: dict[str, float] = field(default_factory=dict)
    band: str = "MODERATE"  # TRIVIAL / EASY / MODERATE / HARD / EXTREME
    dominant_factor: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score, "band": self.band,
            "dominant_factor": self.dominant_factor, "factors": self.factors,
        }


def _band(score: float) -> str:
    if score < 0.2:
        return "TRIVIAL"
    if score < 0.4:
        return "EASY"
    if score < 0.6:
        return "MODERATE"
    if score < 0.8:
        return "HARD"
    return "EXTREME"


def score_context(
    obs: MarketObservation,
    council: dict[str, Any] | None = None,
) -> ContextDifficulty:
    """Compute context difficulty from an observation and (optionally) a council
    result dict. Missing signals default to the *middle* (0.5) so an unknown
    context is neither trivially easy nor maximally hard."""
    council = council or {}
    f: dict[str, float] = {}

    # Data incompleteness: fraction of expected numeric fields absent.
    missing = list(getattr(obs, "missing_fields", []) or [])
    expected = 6.0  # price, returns, volumes, volatility, spread_bps, adv_usd
    f["data_incompleteness"] = _clip(len(missing) / expected)

    # Staleness.
    fresh = (getattr(obs, "freshness_status", "UNKNOWN") or "UNKNOWN").upper()
    f["data_staleness"] = {"FRESH": 0.0, "AGING": 0.5, "STALE": 1.0}.get(fresh, 0.6)

    # Volatility from recent returns dispersion (annualised-ish, capped).
    rets = [float(x) for x in (getattr(obs, "returns", []) or []) if x == x]
    if len(rets) >= 2:
        m = sum(rets) / len(rets)
        var = sum((x - m) ** 2 for x in rets) / (len(rets) - 1)
        vol = var ** 0.5
        f["volatility"] = _clip(vol / 0.04)  # 4% daily stdev ~ maximal
        # Regime instability: change in dispersion across halves.
        h = len(rets) // 2
        if h >= 2:
            def _sd(xs: list[float]) -> float:
                mm = sum(xs) / len(xs)
                return (sum((x - mm) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5
            a, b = _sd(rets[:h]), _sd(rets[h:])
            f["regime_instability"] = _clip(abs(b - a) / (max(a, b) + 1e-9))
        else:
            f["regime_instability"] = 0.5
    else:
        f["volatility"] = 0.5
        f["regime_instability"] = 0.5

    # Source concentration: few sources → high difficulty.
    sc = int(getattr(obs, "source_count", 0) or 0)
    f["source_concentration"] = _clip(1.0 - min(sc, 4) / 4.0)

    # Actor interaction: number of dependencies (more interacting actors = harder).
    deps = getattr(obs, "dependencies", []) or []
    f["actor_interaction"] = _clip(len(deps) / 8.0)

    # Council-derived factors (if a run is supplied).
    dis = council.get("disagreement_class", "")
    f["model_disagreement"] = {
        "CONSENSUS_ROBUST": 0.1, "CONSENSUS_FRAGILE": 0.5, "SPLIT_DECISION": 0.8,
        "MINORITY_TAIL_WARNING": 0.7, "SHARED_EVIDENCE_ILLUSION": 0.6,
        "INSUFFICIENT_INDEPENDENCE": 0.7, "SIMULATION_ONLY_CONSENSUS": 0.5,
    }.get(dis, 0.5)
    f["evidence_contradiction"] = _clip(f["model_disagreement"])  # proxy

    n_scen = len(council.get("stress_results", []) or [])
    f["scenario_complexity"] = _clip(n_scen / 12.0) if n_scen else 0.4

    engines = council.get("engine_availability", {}) or {}
    if engines:
        unavailable = sum(1 for v in engines.values()
                          if str(v).upper() in ("DISABLED", "UNAVAILABLE",
                                                "ENGINE_UNAVAILABLE"))
        f["engine_unavailability"] = _clip(unavailable / max(1, len(engines)))
    else:
        f["engine_unavailability"] = 0.3

    f["runtime_degradation"] = _clip(council.get("_runtime_degradation", 0.2))

    f["tail_severity"] = 1.0 if council.get("tail_warnings") else (
        0.6 if council.get("risk_block_engaged") else 0.3)

    total_w = sum(_FACTORS.values())
    score = sum(_clip(f.get(k, 0.5)) * w for k, w in _FACTORS.items()) / total_w
    score = round(_clip(score), 4)
    dominant = max(_FACTORS, key=lambda k: _clip(f.get(k, 0.5)) * _FACTORS[k])
    return ContextDifficulty(
        score=score, factors={k: round(_clip(f.get(k, 0.5)), 4) for k in _FACTORS},
        band=_band(score), dominant_factor=dominant,
    )


__all__ = ["ContextDifficulty", "score_context"]
