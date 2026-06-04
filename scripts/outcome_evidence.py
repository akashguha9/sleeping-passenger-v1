"""Canonical outcome-evidence model for honest calibration.

Calibration is only as honest as the provenance of the outcomes feeding it.
This module defines a single structured record for every resolved trade/signal
outcome, with an explicit ``source_type`` so REAL, PAPER, SYNTHETIC_FIXTURE,
and IMPORTED_BACKTEST evidence can never be silently mixed.

Pure module: no DB, no network, no broker calls. Importing has no side
effects. Advisory invariants are constant (advisory_only / human_execution
required / broker_api_called False).

Return math
-----------
Closed LONG:   r = (P_exit - P_entry) / P_entry
Closed SHORT:  r = (P_entry - P_exit) / P_entry
PnL fallback:  r = PnL / capital_at_risk   (when prices are absent)
Levered:       r_L = L * r

Labelling (epsilon = 0.001 default):
    WIN        if r >  eps
    LOSS       if r < -eps
    BREAKEVEN  if |r| <= eps
    OPEN/UNKNOWN if r is undefined

Eligibility (q_min = 0.70 default):
    eligible iff source_type in {REAL_MANUAL_TRADE, PAPER_TRADE,
    IMPORTED_BACKTEST} and outcome_label in {WIN, LOSS, BREAKEVEN} and
    score_at_entry is not None and quality >= q_min.
SYNTHETIC_FIXTURE is NEVER calibration-eligible.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

# Source-type vocabulary.
REAL_MANUAL_TRADE = "REAL_MANUAL_TRADE"
PAPER_TRADE = "PAPER_TRADE"
SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"
IMPORTED_BACKTEST = "IMPORTED_BACKTEST"
_VALID_SOURCE_TYPES = {
    REAL_MANUAL_TRADE, PAPER_TRADE, SYNTHETIC_FIXTURE, IMPORTED_BACKTEST,
}
# Source types that may feed calibration (fixtures may not).
_ELIGIBLE_SOURCE_TYPES = {REAL_MANUAL_TRADE, PAPER_TRADE, IMPORTED_BACKTEST}

# Outcome labels.
WIN = "WIN"
LOSS = "LOSS"
BREAKEVEN = "BREAKEVEN"
OPEN = "OPEN"
UNKNOWN = "UNKNOWN"
_RESOLVED_LABELS = {WIN, LOSS, BREAKEVEN}

DEFAULT_EPSILON = 0.001
DEFAULT_Q_MIN = 0.70

# Quality weight for source reliability (component h).
_SOURCE_QUALITY = {
    REAL_MANUAL_TRADE: 1.0,
    PAPER_TRADE: 0.8,
    IMPORTED_BACKTEST: 0.6,
    SYNTHETIC_FIXTURE: 0.0,
}

_ADVISORY_STAMPS = {
    "advisory_only": True,
    "human_execution_required": True,
    "broker_api_called": False,
}


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compute_return(
    direction: str,
    entry_price: float | None,
    exit_price: float | None,
    *,
    realized_pnl: float | None = None,
    capital_at_risk: float | None = None,
) -> float | None:
    """Unlevered return r. None when undeterminable (never fabricated)."""
    d = str(direction or "UNKNOWN").upper()
    ep = _to_float(entry_price)
    xp = _to_float(exit_price)
    if ep is not None and xp is not None and ep != 0.0:
        if d == "LONG":
            return (xp - ep) / ep
        if d == "SHORT":
            return (ep - xp) / ep
        return None  # unknown direction → cannot sign the return
    # PnL fallback only when prices are absent.
    pnl = _to_float(realized_pnl)
    car = _to_float(capital_at_risk)
    if pnl is not None and car not in (None, 0.0):
        return pnl / car
    return None


def label_outcome(r: float | None, *, epsilon: float = DEFAULT_EPSILON) -> str:
    if r is None:
        return OPEN
    if r > epsilon:
        return WIN
    if r < -epsilon:
        return LOSS
    return BREAKEVEN


def compute_quality(
    *,
    source_type: str,
    entry_price: float | None,
    exit_price: float | None,
    realized_pnl: float | None,
    opened_at: Any,
    closed_at: Any,
    score_at_entry: float | None,
    ticker: str | None,
    outcome_label: str,
) -> float:
    """Quality score q_i in [0, 1] per the documented weighting."""
    a = 1.0 if _to_float(entry_price) is not None else 0.0
    b = 1.0 if (_to_float(exit_price) is not None or _to_float(realized_pnl) is not None) else 0.0
    c = 1.0 if opened_at else 0.0
    d = 1.0 if closed_at else 0.0
    e = 1.0 if _to_float(score_at_entry) is not None else 0.0
    f = 1.0 if (ticker and str(ticker).strip()) else 0.0
    g = 1.0 if outcome_label in _RESOLVED_LABELS else 0.0
    h = _SOURCE_QUALITY.get(source_type, 0.0)
    q = 0.15 * a + 0.20 * b + 0.10 * c + 0.10 * d + 0.15 * e + 0.10 * f + 0.15 * g + 0.05 * h
    return min(1.0, max(0.0, q))


@dataclass(frozen=True)
class OutcomeEvidence:
    outcome_id: str
    source_type: str
    ticker: str
    direction: str = UNKNOWN
    signal_id: str | None = None
    trade_id: str | None = None
    opened_at: datetime | str | None = None
    closed_at: datetime | str | None = None
    horizon_days: float | None = None
    entry_price: float | None = None
    exit_price: float | None = None
    realized_return: float | None = None
    realized_levered_return: float | None = None
    realized_pnl: float | None = None
    leverage: float = 1.0
    jurisdiction_group: str = UNKNOWN
    score_at_entry: float | None = None
    score_bucket: str | None = None
    archetype: str | None = None
    signal_class: str | None = None
    outcome_label: str = UNKNOWN
    quality: float = 0.0
    is_calibration_eligible: bool = False
    ineligible_reason: str | None = None
    # Advisory invariants — constant.
    advisory_only: bool = True
    human_execution_required: bool = True
    broker_api_called: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("opened_at", "closed_at"):
            v = d.get(k)
            if isinstance(v, datetime):
                d[k] = v.isoformat()
        return d


def build_outcome(
    *,
    outcome_id: str,
    source_type: str,
    ticker: str,
    direction: str = UNKNOWN,
    signal_id: str | None = None,
    trade_id: str | None = None,
    opened_at: Any = None,
    closed_at: Any = None,
    horizon_days: float | None = None,
    entry_price: float | None = None,
    exit_price: float | None = None,
    realized_pnl: float | None = None,
    capital_at_risk: float | None = None,
    leverage: float = 1.0,
    jurisdiction_group: str = UNKNOWN,
    score_at_entry: float | None = None,
    score_bucket: str | None = None,
    archetype: str | None = None,
    signal_class: str | None = None,
    epsilon: float = DEFAULT_EPSILON,
    q_min: float = DEFAULT_Q_MIN,
    realized_return: float | None = None,
    outcome_label_override: str | None = None,
) -> OutcomeEvidence:
    """Build a fully-derived OutcomeEvidence record.

    ``realized_return`` may be supplied directly (e.g. imported backtests);
    otherwise it is computed from prices / PnL. Returns are never fabricated:
    if nothing determines a return, the outcome is OPEN and ineligible.

    ``outcome_label_override`` lets an authoritative classifier (a human
    reconciliation status, a Moltbook outcome) set the WIN/LOSS/BREAKEVEN
    label even when no clean price-based return exists. It is honoured only
    when it is a resolved label; it never invents a return.
    """
    st = str(source_type).upper()
    if st not in _VALID_SOURCE_TYPES:
        st = SYNTHETIC_FIXTURE  # unknown provenance is treated as non-eligible

    r = _to_float(realized_return)
    if r is None:
        r = compute_return(
            direction, entry_price, exit_price,
            realized_pnl=realized_pnl, capital_at_risk=capital_at_risk,
        )
    lev = _to_float(leverage) or 1.0
    if lev < 1.0:
        lev = 1.0
    r_lev = (lev * r) if r is not None else None

    override = str(outcome_label_override or "").upper()
    if override in _RESOLVED_LABELS:
        label = override
    else:
        label = label_outcome(r, epsilon=epsilon)

    quality = compute_quality(
        source_type=st,
        entry_price=entry_price,
        exit_price=exit_price,
        realized_pnl=realized_pnl,
        opened_at=opened_at,
        closed_at=closed_at,
        score_at_entry=score_at_entry,
        ticker=ticker,
        outcome_label=label,
    )

    eligible, reason = _eligibility(st, label, score_at_entry, quality, q_min)

    return OutcomeEvidence(
        outcome_id=outcome_id,
        source_type=st,
        ticker=str(ticker or "").upper(),
        direction=str(direction or UNKNOWN).upper(),
        signal_id=signal_id,
        trade_id=trade_id,
        opened_at=opened_at,
        closed_at=closed_at,
        horizon_days=_to_float(horizon_days),
        entry_price=_to_float(entry_price),
        exit_price=_to_float(exit_price),
        realized_return=r,
        realized_levered_return=r_lev,
        realized_pnl=_to_float(realized_pnl),
        leverage=lev,
        jurisdiction_group=str(jurisdiction_group or UNKNOWN).upper(),
        score_at_entry=_to_float(score_at_entry),
        score_bucket=score_bucket,
        archetype=archetype,
        signal_class=signal_class,
        outcome_label=label,
        quality=round(quality, 6),
        is_calibration_eligible=eligible,
        ineligible_reason=reason,
    )


def _eligibility(
    source_type: str,
    label: str,
    score_at_entry: float | None,
    quality: float,
    q_min: float,
) -> tuple[bool, str | None]:
    if source_type == SYNTHETIC_FIXTURE:
        return False, "synthetic_fixture_never_calibration_eligible"
    if source_type not in _ELIGIBLE_SOURCE_TYPES:
        return False, "source_type_not_eligible"
    if label not in _RESOLVED_LABELS:
        return False, "outcome_not_resolved"
    if _to_float(score_at_entry) is None:
        return False, "missing_score_at_entry"
    if quality < q_min:
        return False, f"quality_below_q_min ({quality:.3f} < {q_min:.2f})"
    return True, None


def eligible_outcomes(outcomes: list[OutcomeEvidence]) -> list[OutcomeEvidence]:
    return [o for o in outcomes if o.is_calibration_eligible]


def provenance_counts(outcomes: list[OutcomeEvidence]) -> dict[str, int]:
    """Count outcomes by source type + eligibility — feeds readiness honesty."""
    counts = {
        "real_n": 0, "paper_n": 0, "backtest_n": 0, "synthetic_n": 0,
        "eligible_n": 0, "total_n": len(outcomes),
    }
    for o in outcomes:
        if o.source_type == REAL_MANUAL_TRADE:
            counts["real_n"] += 1
        elif o.source_type == PAPER_TRADE:
            counts["paper_n"] += 1
        elif o.source_type == IMPORTED_BACKTEST:
            counts["backtest_n"] += 1
        elif o.source_type == SYNTHETIC_FIXTURE:
            counts["synthetic_n"] += 1
        if o.is_calibration_eligible:
            counts["eligible_n"] += 1
    return counts


__all__ = [
    "REAL_MANUAL_TRADE", "PAPER_TRADE", "SYNTHETIC_FIXTURE", "IMPORTED_BACKTEST",
    "WIN", "LOSS", "BREAKEVEN", "OPEN", "UNKNOWN",
    "DEFAULT_EPSILON", "DEFAULT_Q_MIN",
    "OutcomeEvidence", "build_outcome", "compute_return", "label_outcome",
    "compute_quality", "eligible_outcomes", "provenance_counts",
]
