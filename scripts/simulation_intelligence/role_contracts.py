"""Versioned, immutable component role contracts for the Role-Adjusted
Contribution Rating (RACR) system — the "Kanté Index".

Central idea (a conceptual analogy only — see docs/kante_index_methodology.md):
an elite defensive midfielder can earn a top match rating without scoring or
assisting, because his *role* is interception, recovery, error prevention and
protecting the whole system. Sleeping Passenger's components must likewise be
judged against the job assigned to them, not against trade execution or realised
returns — which they are explicitly forbidden from doing.

Purity contract (enforced by tests): stdlib + ``advisory_contract`` only. No
sqlite, no network, no broker SDK, no FastAPI, no frontend. Role contracts are
*declared before evaluation* and their dimension weights are **immutable** — a
component can never pick an easier role after seeing its results.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]

# Bump on any breaking change to a contract shape or a weight template.  Every
# rating carries this so a stored rating is tied to the contract it was scored
# against.
ROLE_CONTRACT_VERSION = "racr-1.0.0"


class RoleDimension(str, Enum):
    """The 20 RACR dimensions. Every component is scored on all 20; role weights
    decide which ones actually matter for that component."""

    ROLE_FIDELITY = "role_fidelity"
    COVERAGE = "coverage"
    RISK_INTERCEPTION = "risk_interception"
    ERROR_PREVENTION = "error_prevention"
    DECISION_INFLUENCE = "decision_influence"
    RELIABILITY = "reliability"
    CONSISTENCY = "consistency"
    CONTEXT_DIFFICULTY = "context_difficulty"
    RECOVERY_ABILITY = "recovery_ability"
    COLLABORATION = "collaboration"
    INFORMATION_EFFICIENCY = "information_efficiency"
    UNCERTAINTY_HANDLING = "uncertainty_handling"
    EXPLAINABILITY = "explainability"
    OPERATOR_USEFULNESS = "operator_usefulness"
    RESOURCE_EFFICIENCY = "resource_efficiency"
    EVIDENCE_QUALITY = "evidence_quality"
    CALIBRATION_INTEGRITY = "calibration_integrity"
    ADVERSARIAL_RESILIENCE = "adversarial_resilience"
    RUNTIME_REACH = "runtime_reach"
    REGRESSION_RESISTANCE = "regression_resistance"


ALL_DIMENSIONS: tuple[str, ...] = tuple(d.value for d in RoleDimension)


class RatingSupport(str, Enum):
    """Score-quality labels (anti-gaming). A score is only as trustworthy as the
    evidence behind it."""

    SUPPORTED = "SUPPORTED"          # evidence-linked, adequate sample
    LOW_SAMPLE = "LOW_SAMPLE"        # too few observations to trust
    PROXY_HEAVY = "PROXY_HEAVY"      # mostly proxy evidence, little measured
    UNSUPPORTED = "UNSUPPORTED"      # no evidence backing the score


class EvidenceGrade(str, Enum):
    """How grounded a rating's evidence is (parallels the SIL evidence labels but
    scoped to *ratings*, not simulation outputs)."""

    MEASURED = "MEASURED"            # backed by runtime measurement/tests
    DERIVED = "DERIVED"              # computed from measured signals
    PROXY = "PROXY"                  # stand-in metric
    SIMULATED = "SIMULATED"          # from simulation only
    NONE = "NONE"                    # no evidence


class RoleTemplate(str, Enum):
    """A component's role family. Fixes which dimensions carry weight."""

    SIM_LENS = "SIM_LENS"
    COUNCIL = "COUNCIL"
    RISK_ENGINE = "RISK_ENGINE"
    CALIBRATION = "CALIBRATION"
    EVIDENCE_PROVENANCE = "EVIDENCE_PROVENANCE"
    SCENARIO_GENERATOR = "SCENARIO_GENERATOR"
    STRESS_TESTING = "STRESS_TESTING"
    REPLAY = "REPLAY"
    OPERATOR_FRONTEND = "OPERATOR_FRONTEND"
    ADAPTER = "ADAPTER"
    SIGNAL_REACTOR = "SIGNAL_REACTOR"
    SIGNAL_BRIDGE = "SIGNAL_BRIDGE"


def _w(**kw: float) -> dict[str, float]:
    """Build a full 20-dimension weight vector: named dims get their weight, the
    rest get a small floor of 0.1 (nothing is entirely irrelevant, but role
    focus dominates). Weights are relative; RACR normalises them."""
    base = {d: 0.1 for d in ALL_DIMENSIONS}
    for name, val in kw.items():
        if name not in base:
            raise KeyError(f"unknown RACR dimension: {name}")
        base[name] = float(val)
    return base


# ---------------------------------------------------------------------------
# Role weight templates — HIGH weight on the dimensions a role is responsible
# for, LOW/floor weight on the rest. Declared here, immutable, versioned.
#
# A risk engine is NOT rewarded for producing opportunities; a lens is NOT
# punished for not executing trades; a frontend is judged on operator clarity.
# ---------------------------------------------------------------------------
D = RoleDimension
_ROLE_WEIGHTS: dict[str, dict[str, float]] = {
    RoleTemplate.SIM_LENS.value: _w(
        coverage=2.0, uncertainty_handling=1.8, decision_influence=1.5,
        role_fidelity=1.8, evidence_quality=1.6, adversarial_resilience=1.3,
        context_difficulty=1.3, collaboration=1.2, information_efficiency=1.2,
        runtime_reach=1.4, regression_resistance=1.2,
    ),
    RoleTemplate.COUNCIL.value: _w(
        role_fidelity=1.8, risk_interception=1.8, error_prevention=1.8,
        explainability=1.8, decision_influence=1.6, uncertainty_handling=1.5,
        evidence_quality=1.6, consistency=1.5, adversarial_resilience=1.5,
        runtime_reach=1.5, regression_resistance=1.3,
    ),
    RoleTemplate.RISK_ENGINE.value: _w(
        risk_interception=2.4, error_prevention=2.2, reliability=1.8,
        adversarial_resilience=1.8, calibration_integrity=1.6, consistency=1.6,
        role_fidelity=1.8, runtime_reach=1.4,
    ),
    RoleTemplate.CALIBRATION.value: _w(
        calibration_integrity=2.4, evidence_quality=2.0, reliability=1.6,
        role_fidelity=1.8, adversarial_resilience=1.5, regression_resistance=1.4,
        information_efficiency=1.3, runtime_reach=1.2,
    ),
    RoleTemplate.EVIDENCE_PROVENANCE.value: _w(
        evidence_quality=2.2, information_efficiency=1.8, error_prevention=1.6,
        role_fidelity=1.8, collaboration=1.6, adversarial_resilience=1.5,
        explainability=1.4, runtime_reach=1.4,
    ),
    RoleTemplate.SCENARIO_GENERATOR.value: _w(
        coverage=2.4, context_difficulty=1.6, role_fidelity=1.6,
        information_efficiency=1.4, adversarial_resilience=1.4, runtime_reach=1.3,
        regression_resistance=1.3,
    ),
    RoleTemplate.STRESS_TESTING.value: _w(
        risk_interception=2.0, coverage=1.8, adversarial_resilience=1.8,
        uncertainty_handling=1.6, role_fidelity=1.6, resource_efficiency=1.4,
        runtime_reach=1.3,
    ),
    RoleTemplate.REPLAY.value: _w(
        reliability=2.2, consistency=2.0, regression_resistance=1.8,
        role_fidelity=1.8, recovery_ability=1.6, runtime_reach=1.3,
    ),
    RoleTemplate.OPERATOR_FRONTEND.value: _w(
        operator_usefulness=2.4, explainability=2.2, error_prevention=1.8,
        role_fidelity=1.6, uncertainty_handling=1.2, runtime_reach=1.4,
    ),
    RoleTemplate.ADAPTER.value: _w(
        reliability=2.0, adversarial_resilience=1.8, recovery_ability=1.8,
        role_fidelity=1.8, resource_efficiency=1.5, evidence_quality=1.4,
        runtime_reach=1.2,
    ),
    RoleTemplate.SIGNAL_REACTOR.value: _w(
        risk_interception=1.8, error_prevention=1.8, reliability=1.6,
        role_fidelity=1.6, information_efficiency=1.4, runtime_reach=1.6,
        coverage=1.4,
    ),
    RoleTemplate.SIGNAL_BRIDGE.value: _w(
        role_fidelity=2.0, information_efficiency=1.8, error_prevention=1.8,
        reliability=1.6, evidence_quality=1.6, runtime_reach=1.8,
        recovery_ability=1.3,
    ),
}


@dataclass(frozen=True, slots=True)
class ComponentRoleContract:
    """One component's immutable role contract. Declared before evaluation."""

    component_id: str
    component_name: str
    role_template: str  # RoleTemplate value
    primary_mandate: str
    secondary_mandates: tuple[str, ...] = ()
    forbidden_mandates: tuple[str, ...] = ()
    responsibilities: tuple[str, ...] = ()
    non_responsibilities: tuple[str, ...] = ()
    required_inputs: tuple[str, ...] = ()
    expected_outputs: tuple[str, ...] = ()
    failure_modes: tuple[str, ...] = ()
    success_events: tuple[str, ...] = ()
    prevention_events: tuple[str, ...] = ()
    recovery_events: tuple[str, ...] = ()
    reliability_expectation: float = 0.95
    evidence_requirements: tuple[str, ...] = ()
    #: Honest ceiling on the Role-Adjusted Performance score for this component
    #: given current evidence maturity. A lens with no measured outcomes cannot
    #: be perfect. Never exceeded by the RACR engine.
    honest_ceiling: float = 9.5
    contract_version: str = ROLE_CONTRACT_VERSION

    @property
    def dimension_weights(self) -> dict[str, float]:
        """Immutable, role-derived weight vector (returns a fresh copy)."""
        return dict(_ROLE_WEIGHTS.get(self.role_template, _w()))

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["dimension_weights"] = self.dimension_weights
        d.update(advisory_safety_stamps())
        return d


# Universal forbidden mandates — every component is barred from these.
_FORBIDDEN = (
    "place a broker order", "route an order", "size a position automatically",
    "execute a trade", "raise ai_execution_count", "unlock execution_gate",
    "present simulated evidence as measured",
)


def _c(**kw: Any) -> ComponentRoleContract:
    kw.setdefault("forbidden_mandates", _FORBIDDEN)
    return ComponentRoleContract(**kw)


# ---------------------------------------------------------------------------
# The component registry — 16 components with declared role contracts.
# ---------------------------------------------------------------------------
_LENS_CONTRACT = dict(
    role_template=RoleTemplate.SIM_LENS.value,
    responsibilities=("interpret market state through its domain",
                      "surface scenario branches", "flag its main risk",
                      "quantify uncertainty", "label evidence honestly"),
    non_responsibilities=("final vote", "trade execution", "position sizing",
                          "realised returns"),
    required_inputs=("MarketObservation",),
    expected_outputs=("LensResult",),
    failure_modes=("inventing data when inputs missing", "unbounded confidence",
                   "silent error"),
    success_events=("orthogonal scenario surfaced", "uncertainty reduced",
                    "tail risk flagged"),
    prevention_events=("false confidence prevented via INSUFFICIENT_DATA",),
    recovery_events=("trapped exception → error result, council survives",),
    evidence_requirements=("deterministic re-run", "ablation marginal contribution"),
    honest_ceiling=9.4,
)

_REGISTRY: dict[str, ComponentRoleContract] = {}


def _register(contract: ComponentRoleContract) -> None:
    _REGISTRY[contract.component_id] = contract


for _dom, _name in (("PHYSICS", "Physics lens"), ("CHEMISTRY", "Chemistry lens"),
                    ("BIOLOGY", "Biology lens"), ("RACING", "Racing lens"),
                    ("CHESS", "Chess lens"), ("POKER", "Poker lens")):
    _register(_c(component_id=f"lens.{_dom.lower()}", component_name=_name,
                 primary_mandate=f"interpret the candidate through the {_name} "
                                 "and contribute orthogonal, honestly-labelled insight",
                 **_LENS_CONTRACT))

_register(_c(
    component_id="council", component_name="Six-lens council",
    role_template=RoleTemplate.COUNCIL.value,
    primary_mandate="aggregate six lenses without naive averaging and produce an "
                    "explainable advisory stance with RISK_BLOCK precedence",
    secondary_mandates=("preserve minority + tail warnings",
                        "penalise correlated/shared evidence"),
    responsibilities=("dedup evidence", "penalise correlation/staleness/missing",
                      "risk-block precedence", "classify disagreement",
                      "explain every weight"),
    non_responsibilities=("execution", "sizing", "return generation"),
    required_inputs=("SimulationRequest", "six LensResults"),
    expected_outputs=("SimulationCouncilResult",),
    failure_modes=("naive averaging", "suppressed minority warning",
                   "false risk block", "shared-evidence illusion"),
    success_events=("risk block overrode attractive aggregate",
                    "minority tail warning preserved"),
    prevention_events=("correlated agreement penalised", "duplicate evidence removed"),
    recovery_events=("one lens error isolated, council still returns"),
    evidence_requirements=("ablation", "adversarial probe", "determinism"),
    honest_ceiling=9.3,
))

_register(_c(
    component_id="risk_engine", component_name="Risk interception layer",
    role_template=RoleTemplate.RISK_ENGINE.value,
    primary_mandate="intercept tail risk and prevent unsafe confidence; fail closed",
    responsibilities=("detect tail risk", "engage RISK_BLOCK", "fail closed"),
    non_responsibilities=("opportunity generation", "upside selection", "returns"),
    required_inputs=("lens results", "stress results"),
    expected_outputs=("risk_block decision", "tail warnings"),
    failure_modes=("missed tail risk", "false risk block", "silent pass"),
    success_events=("tail risk intercepted before aggregation",),
    prevention_events=("unsafe recommendation prevented",),
    recovery_events=("degraded-data path stays fail-closed",),
    evidence_requirements=("tail precision/recall", "false-risk-block rate"),
    honest_ceiling=9.4,
))

_register(_c(
    component_id="calibration", component_name="Leakage-safe calibration harness",
    role_template=RoleTemplate.CALIBRATION.value,
    primary_mandate="link SIL predictions to leakage-safe outcomes and report honest "
                    "calibration; never auto-promote evidence grades",
    responsibilities=("record predictions with cutoff", "enforce outcome windows",
                      "compute Brier/ECE", "resist leakage"),
    non_responsibilities=("promoting labels automatically", "sizing"),
    required_inputs=("SIL predictions", "resolved outcomes"),
    expected_outputs=("calibration record", "tail precision/recall"),
    failure_modes=("look-ahead leakage", "duplicate outcomes", "auto-promotion"),
    success_events=("leakage attempt blocked", "honest low score reported"),
    prevention_events=("post-outcome mutation prevented",),
    recovery_events=("insufficient sample → LOW_SAMPLE, no crash"),
    evidence_requirements=("leakage-safe cohort", "adequate real sample"),
    honest_ceiling=9.3,
))

_register(_c(
    component_id="evidence_provenance", component_name="Evidence provenance system",
    role_template=RoleTemplate.EVIDENCE_PROVENANCE.value,
    primary_mandate="deduplicate evidence and measure source concentration so shared "
                    "inputs cannot masquerade as independent corroboration",
    responsibilities=("fingerprint evidence", "dedup", "Herfindahl concentration"),
    non_responsibilities=("voting", "execution"),
    required_inputs=("evidence packets",),
    expected_outputs=("dedup report", "concentration score"),
    failure_modes=("double-counting", "missed shared evidence"),
    success_events=("shared-evidence illusion detected",),
    prevention_events=("duplicate evidence removed before weighting",),
    recovery_events=(),
    evidence_requirements=("dedup unit tests",),
    honest_ceiling=9.4,
))

_register(_c(
    component_id="scenario_generator", component_name="Scenario library",
    role_template=RoleTemplate.SCENARIO_GENERATOR.value,
    primary_mandate="provide broad, orthogonal India/US stress + operational scenarios",
    responsibilities=("cover risk families", "deterministic + stochastic variants"),
    non_responsibilities=("execution", "returns"),
    required_inputs=("scenario ids",),
    expected_outputs=("SimulationScenario set",),
    failure_modes=("redundant coverage", "missing a risk family"),
    success_events=("scenario surfaced a risk another lens missed",),
    prevention_events=(),
    recovery_events=(),
    evidence_requirements=("coverage count", "redundancy penalty"),
    honest_ceiling=9.3,
))

_register(_c(
    component_id="stress_testing", component_name="Bounded Monte-Carlo stress suite",
    role_template=RoleTemplate.STRESS_TESTING.value,
    primary_mandate="apply scenarios under bounded stochastic runs and surface tail impact",
    responsibilities=("bounded Monte-Carlo", "tail bands", "survived/impact"),
    non_responsibilities=("execution", "sizing"),
    required_inputs=("observation", "scenarios", "seed"),
    expected_outputs=("StressTestResult set",),
    failure_modes=("unbounded runtime", "coarse tail hidden as precise"),
    success_events=("unstable scenario surfaced",),
    prevention_events=("simulation timed out safely",),
    recovery_events=(),
    evidence_requirements=("bounded-runs test", "determinism"),
    honest_ceiling=9.2,
))

_register(_c(
    component_id="replay", component_name="Deterministic replay",
    role_template=RoleTemplate.REPLAY.value,
    primary_mandate="reproduce a stored run exactly from its seed + data cutoff",
    responsibilities=("deterministic re-run", "byte-identical council"),
    non_responsibilities=("execution",),
    required_inputs=("stored run",),
    expected_outputs=("replayed council result", "match verdict"),
    failure_modes=("non-deterministic replay presented as deterministic",),
    success_events=("deterministic replay matched",),
    prevention_events=(),
    recovery_events=("corrupted replay metadata → structured error"),
    evidence_requirements=("replay-match test",),
    honest_ceiling=9.5,
))

_register(_c(
    component_id="operator_frontend", component_name="Simulation Lab operator UI",
    role_template=RoleTemplate.OPERATOR_FRONTEND.value,
    primary_mandate="make simulated-vs-measured evidence and warnings unmistakable so "
                    "the operator cannot misinterpret the council",
    responsibilities=("show warnings", "distinguish measured/simulated",
                      "surface honest ceilings", "link scores to evidence"),
    non_responsibilities=("execution", "sizing", "hiding failures"),
    required_inputs=("API responses",),
    expected_outputs=("rendered decision surface",),
    failure_modes=("false confidence shown", "decorative dashboard"),
    success_events=("operator error prevented",),
    prevention_events=("misinterpretation prevented via clear labelling",),
    recovery_events=("finite loading/empty states, no hang"),
    evidence_requirements=("render tests", "accessibility"),
    honest_ceiling=9.1,
))

for _eid, _ename in (("adapter.stockfish", "Stockfish UCI adapter"),
                     ("adapter.copasi", "COPASI/basico adapter")):
    _register(_c(
        component_id=_eid, component_name=_ename,
        role_template=RoleTemplate.ADAPTER.value,
        primary_mandate="report availability honestly and degrade gracefully; never "
                        "become a required dependency",
        responsibilities=("availability detection", "timeout/cancel", "isolation",
                          "honest capability reporting"),
        non_responsibilities=("being mandatory", "execution"),
        required_inputs=("feature flag", "optional binary/library"),
        expected_outputs=("availability report", "bounded engine output"),
        failure_modes=("hang on missing binary", "unbounded runtime",
                       "false availability"),
        success_events=("failing engine isolated",),
        prevention_events=("base app runs with engine disabled",),
        recovery_events=("missing binary handled, council still runs"),
        evidence_requirements=("availability test", "disabled-path test"),
        honest_ceiling=9.0,
    ))

_register(_c(
    component_id="signal_reactor", component_name="Signal reactor / discovery",
    role_template=RoleTemplate.SIGNAL_REACTOR.value,
    primary_mandate="surface fresh, provenance-tagged candidates and fail closed on "
                    "stale or incomplete evidence",
    responsibilities=("freshness gating", "provenance", "fail closed"),
    non_responsibilities=("execution", "simulation"),
    required_inputs=("live sources", "OHLCV"),
    expected_outputs=("candidate signals",),
    failure_modes=("stale accepted", "provenance lost"),
    success_events=("stale data blocked",),
    prevention_events=("false completeness prevented",),
    recovery_events=(),
    evidence_requirements=("freshness tests",),
    honest_ceiling=9.0,
))

_register(_c(
    component_id="signal_bridge", component_name="Signal→MarketObservation bridge",
    role_template=RoleTemplate.SIGNAL_BRIDGE.value,
    primary_mandate="turn live signal/OHLCV state into a validated MarketObservation "
                    "without letting incomplete data look complete",
    responsibilities=("read signal state", "reconstruct returns/volumes",
                      "preserve provenance + freshness", "link parent signal",
                      "flag missing fields"),
    non_responsibilities=("execution", "creating a trade action", "inventing data"),
    required_inputs=("ticker", "OHLCV bars", "signal events"),
    expected_outputs=("MarketObservation", "parent_signal_id linkage"),
    failure_modes=("stale observation looks fresh", "invented returns"),
    success_events=("missing data prevented false confidence",),
    prevention_events=("stale/incomplete observation flagged, not fabricated",),
    recovery_events=("no OHLCV → INSUFFICIENT_DATA observation, no crash"),
    evidence_requirements=("bridge unit tests", "parent-linkage test"),
    honest_ceiling=9.2,
))


def get_contract(component_id: str) -> ComponentRoleContract | None:
    return _REGISTRY.get(component_id)


def all_contracts() -> list[ComponentRoleContract]:
    return list(_REGISTRY.values())


def component_ids() -> list[str]:
    return list(_REGISTRY.keys())


def role_weights_for(component_id: str) -> dict[str, float]:
    c = get_contract(component_id)
    return c.dimension_weights if c else _w()


def registry_report() -> dict[str, Any]:
    out = {
        "report": "role_contracts",
        "contract_version": ROLE_CONTRACT_VERSION,
        "component_count": len(_REGISTRY),
        "components": [c.to_dict() for c in _REGISTRY.values()],
        "dimensions": list(ALL_DIMENSIONS),
    }
    out.update(advisory_safety_stamps())
    return out


__all__ = [
    "ROLE_CONTRACT_VERSION", "RoleDimension", "ALL_DIMENSIONS", "RatingSupport",
    "EvidenceGrade", "RoleTemplate", "ComponentRoleContract", "get_contract",
    "all_contracts", "component_ids", "role_weights_for", "registry_report",
]
