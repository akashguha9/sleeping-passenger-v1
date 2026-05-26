"""Portfolio Capacity Score · Regime classifier · Risk-Budget dashboard.

Capital Rotation Engine — capacity + regime + budget layer.

This module turns a portfolio snapshot (positions + exit-review board
+ theme-slot summary + optional cash data) into three deterministic
artefacts the operator can rely on:

1. ``portfolio_capacity_score``  ∈ [0,10]
2. ``portfolio_regime``          ∈ {BUY_ALLOWED, BUY_LIMITED, BUY_BLOCKED}
3. ``risk_budget``               available capital + buffers

Mathematical definitions follow Section 5 / Section 6 / Section 10 of
the capital-rotation spec exactly.  Every output preserves the
advisory-only invariants.

Pure module
-----------
- No DB / filesystem / network / broker calls / AI execution.
- Importing has no side effects.
"""
from __future__ import annotations

from typing import Any, Iterable

try:
    from scripts.theme_slot_accounting import STATUS_OVER_CAP
except ModuleNotFoundError:  # pragma: no cover — flat-layout fallback
    from theme_slot_accounting import STATUS_OVER_CAP  # type: ignore


# ---------------------------------------------------------------------------
# Regime vocabulary
# ---------------------------------------------------------------------------

REGIME_BUY_ALLOWED = "BUY_ALLOWED"
REGIME_BUY_LIMITED = "BUY_LIMITED"
REGIME_BUY_BLOCKED = "BUY_BLOCKED"

ALL_REGIMES: tuple[str, ...] = (
    REGIME_BUY_ALLOWED,
    REGIME_BUY_LIMITED,
    REGIME_BUY_BLOCKED,
)

# Source-health labels recognised by the live-source score.
_LIVE_VERIFIED = "LIVE_VERIFIED"
_DELAYED_BUT_USABLE = "DELAYED_BUT_USABLE"
_PARTIAL = "PARTIAL"
_UNVERIFIED = "UNVERIFIED"
_STATIC_FALLBACK = "STATIC_FALLBACK"

# Default standard "small entry" size.  Used by the risk-budget buffers
# so the operator can override per call.
DEFAULT_SMALL_ENTRY_SIZE = 50.0


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Capacity-component scores
# ---------------------------------------------------------------------------


def live_source_score(source_health: str | None) -> float:
    """S_live ∈ [0,1] from the source-health label."""
    text = (source_health or "").strip().upper()
    if text == _LIVE_VERIFIED:
        return 1.0
    if text == _DELAYED_BUT_USABLE:
        return 0.7
    if text == _PARTIAL:
        return 0.4
    return 0.0  # UNVERIFIED, STATIC_FALLBACK, missing


def reconciliation_cleanliness_score(
    unreconciled_count: int, open_count: int
) -> float:
    """S_recon = 1 - min(1, unreconciled / max(open, 1))."""
    return 1.0 - min(1.0, unreconciled_count / max(open_count, 1))


def stop_distance_score(distances: Iterable[float | None]) -> float:
    """S_stop = average over positions of clamp(d / 0.10, 0, 1).

    10% cushion = 1.0, 5% = 0.5, breached = 0.  Missing distances
    contribute 0 (no cushion to credit).
    """
    arr = [d for d in distances if d is not None]
    if not arr:
        return 0.5  # neutral when nothing to measure
    scores = [_clamp(d / 0.10, 0.0, 1.0) for d in arr]
    return sum(scores) / len(scores)


def cash_available_score(
    cash_available: float | None,
    target_cash_buffer: float | None,
) -> tuple[float, bool]:
    """S_cash, cash_budget_unknown.

    If either input is missing or non-positive target → ``(0.5, True)``.
    """
    if cash_available is None or target_cash_buffer is None:
        return 0.5, True
    if target_cash_buffer <= 0:
        return 0.5, True
    return _clamp(cash_available / target_cash_buffer, 0.0, 1.0), False


def theme_room_score(theme_rows: Iterable[dict[str, Any]]) -> float:
    """S_theme — average per-theme slack, capped at 0.35 if any over-cap."""
    rows = list(theme_rows or [])
    if not rows:
        return 0.5
    over_cap = any(r.get("status") == STATUS_OVER_CAP for r in rows)
    per_theme: list[float] = []
    for row in rows:
        hard = float(row.get("hard_cap") or 0)
        if hard <= 0:
            continue
        used = float(row.get("used_weight") or 0)
        slack = 1.0 - (used / hard)
        per_theme.append(_clamp(slack, 0.0, 1.0))
    if not per_theme:
        score = 0.5
    else:
        score = sum(per_theme) / len(per_theme)
    if over_cap:
        score = min(score, 0.35)
    return score


def leverage_safety_score(
    leveraged_risk_exposure: float, leverage_risk_limit: float
) -> float:
    """S_lev = 1 - min(1, exposure / limit).  Defaults to 1 when limit ≤ 0."""
    if leverage_risk_limit <= 0:
        return 1.0
    return 1.0 - min(1.0, max(0.0, leveraged_risk_exposure) / leverage_risk_limit)


def duplicate_exposure_penalty(duplicate_count: int) -> float:
    """P_dup = min(1, duplicates / 3)."""
    return min(1.0, max(0, duplicate_count) / 3.0)


def open_unreviewed_penalty(unreviewed_count: int, open_count: int) -> float:
    """P_unreviewed = min(1, unreviewed / max(open, 1))."""
    return min(1.0, max(0, unreviewed_count) / max(open_count, 1))


def dirty_data_penalty(
    phantom_open_count: int, critical_missing_count: int, open_count: int
) -> float:
    """P_dirty — 1 if any phantom row OR critical missing; else proportional."""
    if phantom_open_count > 0 or critical_missing_count > 0:
        return 1.0
    if open_count <= 0:
        return 0.0
    return min(1.0, max(0, critical_missing_count) / open_count)


def pending_tp_penalty(partial_tp_due_count: int) -> float:
    """P_tp = min(1, due / 3)."""
    return min(1.0, max(0, partial_tp_due_count) / 3.0)


def stop_breach_penalty(stop_breach_count: int) -> float:
    """P_stop — 1 if any breach else 0 (binary by spec)."""
    return 1.0 if stop_breach_count > 0 else 0.0


# ---------------------------------------------------------------------------
# Composite capacity score + regime
# ---------------------------------------------------------------------------


def compute_portfolio_capacity(
    *,
    exit_board: dict[str, Any],
    theme_summary: dict[str, Any],
    source_health: str | None = None,
    cash_available: float | None = None,
    target_cash_buffer: float | None = None,
    leveraged_risk_exposure: float = 0.0,
    leverage_risk_limit: float = 0.0,
    unreconciled_open_count: int = 0,
    india_4x_unreviewed_count: int = 0,
) -> dict[str, Any]:
    """Composite capacity score in ``[0,10]`` + per-component breakdown.

    Inputs are sourced from the exit-review board and theme-slot
    summary the daily pipeline already builds.  The function never
    reaches a broker, queries a DB, or fabricates inputs.
    """
    rows = exit_board.get("rows") or []
    open_count = int(exit_board.get("open_position_count") or len(rows))
    distances = [r.get("distance_to_stop_pct") for r in rows]
    stop_breach_count = int(exit_board.get("stop_breach_count") or 0)
    phantom_count = int(exit_board.get("phantom_open_count") or 0)
    live_missing_count = int(exit_board.get("live_price_missing_count") or 0)
    partial_tp_due = int(exit_board.get("partial_tp_due_count") or 0)
    duplicate_count = int(exit_board.get("duplicate_exposure_count") or 0)
    unreviewed_count = sum(
        1 for r in rows if r.get("human_action_required")
    )

    theme_rows = theme_summary.get("themes") or []

    S_live = live_source_score(source_health)
    S_recon = reconciliation_cleanliness_score(unreconciled_open_count, open_count)
    S_stop = stop_distance_score(distances)
    S_cash, cash_unknown = cash_available_score(cash_available, target_cash_buffer)
    S_theme = theme_room_score(theme_rows)
    S_lev = leverage_safety_score(leveraged_risk_exposure, leverage_risk_limit)

    P_dup = duplicate_exposure_penalty(duplicate_count)
    P_unreviewed = open_unreviewed_penalty(unreviewed_count, open_count)
    critical_missing = live_missing_count + phantom_count
    P_dirty = dirty_data_penalty(phantom_count, critical_missing, open_count)
    P_tp = pending_tp_penalty(partial_tp_due)
    P_stop = stop_breach_penalty(stop_breach_count)

    raw = (
        2.0 * S_live
        + 1.5 * S_recon
        + 1.5 * S_stop
        + 1.0 * S_cash
        + 1.5 * S_theme
        + 1.0 * S_lev
        - 1.0 * P_dup
        - 1.0 * P_unreviewed
        - 1.5 * P_dirty
        - 1.0 * P_tp
        - 2.0 * P_stop
    )
    score = _clamp(raw, 0.0, 10.0)

    return {
        "portfolio_capacity_score": round(score, 4),
        "raw_components": {
            "S_live": round(S_live, 4),
            "S_recon": round(S_recon, 4),
            "S_stop": round(S_stop, 4),
            "S_cash": round(S_cash, 4),
            "S_theme": round(S_theme, 4),
            "S_lev": round(S_lev, 4),
            "P_dup": round(P_dup, 4),
            "P_unreviewed": round(P_unreviewed, 4),
            "P_dirty": round(P_dirty, 4),
            "P_tp": round(P_tp, 4),
            "P_stop": round(P_stop, 4),
        },
        "inputs": {
            "open_position_count": open_count,
            "stop_breach_count": stop_breach_count,
            "phantom_open_count": phantom_count,
            "live_price_missing_count": live_missing_count,
            "partial_tp_due_count": partial_tp_due,
            "duplicate_exposure_count": duplicate_count,
            "unreviewed_open_count": unreviewed_count,
            "india_4x_unreviewed_count": india_4x_unreviewed_count,
            "source_health": source_health or "MISSING",
            "cash_budget_unknown": cash_unknown,
        },
        "advisory_only": True,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "human_execution_required": True,
        "execution_permission": "LOCKED",
    }


def classify_portfolio_regime(
    capacity_result: dict[str, Any],
    *,
    exit_board: dict[str, Any],
    theme_summary: dict[str, Any],
    source_health: str | None = None,
    india_4x_unreviewed_count: int = 0,
) -> dict[str, Any]:
    """Map capacity + counters to one of the three regime labels."""
    score = float(capacity_result.get("portfolio_capacity_score") or 0.0)
    stop_breach = int(exit_board.get("stop_breach_count") or 0)
    phantom = int(exit_board.get("phantom_open_count") or 0)
    live_missing = int(exit_board.get("live_price_missing_count") or 0)
    tp_due = int(exit_board.get("partial_tp_due_count") or 0)
    runner_review = int(exit_board.get("runner_exit_review_count") or 0)
    any_hard_cap = bool(theme_summary.get("any_hard_cap_exceeded"))
    health = (source_health or "").strip().upper()

    reasons: list[str] = []
    regime: str

    blocked = False
    if score < 5.0:
        reasons.append(f"capacity_score<5.0:{round(score, 2)}")
        blocked = True
    if stop_breach > 0:
        reasons.append(f"stop_breach_count={stop_breach}")
        blocked = True
    if phantom > 0:
        reasons.append(f"phantom_open_count={phantom}")
        blocked = True
    if live_missing > 0:
        reasons.append(f"live_price_missing_count={live_missing}")
        blocked = True
    if india_4x_unreviewed_count > 0:
        reasons.append(
            f"india_4x_unreviewed_count={india_4x_unreviewed_count}"
        )
        blocked = True
    if health == _UNVERIFIED:
        reasons.append("source_health=UNVERIFIED")
        blocked = True

    if blocked:
        regime = REGIME_BUY_BLOCKED
        max_new_entries = 0
        max_size_per_entry = 0.0
        leverage_allowed = 1.0
    elif score >= 8.0 and not any_hard_cap and tp_due == 0 and runner_review == 0:
        regime = REGIME_BUY_ALLOWED
        max_new_entries = 5
        max_size_per_entry = 200.0
        leverage_allowed = 1.0
    else:
        regime = REGIME_BUY_LIMITED
        if any_hard_cap:
            reasons.append("theme_hard_cap_exceeded")
        if tp_due > 0:
            reasons.append(f"partial_tp_due_count={tp_due}")
        if runner_review > 0:
            reasons.append(f"runner_exit_review_count={runner_review}")
        if not reasons:
            reasons.append(f"capacity_score_mid:{round(score, 2)}")
        max_new_entries = 3
        max_size_per_entry = DEFAULT_SMALL_ENTRY_SIZE
        leverage_allowed = 1.0

    return {
        "portfolio_regime": regime,
        "portfolio_capacity_score": score,
        "reason_codes": reasons,
        "allowed_new_entries": int(max_new_entries),
        "max_size_per_entry": float(max_size_per_entry),
        "max_total_new_capital": float(max_new_entries * max_size_per_entry),
        "leverage_allowed": float(leverage_allowed),
        "advisory_only": True,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "human_execution_required": True,
        "execution_permission": "LOCKED",
    }


# ---------------------------------------------------------------------------
# Risk-budget dashboard (Section 10)
# ---------------------------------------------------------------------------


def compute_risk_budget(
    *,
    exit_board: dict[str, Any],
    regime: dict[str, Any],
    cash_available: float | None = None,
    minimum_cash_reserve: float = 0.0,
    standard_small_trade_size: float = DEFAULT_SMALL_ENTRY_SIZE,
    leverage_risk_factor: float = 0.5,
) -> dict[str, Any]:
    """available_new_risk_budget per the spec.

    When ``cash_available`` is None we still compute the buffer-only
    side and set ``cash_budget_unknown=True``; ``available_new_risk_budget``
    is then derived from the regime's ``max_total_new_capital`` cap.
    """
    rows = exit_board.get("rows") or []

    # unresolved_stop_risk_buffer ≈ Σ notional · L · max(0, 0.05 - distance)
    stop_buffer = 0.0
    for r in rows:
        d = r.get("distance_to_stop_pct")
        L = float(r.get("leverage") or 1.0)
        notional = float(
            r.get("notional")
            or r.get("money_allocated")
            or standard_small_trade_size
        )
        if d is None:
            continue
        if d < 0.05:
            stop_buffer += notional * L * max(0.0, 0.05 - d)

    partial_tp_due = int(exit_board.get("partial_tp_due_count") or 0)
    pending_tp_buffer = partial_tp_due * standard_small_trade_size

    leverage_buffer = 0.0
    for r in rows:
        L = float(r.get("leverage") or 1.0)
        if L <= 1.0:
            continue
        notional = float(
            r.get("notional")
            or r.get("money_allocated")
            or standard_small_trade_size
        )
        leverage_buffer += notional * (L - 1.0) * leverage_risk_factor

    duplicate_count = int(exit_board.get("duplicate_exposure_count") or 0)
    duplicate_buffer = duplicate_count * standard_small_trade_size

    data_blocked = int(exit_board.get("data_blocked_count") or 0)
    dirty_data_buffer = data_blocked * standard_small_trade_size

    cash_unknown = cash_available is None
    if cash_unknown:
        available = float(regime.get("max_total_new_capital") or 0.0)
    else:
        available = (
            float(cash_available)
            - stop_buffer
            - pending_tp_buffer
            - leverage_buffer
            - duplicate_buffer
            - dirty_data_buffer
            - float(minimum_cash_reserve)
        )
        available = max(0.0, available)

    regime_cap = float(regime.get("max_total_new_capital") or 0.0)
    effective_cap = min(available, regime_cap) if not cash_unknown else regime_cap

    return {
        "available_new_risk_budget": round(effective_cap, 2),
        "cash_budget_unknown": cash_unknown,
        "buffers": {
            "unresolved_stop_risk_buffer": round(stop_buffer, 2),
            "pending_tp_review_buffer": round(pending_tp_buffer, 2),
            "leverage_risk_buffer": round(leverage_buffer, 2),
            "duplicate_exposure_buffer": round(duplicate_buffer, 2),
            "dirty_data_buffer": round(dirty_data_buffer, 2),
            "minimum_cash_reserve": float(minimum_cash_reserve),
        },
        "regime_cap": regime_cap,
        "allowed_new_entries": int(regime.get("allowed_new_entries") or 0),
        "max_size_per_entry": float(regime.get("max_size_per_entry") or 0.0),
        "max_total_new_capital": regime_cap,
        "reason_codes": list(regime.get("reason_codes") or []),
        "advisory_only": True,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "human_execution_required": True,
        "execution_permission": "LOCKED",
    }


__all__ = [
    "REGIME_BUY_ALLOWED",
    "REGIME_BUY_LIMITED",
    "REGIME_BUY_BLOCKED",
    "ALL_REGIMES",
    "DEFAULT_SMALL_ENTRY_SIZE",
    "live_source_score",
    "reconciliation_cleanliness_score",
    "stop_distance_score",
    "cash_available_score",
    "theme_room_score",
    "leverage_safety_score",
    "duplicate_exposure_penalty",
    "open_unreviewed_penalty",
    "dirty_data_penalty",
    "pending_tp_penalty",
    "stop_breach_penalty",
    "compute_portfolio_capacity",
    "classify_portfolio_regime",
    "compute_risk_budget",
]
