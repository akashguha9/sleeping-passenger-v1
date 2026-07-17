"""Unified, versioned contracts for the Simulation Intelligence Layer (SIL).

This is the *bedrock* of the SIL: pure, dependency-light dataclasses and enums
that describe every object flowing through the six-lens simulation council.

Purity contract (enforced by tests)
-----------------------------------
This module imports only the standard library and the repo's
``advisory_contract`` bedrock.  It NEVER imports:

* ``sqlite3`` / ``persistence`` (canonical writes live in ``scripts/persistence``)
* ``requests`` / ``socket`` / any network client
* any broker / order-execution SDK
* the FastAPI app or the frontend

Every simulation output is advisory-only.  None of these structures can grant
execution permission; the advisory safety stamps are attached on serialization
and are always ``execution_gate="LOCKED"`` / ``ai_execution_count=0`` /
``broker_api_called=False``.

Evidence honesty
----------------
The single most important design rule: an output must always declare *what kind
of thing it is* — MEASURED vs SIMULATED_ONLY vs INSUFFICIENT_DATA — and this is
never collapsed into a bare confidence number.  A beautiful simulated
distribution with no real outcomes behind it is labelled ``SIMULATED_ONLY`` and
can never masquerade as ``MEASURED``.
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

# Contract version — bump on any breaking change to a dataclass shape.  Every
# serialized SIL object carries this so replayed/persisted runs are versioned.
CONTRACT_VERSION = "sil-1.0.0"


# ---------------------------------------------------------------------------
# Evidence labels — the honesty vocabulary.  Never collapse into a confidence.
# ---------------------------------------------------------------------------
class EvidenceLabel(str, Enum):
    """How much trust an output deserves, by *kind* not by magnitude."""

    MEASURED = "MEASURED"
    EMPIRICALLY_CALIBRATED = "EMPIRICALLY_CALIBRATED"
    BACKTEST_DERIVED = "BACKTEST_DERIVED"
    MODEL_INFERRED = "MODEL_INFERRED"
    PROXY_DERIVED = "PROXY_DERIVED"
    SIMULATED_ONLY = "SIMULATED_ONLY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    ENGINE_UNAVAILABLE = "ENGINE_UNAVAILABLE"


# Ordering from strongest real-world grounding to weakest.  Used by the
# aggregator to weight measured evidence above metaphor/proxy/simulation.
EVIDENCE_STRENGTH: dict[str, float] = {
    EvidenceLabel.MEASURED.value: 1.00,
    EvidenceLabel.EMPIRICALLY_CALIBRATED.value: 0.85,
    EvidenceLabel.BACKTEST_DERIVED.value: 0.60,
    EvidenceLabel.MODEL_INFERRED.value: 0.40,
    EvidenceLabel.PROXY_DERIVED.value: 0.30,
    EvidenceLabel.SIMULATED_ONLY.value: 0.20,
    EvidenceLabel.INSUFFICIENT_DATA.value: 0.05,
    EvidenceLabel.ENGINE_UNAVAILABLE.value: 0.0,
}


class FreshnessStatus(str, Enum):
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class AdvisoryVote(str, Enum):
    """The only advisory actions the SIL may recommend.  NONE is an execution
    instruction — these are timing/attention stances a human interprets."""

    WATCH = "WATCH"
    WAIT = "WAIT"
    AVOID = "AVOID"
    RISK_BLOCK = "RISK_BLOCK"
    OUTCOME_REVIEW = "OUTCOME_REVIEW"


# Ranking used for risk-block precedence: a more defensive vote can override a
# more attractive one during aggregation.  Higher = more defensive.
VOTE_DEFENSIVENESS: dict[str, int] = {
    AdvisoryVote.RISK_BLOCK.value: 4,
    AdvisoryVote.AVOID.value: 3,
    AdvisoryVote.WAIT.value: 2,
    AdvisoryVote.OUTCOME_REVIEW.value: 1,
    AdvisoryVote.WATCH.value: 0,
}


class ThesisLifecycle(str, Enum):
    """COPASI-lens classification of where a thesis sits in its life."""

    EMERGING = "EMERGING"
    GROWING = "GROWING"
    STABLE = "STABLE"
    SATURATED = "SATURATED"
    ADAPTING = "ADAPTING"
    DECAYING = "DECAYING"
    COLLAPSING = "COLLAPSING"


class DisagreementClass(str, Enum):
    """How the six lenses relate to each other after aggregation."""

    CONSENSUS_ROBUST = "CONSENSUS_ROBUST"
    CONSENSUS_FRAGILE = "CONSENSUS_FRAGILE"
    SPLIT_DECISION = "SPLIT_DECISION"
    MINORITY_TAIL_WARNING = "MINORITY_TAIL_WARNING"
    SHARED_EVIDENCE_ILLUSION = "SHARED_EVIDENCE_ILLUSION"
    INSUFFICIENT_INDEPENDENCE = "INSUFFICIENT_INDEPENDENCE"
    SIMULATION_ONLY_CONSENSUS = "SIMULATION_ONLY_CONSENSUS"


class LensDomain(str, Enum):
    PHYSICS = "PHYSICS"
    CHEMISTRY = "CHEMISTRY"
    BIOLOGY = "BIOLOGY"
    RACING = "RACING"
    CHESS = "CHESS"
    POKER = "POKER"


def _clip(value: Any, lo: float = 0.0, hi: float = 1.0, default: float = 0.0) -> float:
    """Bounded float coercion — never raises, always in [lo, hi]."""
    try:
        if value is None or isinstance(value, bool):
            return default
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v:  # NaN
        return default
    return max(lo, min(hi, v))


# ---------------------------------------------------------------------------
# Input contracts
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class SimulationAssumption:
    """One named, adjustable assumption feeding a scenario (PhET-lens knob)."""

    name: str
    value: float
    unit: str = ""
    rationale: str = ""
    evidence_label: str = EvidenceLabel.MODEL_INFERRED.value
    low: float | None = None
    high: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(slots=True)
class SimulationScenario:
    """A named scenario: a set of assumptions + shock parameters."""

    scenario_id: str
    name: str
    description: str = ""
    assumptions: list[SimulationAssumption] = field(default_factory=list)
    shock_parameters: dict[str, float] = field(default_factory=dict)
    deterministic: bool = True
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        return d


@dataclass(slots=True)
class MarketObservation:
    """Normalized, provenance-tagged market inputs for one candidate.

    Every field is optional; missing fields must be declared in
    ``missing_fields`` so lenses fail closed rather than inventing data.
    """

    ticker: str
    market: str = "UNKNOWN"  # e.g. "IN" / "US"
    as_of: str = ""
    data_cutoff: str = ""
    price: float | None = None
    prev_close: float | None = None
    returns: list[float] = field(default_factory=list)  # recent daily returns
    volumes: list[float] = field(default_factory=list)
    volatility: float | None = None
    spread_bps: float | None = None
    adv_usd: float | None = None  # average daily $ volume (liquidity)
    sector: str = ""
    catalysts: list[dict[str, Any]] = field(default_factory=list)
    dependencies: list[dict[str, Any]] = field(default_factory=list)
    narrative_sources: list[str] = field(default_factory=list)
    source_count: int = 0
    freshness_status: str = FreshnessStatus.UNKNOWN.value
    missing_fields: list[str] = field(default_factory=list)
    provenance: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(slots=True)
class SimulationRequest:
    """Top-level request to run the council for one candidate."""

    ticker: str
    market: str = "UNKNOWN"
    observation: MarketObservation | None = None
    scenarios: list[str] = field(default_factory=list)  # scenario_ids to stress
    seed: int = 0
    max_runs: int = 256
    parent_signal_id: str = ""
    requested_lenses: list[str] = field(default_factory=list)  # empty = all six

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        if self.observation is not None:
            d["observation"] = self.observation.to_dict()
        return d


# ---------------------------------------------------------------------------
# Uncertainty + evidence
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class UncertaintyBand:
    """A distribution summary — never a single number."""

    central: float
    p05: float
    p50: float
    p95: float
    dispersion: float  # std / spread proxy
    tail_low: float  # worst plausible (e.g. p01)
    tail_high: float  # best plausible (e.g. p99)
    n_samples: int = 0
    convergence: str = "UNKNOWN"  # CONVERGED / NOT_CONVERGED / DETERMINISTIC

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(slots=True)
class EvidencePacket:
    """A single unit of evidence with a de-dup fingerprint and provenance.

    The fingerprint lets the aggregator detect when two lenses are leaning on
    the *same* underlying observation (shared-evidence illusion).
    """

    lens: str
    claim: str
    evidence_label: str
    fingerprint: str  # stable hash of the underlying source(s)
    source_keys: list[str] = field(default_factory=list)
    weight: float = 1.0
    freshness_status: str = FreshnessStatus.UNKNOWN.value

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(slots=True)
class CounterfactualBranch:
    """One 'what if assumption X changes' branch."""

    branch_id: str
    changed_assumption: str
    from_value: float
    to_value: float
    baseline_outcome: float
    branch_outcome: float
    delta: float
    dominant: bool = False  # does this assumption dominate the result?

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(slots=True)
class StressTestResult:
    """Outcome of applying one scenario to a candidate."""

    scenario_id: str
    scenario_name: str
    survived: bool
    impact: float  # signed impact estimate (e.g. simulated drawdown fraction)
    band: UncertaintyBand
    failure_modes: list[str] = field(default_factory=list)
    evidence_label: str = EvidenceLabel.SIMULATED_ONLY.value

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["band"] = self.band.to_dict()
        return d


# ---------------------------------------------------------------------------
# Lens output — the common interface every lens returns
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class LensResult:
    """Uniform output of every domain lens.

    All six lenses return exactly this shape so the council can aggregate them
    without special-casing.  Scores are bounded [0, 1].
    """

    lens: str  # LensDomain value
    state_interpretation: str
    scenario_branches: list[str] = field(default_factory=list)
    main_risk: str = ""
    main_opportunity: str = ""
    advisory_vote: str = AdvisoryVote.WATCH.value
    confidence: float = 0.0  # bounded 0..1 — NOT a truth claim on its own
    evidence_label: str = EvidenceLabel.SIMULATED_ONLY.value
    uncertainty: float = 1.0  # 0 = certain, 1 = maximally uncertain
    robustness: float = 0.0  # how stable to assumption perturbation
    fragility: float = 0.0  # how easily the conclusion flips
    regret: float = 0.0  # max regret proxy of following this vote
    exploitability: float = 0.0  # how easily an opposing actor breaks it
    evidence: list[EvidencePacket] = field(default_factory=list)
    missing_data_warnings: list[str] = field(default_factory=list)
    freshness_status: str = FreshnessStatus.UNKNOWN.value
    detail: dict[str, Any] = field(default_factory=dict)
    tail_warning: str = ""  # non-empty => preserve through aggregation
    error: str = ""

    def __post_init__(self) -> None:
        self.confidence = _clip(self.confidence)
        self.uncertainty = _clip(self.uncertainty)
        self.robustness = _clip(self.robustness)
        self.fragility = _clip(self.fragility)
        self.regret = _clip(self.regret)
        self.exploitability = _clip(self.exploitability)

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["evidence"] = [e.to_dict() if hasattr(e, "to_dict") else e
                         for e in self.evidence]
        return d


# ---------------------------------------------------------------------------
# Council + envelope
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class LensWeight:
    """Explainable weight assigned to one lens by the aggregator."""

    lens: str
    base_weight: float
    evidence_multiplier: float
    correlation_penalty: float
    staleness_penalty: float
    missing_data_penalty: float
    final_weight: float
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(slots=True)
class SimulationCouncilResult:
    """The aggregated verdict of the six-lens council for one candidate."""

    run_id: str
    contract_version: str
    ticker: str
    market: str
    as_of: str
    data_cutoff: str
    seed: int
    parent_signal_id: str
    aggregate_vote: str
    disagreement_class: str
    aggregate_confidence: float
    evidence_label: str  # the *weakest binding* label — honesty floor
    robustness: float
    fragility: float
    lens_results: list[LensResult] = field(default_factory=list)
    lens_weights: list[LensWeight] = field(default_factory=list)
    minority_warnings: list[str] = field(default_factory=list)
    tail_warnings: list[str] = field(default_factory=list)
    stress_results: list[StressTestResult] = field(default_factory=list)
    counterfactuals: list[CounterfactualBranch] = field(default_factory=list)
    dominant_assumptions: list[str] = field(default_factory=list)
    missing_data_warnings: list[str] = field(default_factory=list)
    freshness_status: str = FreshnessStatus.UNKNOWN.value
    risk_block_engaged: bool = False
    risk_block_reason: str = ""
    simulation_only: bool = True
    aggregation_explanation: list[str] = field(default_factory=list)
    engine_availability: dict[str, str] = field(default_factory=dict)
    usefulness_score: float = 0.0  # engineering/decision usefulness, NOT alpha

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["lens_results"] = [r.to_dict() for r in self.lens_results]
        d["lens_weights"] = [w.to_dict() for w in self.lens_weights]
        d["stress_results"] = [s.to_dict() for s in self.stress_results]
        d["counterfactuals"] = [c.to_dict() for c in self.counterfactuals]
        # Advisory safety stamps on every serialized council result.
        d.update(advisory_safety_stamps())
        d["execution_mode"] = "HUMAN_ONLY"
        d["human_execution_required"] = True
        return d


def stamp_advisory(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach canonical advisory stamps to any SIL dict payload."""
    out = dict(payload)
    out.update(advisory_safety_stamps())
    out.setdefault("execution_mode", "HUMAN_ONLY")
    out.setdefault("human_execution_required", True)
    out.setdefault("contract_version", CONTRACT_VERSION)
    return out


__all__ = [
    "CONTRACT_VERSION",
    "EvidenceLabel",
    "EVIDENCE_STRENGTH",
    "FreshnessStatus",
    "AdvisoryVote",
    "VOTE_DEFENSIVENESS",
    "ThesisLifecycle",
    "DisagreementClass",
    "LensDomain",
    "SimulationAssumption",
    "SimulationScenario",
    "MarketObservation",
    "SimulationRequest",
    "UncertaintyBand",
    "EvidencePacket",
    "CounterfactualBranch",
    "StressTestResult",
    "LensResult",
    "LensWeight",
    "SimulationCouncilResult",
    "stamp_advisory",
]
