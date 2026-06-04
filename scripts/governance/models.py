"""Dataclasses for the Daily Governance / Discovery Gate.

Pure data containers — no I/O, no broker, no execution. Every structure is
JSON-serialisable via :func:`to_jsonable` / ``DailyGovernanceResult.to_dict``.

This layer is ADVISORY-ONLY. The execution gate is always LOCKED, human
execution is always required, and broker execution is never allowed. Those
invariants are stamped onto every result so the MVP cannot silently drift.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any

# --- canonical advisory / safety vocabulary -----------------------------------
EXECUTION_GATE_LOCKED = "LOCKED"
REGIME_EXISTING_ONLY = "EXISTING_POSITION_MANAGEMENT_ONLY"
REGIME_WATCHLIST_ONLY = "WATCHLIST_ONLY"
REGIME_DISCOVERY = "DISCOVERY_AND_EXISTING_MANAGEMENT"

# --- candidate classifications ------------------------------------------------
CLASS_MANUAL_ADD = "MANUAL_ADD_CONSIDERATION"
CLASS_WATCH = "WATCH"
CLASS_WAIT = "WAIT"
CLASS_AVOID = "AVOID TODAY"
CLASS_RISK_BLOCK = "RISK BLOCK"
CLASS_MANAGEMENT_ONLY = "MANAGEMENT_ONLY"

# Ordering used to apply a "max classification" ceiling (e.g. source health
# failed => no candidate may exceed WATCH).
CLASS_RANK: dict[str, int] = {
    CLASS_RISK_BLOCK: 0,
    CLASS_AVOID: 1,
    CLASS_WAIT: 2,
    CLASS_WATCH: 3,
    CLASS_MANUAL_ADD: 4,
}

# --- source-health bands ------------------------------------------------------
SH_HIGH = "HIGH"
SH_MEDIUM = "MEDIUM"
SH_LOW = "LOW"
SH_FAILED = "FAILED"

# Providers whose payloads must NEVER count as live evidence.
NON_LIVE_PROVIDERS: frozenset[str] = frozenset(
    {
        "STATIC_UNIVERSE_FALLBACK",
        "STATIC_OR_EMPTY_FALLBACK",
        "EMPTY_FALLBACK",
        "UNVERIFIED",
    }
)

# --- risk-block taxonomy ------------------------------------------------------
BLOCK_TYPES: tuple[str, ...] = (
    "SOURCE_HEALTH_FAILED",
    "CURRENT_PRICE_MISSING",
    "PHANTOM_TICKER",
    "STALE_CANDIDATE",
    "CLOSED_OR_SOLD_POSITION",
    "NOT_OWNED_DO_NOT_MANAGE",
    "MODEL_CONTRADICTION",
    "HIGH_CHAOS_DIABLO_RISK",
    "STATIC_FALLBACK_ONLY",
    "PROMPT_ONLY_NOT_MODEL_BACKED",
    "DUPLICATE_CROWDED_EXPOSURE",
    "EXISTING_EXPOSURE_PENALTY",
    "OUTCOME_NOT_RECONCILED",
    "LEVERAGE_PRICE_UNKNOWN",
    "THESIS_NOT_FALSIFIABLE",
    "WRONG_RUN_DATE",
    "TICKER_MAPPING_UNCLEAR",
    "PHANTOM_POSITION_MANAGEMENT_ATTEMPT",
)


def to_jsonable(obj: Any) -> Any:
    """Recursively convert dataclasses/containers into JSON-serialisable data."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [to_jsonable(v) for v in obj]
    return obj


@dataclass(slots=True)
class RiskBlock:
    ticker: str
    name: str = ""
    block_type: str = ""
    severity: str = "MEDIUM"
    reason: str = ""
    missing_evidence: list[str] = field(default_factory=list)
    required_resolution: str = ""
    quarantine: bool = False
    created_at: str = ""
    source_models: list[str] = field(default_factory=list)
    can_appear_on_watchlist: bool = True
    can_appear_on_manual_board: bool = False
    can_receive_holding_review: bool = False

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


@dataclass(slots=True)
class ExistingHoldingReview:
    ticker: str
    classification: str
    severity: str
    reason: str
    leverage: float = 1.0
    leverage_risk: float = 0.0
    current_price_missing: bool = False
    stop_status: str = "unknown"
    tp_status: str = "unknown"
    thesis_conflict: bool = False
    holding_age_days: int = 0
    missing_evidence: list[str] = field(default_factory=list)
    human_review_required: bool = True
    authorizes_action: bool = False

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


@dataclass(slots=True)
class SourcePayloadScore:
    payload_name: str
    provider: str
    is_live: int
    provider_quality: float
    freshness: float
    completeness: float
    source_score: float
    counted_as_live: bool

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


@dataclass(slots=True)
class SourceHealth:
    score: float
    status: str
    new_risk_permission: bool
    current_prices_missing_for_all_H: bool
    all_market_news_filing_static_or_empty: bool
    payload_scores: list[SourcePayloadScore] = field(default_factory=list)
    hard_fail_reasons: list[str] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


@dataclass(slots=True)
class ModelReliability:
    model: str
    reliability: float
    wrong_run_date: bool = False
    overconfident_without_data: bool = False
    phantom_management_attempt: bool = False
    missing_evidence_claims: bool = False
    contradiction_with_portfolio_truth: bool = False
    unclear_action_language: bool = False
    action_calls_downgraded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


@dataclass(slots=True)
class CandidateAssessment:
    ticker: str
    name: str = ""
    country: str = "UNKNOWN"
    why_today: float = 0.0
    fcs: float = 0.0
    ers: float = 0.0
    mrs: float = 0.0
    mrs_norm: float = 0.0
    decay: float = 1.0
    delta_days: int = 0
    stale_flag: bool = False
    severe_stale_flag: bool = False
    classification: str = CLASS_WAIT
    manual_add_consideration: bool = False
    executable: bool = False
    qualitative_score: bool = False
    blockers: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    components: dict[str, Any] = field(default_factory=dict)
    human_review_required: bool = True
    authorizes_action: bool = False

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


@dataclass(slots=True)
class PortfolioTruth:
    verified_open: list[str] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)
    sold: list[str] = field(default_factory=list)
    do_not_manage: list[str] = field(default_factory=list)
    current_holdings_H: list[str] = field(default_factory=list)
    quarantined: list[str] = field(default_factory=list)
    indicator: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


@dataclass(slots=True)
class DailyGovernanceResult:
    # --- 16 mandated boards ---------------------------------------------------
    portfolio_truth: PortfolioTruth
    source_health: SourceHealth
    phantom_quarantine_board: list[RiskBlock]
    stale_memory_decay_board: list[dict[str, Any]]
    why_today_scores: dict[str, float]
    concentration_and_diversity: dict[str, Any]
    candidate_quality_board: list[CandidateAssessment]
    manual_promotion_gate: dict[str, Any]
    existing_holding_review_board: list[ExistingHoldingReview]
    reduce_exit_review_board: list[ExistingHoldingReview]
    risk_blocks: list[RiskBlock]
    no_new_risk_day: str
    least_bad_override_list: list[dict[str, Any]]
    moltbook_entry: dict[str, Any]
    final_daily_decision_board: dict[str, Any]

    # --- mirrored top-level scalars (single source of truth) ------------------
    run_date: str = ""
    created_at: str = ""
    schema_version: str = "1.0.0"
    final_regime: str = REGIME_EXISTING_ONLY
    new_risk_permission: bool = False
    execution_gate_status: str = EXECUTION_GATE_LOCKED
    human_execution_required: bool = True
    broker_execution_allowed: bool = False
    source_health_status: str = SH_FAILED

    # convenience mirrors used by the decision board / regression tests
    top_manual_add_consideration: list[str] = field(default_factory=list)
    best_watch: str | None = None
    best_wait: str | None = None
    names_to_quarantine: list[str] = field(default_factory=list)
    strongest_reduce_exit_review: list[str] = field(default_factory=list)

    # model reliability is a useful by-product, surfaced for transparency.
    model_reliability: list[ModelReliability] = field(default_factory=list)

    # outcome-maturity diagnostics (section 10) — surfaced alongside the boards.
    outcome_maturity_board: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)
