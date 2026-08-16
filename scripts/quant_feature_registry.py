"""Quant hackathon — canonical signal state vector + feature registry.

Mission 1.  ONE source of truth for every feature entering

    x_{i,t} = [P, Ṗ, P̈, Q, CES, D, Ḋ, NIS, PIS, CIS, SIS, IIR, TP, B,
               WF, PEG, HL, EXP, MOM, VOL, LIQ]

Each FeatureSpec documents: domain/units/bounds, null semantics,
provenance module, expected monotonicity vs forward abnormal return,
lagging rule, leakage risk, and epistemic + calibration status (Rule
Zero labels).  ``assemble_state_vector`` validates bounds and preserves
UNKNOWN (None) — a missing feature is NEVER coerced to 0.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Rule Zero epistemic labels.
DERIVED = "DERIVED"
ESTIMATED = "ESTIMATED"
CALIBRATED = "CALIBRATED"
HEURISTIC = "HEURISTIC"
EXPERIMENTAL = "EXPERIMENTAL"
IDENTIFIED = "IDENTIFIED"

RESEARCH_ONLY = "RESEARCH_ONLY"
UNCALIBRATED = "UNCALIBRATED"

OK = "OK"
UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    description: str
    domain: str                 # e.g. "[0,1]", "R", "[0,100]"
    units: str
    bounds: tuple[float | None, float | None]
    null_semantics: str         # what None means; never silently 0
    provenance: str             # producing module.function
    monotonicity_hypothesis: str  # expected sign vs forward AR (HEURISTIC)
    lag_rule: str               # what timestamp the value must precede
    leakage_risk: str
    epistemic_status: str
    calibration_status: str = UNCALIBRATED
    transformations: tuple[str, ...] = field(default_factory=tuple)


def _spec(name: str, desc: str, domain: str, units: str,
          bounds: tuple[float | None, float | None], prov: str,
          mono: str, epi: str, leak: str = "low — point-in-time input",
          **kw: Any) -> FeatureSpec:
    return FeatureSpec(
        name=name, description=desc, domain=domain, units=units,
        bounds=bounds, provenance=prov, monotonicity_hypothesis=mono,
        lag_rule="t_available <= t (walk-forward enforced)",
        leakage_risk=leak, epistemic_status=epi,
        null_semantics="None == UNKNOWN (input unavailable); never 0", **kw)


FEATURE_REGISTRY: dict[str, FeatureSpec] = {s.name: s for s in [
    _spec("P", "event probability level", "[0,1]", "probability", (0.0, 1.0),
          "kalshi/polymarket adapters", "none (level alone uninformative)",
          DERIVED),
    _spec("P_dot", "probability velocity dP/dt", "R", "prob/day",
          (None, None),
          "quant_statistics_engine.standardized_shock + "
          "regime_transition_market_state_engine.probability_dynamics",
          "+ for positively exposed names (HEURISTIC)", DERIVED),
    _spec("P_ddot", "probability acceleration d2P/dt2", "R", "prob/day^2",
          (None, None),
          "regime_transition_market_state_engine.probability_dynamics",
          "unknown; consensus-break hypothesis", HEURISTIC),
    _spec("Z_P", "standardized probability shock", "R", "z-units",
          (None, None), "quant_statistics_engine.standardized_shock",
          "+ (larger shock -> larger repricing) (HEURISTIC)", DERIVED,
          leak="uses strictly-prior window moments"),
    _spec("Q", "market quality / information reliability", "[0,100]|None",
          "score", (0.0, 100.0),
          "regime_transition_market_state_engine.venue_quality_score",
          "moderator: signal validity increases with Q", HEURISTIC),
    _spec("CES", "contract equivalence score", "[0,100]|None", "score",
          (0.0, 100.0),
          "regime_transition_contract_equivalence_score",
          "gate: divergence valid only above floor", HEURISTIC),
    _spec("D", "cross-venue divergence |P_a-P_b|", "[0,1]", "probability",
          (0.0, 1.0),
          "regime_transition_market_state_engine.divergence_dynamics",
          "unknown — information vs noise untested", HEURISTIC),
    _spec("D_dot", "divergence velocity dD/dt", "R", "prob/day",
          (None, None),
          "regime_transition_market_state_engine.divergence_dynamics",
          "+ widening gap hypothesis", HEURISTIC),
    _spec("NIS", "narrative instability score", "[0,100]|None", "score",
          (0.0, 100.0), "regime_transition_flip_engine",
          "+ pre-transition fragility (HEURISTIC)", HEURISTIC),
    _spec("PIS", "policy inertia score", "[0,100]|None", "score",
          (0.0, 100.0), "regime_transition_inertia_engine",
          "moderator: durability of trajectory", HEURISTIC),
    _spec("CIS", "capital inertia score", "[0,100]|None", "score",
          (0.0, 100.0), "regime_transition_inertia_engine",
          "moderator: fundamental persistence", HEURISTIC),
    _spec("SIS", "supply-chain inertia score", "[0,100]|None", "score",
          (0.0, 100.0), "regime_transition_inertia_engine",
          "+ scarcity/pricing-power channel", HEURISTIC),
    _spec("IIR", "impulse-to-inertia ratio", "[0,inf)", "ratio",
          (0.0, None), "regime_transition_inertia_engine",
          "+ regime-threat hypothesis", HEURISTIC),
    _spec("TP", "threshold pressure", "[0,inf)", "ratio", (0.0, None),
          "regime_transition_titration_engine.threshold_pressure",
          "+ nonlinear near transition (HEURISTIC)", HEURISTIC),
    _spec("B", "remaining buffer", "[0,inf)|None", "capacity units",
          (0.0, None), "regime_transition_titration_engine.buffer_state",
          "- (depleted buffer -> higher sensitivity)", HEURISTIC),
    _spec("WF", "wavefront distance (expected arrival - today)", "R",
          "days", (None, None),
          "regime_transition_wave_engine.wavefront",
          "+ WFD>0 = ahead of wave (HEURISTIC)", HEURISTIC),
    _spec("PEG", "probability-to-equity propagation gap", "R",
          "log-return units", (None, None),
          "quant_peg_research_engine.peg_value",
          "+ open gap -> forward AR (PRIMARY ALPHA HYPOTHESIS)",
          EXPERIMENTAL),
    _spec("PEG_Z", "volatility-normalized PEG", "R", "z-units",
          (None, None), "quant_peg_research_engine.peg_value",
          "+ (normalized form of the same hypothesis)", EXPERIMENTAL),
    _spec("HL", "remaining information half-life fraction", "[0,1]|None",
          "fraction", (0.0, 1.0),
          "quant_statistics_engine.fit_exponential_decay",
          "moderator: priority decays with age", HEURISTIC),
    _spec("EXP", "signed economic exposure X_{i,e}", "[-1,1]|None",
          "fraction", (-1.0, 1.0),
          "prediction_market_shock_engine frozen map / "
          "regime_transition_wave_engine",
          "sign-preserving multiplier on event impact", HEURISTIC,
          leak="must be frozen BEFORE the event window"),
    _spec("MOM", "trailing 5-bar log return (momentum control)", "R",
          "log-return", (None, None), "quant_return_engine.log_return",
          "baseline control — signal must beat it", DERIVED),
    _spec("VOL", "realized daily volatility", "[0,inf)", "log-return/day",
          (0.0, None), "quant_return_engine.daily_volatility",
          "regime conditioner; PEG_Z denominator", DERIVED),
    _spec("LIQ", "average volume (liquidity proxy)", "[0,inf)|None",
          "shares/day", (0.0, None), "signal_events market_data payload",
          "moderator: thin names untradeable", DERIVED),
]}


def assemble_state_vector(inputs: dict[str, Any]) -> dict[str, Any]:
    """Validate raw inputs against the registry into a canonical vector.

    Unknown feature names are rejected (single source of truth).  Values
    outside documented bounds are flagged BOUNDS_VIOLATION, not clipped
    silently.  None survives as None (UNKNOWN != 0).
    """
    vector: dict[str, Any] = {}
    violations: list[str] = []
    for name, value in inputs.items():
        spec = FEATURE_REGISTRY.get(name)
        if spec is None:
            violations.append(f"unregistered feature: {name}")
            continue
        if value is None:
            vector[name] = None
            continue
        lo, hi = spec.bounds
        if not isinstance(value, (int, float)):
            violations.append(f"{name}: non-numeric value {value!r}")
            continue
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            violations.append(
                f"{name}: {value} outside bounds [{lo}, {hi}]")
            continue
        vector[name] = float(value)
    known = [k for k, v in vector.items() if v is not None]
    return {"status": OK if not violations else "BOUNDS_VIOLATION",
            "vector": vector,
            "known_features": sorted(known),
            "unknown_features": sorted(k for k, v in vector.items()
                                       if v is None),
            "coverage": round(len(known) / max(1, len(vector)), 4),
            "violations": violations,
            "signal_class": RESEARCH_ONLY}


def registry_manifest() -> list[dict[str, Any]]:
    """Serializable registry dump for reports/audits."""
    return [{
        "name": s.name, "description": s.description, "domain": s.domain,
        "units": s.units, "provenance": s.provenance,
        "monotonicity_hypothesis": s.monotonicity_hypothesis,
        "epistemic_status": s.epistemic_status,
        "calibration_status": s.calibration_status,
        "null_semantics": s.null_semantics,
        "leakage_risk": s.leakage_risk,
    } for s in FEATURE_REGISTRY.values()]
