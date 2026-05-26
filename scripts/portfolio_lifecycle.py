"""Portfolio lifecycle — exit classification + thesis scoring.

Capital Rotation Engine — exit + thesis layer.

Two deterministic pure functions live here.  They take a *position dict*
(plus an optional ``context``) and return classifications.  Neither
function ever reaches a broker, fetches a price, or grants execution
permission — all live inputs are passed in by the caller.

Exit lifecycle statuses
-----------------------
Priority-ordered (first match wins):

1. ``DATA_BLOCKED``         — critical input missing
2. ``EXIT_NOW``             — stop breach / thesis broken / phantom row
3. ``PARTIAL_TP_NOW``       — at TP and partial not yet logged
4. ``RUNNER_EXIT_REVIEW``   — runner under trailing stop / thesis decay
5. ``RUNNER_HOLD``          — clean runner, thesis confirmed/unchanged
6. ``TRIM_REVIEW``          — theme cap / duplicate / overcrowding
7. ``STALE_REVIEW``         — past horizon and unproductive
8. ``HOLD_OK``              — none of the above

Thesis statuses
---------------
- ``THESIS_CONFIRMED``  thesis_score >= 0.75
- ``THESIS_UNCHANGED``  0.55 <= thesis_score < 0.75
- ``THESIS_DECAYING``   0.35 <= thesis_score < 0.55
- ``THESIS_BROKEN``     thesis_score < 0.35  *or* hard invalidation
- ``THESIS_REPLACED``   stronger candidate in same theme by >= 0.20

Contract — pure module
----------------------
- No DB, no filesystem, no network, no broker calls, no AI execution.
- Importing this module has no side effects.
- All outputs include ``advisory_only=True`` semantics indirectly via
  the caller's stamps (the route layer and summary writer attach them).
"""
from __future__ import annotations

import math
from typing import Any

try:
    from scripts.economic_exposure import (
        normalize_economic_exposure,
        map_theme_buckets,
    )
except ModuleNotFoundError:  # pragma: no cover — flat-layout fallback
    from economic_exposure import (  # type: ignore
        normalize_economic_exposure,
        map_theme_buckets,
    )


# ---------------------------------------------------------------------------
# Exit-status vocabulary
# ---------------------------------------------------------------------------

EXIT_DATA_BLOCKED = "DATA_BLOCKED"
EXIT_NOW = "EXIT_NOW"
EXIT_PARTIAL_TP_NOW = "PARTIAL_TP_NOW"
EXIT_RUNNER_EXIT_REVIEW = "RUNNER_EXIT_REVIEW"
EXIT_RUNNER_HOLD = "RUNNER_HOLD"
EXIT_TRIM_REVIEW = "TRIM_REVIEW"
EXIT_STALE_REVIEW = "STALE_REVIEW"
EXIT_HOLD_OK = "HOLD_OK"

ALL_EXIT_STATUSES: tuple[str, ...] = (
    EXIT_DATA_BLOCKED,
    EXIT_NOW,
    EXIT_PARTIAL_TP_NOW,
    EXIT_RUNNER_EXIT_REVIEW,
    EXIT_RUNNER_HOLD,
    EXIT_TRIM_REVIEW,
    EXIT_STALE_REVIEW,
    EXIT_HOLD_OK,
)


# ---------------------------------------------------------------------------
# Thesis-status vocabulary
# ---------------------------------------------------------------------------

THESIS_CONFIRMED = "THESIS_CONFIRMED"
THESIS_UNCHANGED = "THESIS_UNCHANGED"
THESIS_DECAYING = "THESIS_DECAYING"
THESIS_BROKEN = "THESIS_BROKEN"
THESIS_REPLACED = "THESIS_REPLACED"

ALL_THESIS_STATUSES: tuple[str, ...] = (
    THESIS_CONFIRMED,
    THESIS_UNCHANGED,
    THESIS_DECAYING,
    THESIS_BROKEN,
    THESIS_REPLACED,
)


# ---------------------------------------------------------------------------
# Small numeric helpers
# ---------------------------------------------------------------------------


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def _truthy_yes(value: Any) -> bool:
    """Treat ``True``/``1``/``'YES'``/``'TRUE'``/``'Y'`` as yes."""
    if value is True:
        return True
    if value in (1, "1"):
        return True
    if isinstance(value, str):
        return value.strip().upper() in {"YES", "TRUE", "Y", "T"}
    return False


def _resolve_lambda(expected_horizon_days: float | None) -> float:
    """Pick the freshness-decay constant by horizon length.

    Short trades decay fast; long-horizon trades decay slow.
    """
    h = expected_horizon_days or 0
    if h <= 5:
        return 0.25
    if h >= 60:
        return 0.08
    return 0.15


# ---------------------------------------------------------------------------
# Numeric derivations from a position dict
# ---------------------------------------------------------------------------


def compute_position_metrics(position: dict[str, Any]) -> dict[str, Any]:
    """Derive every numeric the classifier needs from one position dict.

    Missing inputs become ``None`` rather than ``0`` so the data-quality
    branch can detect them.  Returns a dict with all derived numbers
    plus a ``data_ok`` boolean.
    """
    p_i = _safe_float(position.get("live_price"))
    b_i = _safe_float(position.get("buy_price") or position.get("entry_price"))
    s_i = _safe_float(position.get("stop_loss"))
    t_i = _safe_float(position.get("tp_price") or position.get("take_profit_price"))
    trailing = _safe_float(position.get("trailing_stop"))
    L_i = _safe_float(position.get("leverage"))
    if L_i is None or L_i <= 0:
        L_i = 1.0
    age_i = _safe_float(position.get("age_days") or position.get("days_open"))
    h_i = _safe_float(
        position.get("expected_horizon_days") or position.get("expected_horizon")
    )
    partial = _truthy_yes(position.get("partial_tp_logged"))
    booked = _safe_float(position.get("booked_pct"))
    ride = _safe_float(position.get("ride_pct"))

    pnl_pct = None
    if p_i is not None and b_i is not None and b_i > 0:
        pnl_pct = (p_i - b_i) / b_i
    leveraged_pnl_pct = None
    if pnl_pct is not None:
        leveraged_pnl_pct = L_i * pnl_pct

    distance_to_stop_pct = None
    if p_i is not None and s_i is not None and p_i > 0:
        distance_to_stop_pct = (p_i - s_i) / p_i
    distance_to_tp_pct = None
    if p_i is not None and t_i is not None and p_i > 0:
        distance_to_tp_pct = (t_i - p_i) / p_i

    stop_breach = bool(p_i is not None and s_i is not None and p_i <= s_i)
    trailing_breach = bool(
        trailing is not None and p_i is not None and p_i <= trailing
    )
    tp_due = bool(
        p_i is not None and t_i is not None and p_i >= t_i and not partial
    )

    runner_active = bool(
        partial
        and (booked is not None and booked >= 70)
        and (ride is not None and ride <= 30)
    )

    staleness_ratio = None
    time_stop_risk = None
    if age_i is not None and h_i is not None and h_i > 0:
        staleness_ratio = age_i / h_i
        time_stop_risk = _clamp((age_i - h_i) / h_i, 0.0, 1.0)

    lam = _resolve_lambda(h_i)
    freshness_score = None
    if age_i is not None:
        freshness_score = math.exp(-lam * max(0.0, age_i))

    source_health = str(position.get("source_health") or "").strip().upper()
    currency_ok = True
    if position.get("currency") and position.get("entry_currency"):
        currency_ok = (
            str(position.get("currency")).upper()
            == str(position.get("entry_currency")).upper()
        )

    data_ok = (
        p_i is not None
        and b_i is not None
        and s_i is not None
        and t_i is not None
        and source_health not in {"", "UNVERIFIED", "STATIC_FALLBACK", "MISSING"}
        and currency_ok
    )

    return {
        "live_price": p_i,
        "buy_price": b_i,
        "stop_loss": s_i,
        "tp_price": t_i,
        "trailing_stop": trailing,
        "leverage": L_i,
        "age_days": age_i,
        "expected_horizon_days": h_i,
        "partial_tp_logged": partial,
        "booked_pct": booked,
        "ride_pct": ride,
        "pnl_pct": pnl_pct,
        "leveraged_pnl_pct": leveraged_pnl_pct,
        "distance_to_stop_pct": distance_to_stop_pct,
        "distance_to_tp_pct": distance_to_tp_pct,
        "stop_breach": stop_breach,
        "trailing_breach": trailing_breach,
        "tp_due": tp_due,
        "runner_active": runner_active,
        "staleness_ratio": staleness_ratio,
        "time_stop_risk": time_stop_risk,
        "freshness_score": freshness_score,
        "source_health": source_health,
        "currency_ok": currency_ok,
        "data_ok": data_ok,
    }


# ---------------------------------------------------------------------------
# Thesis scoring
# ---------------------------------------------------------------------------


def _price_structure_score(metrics: dict[str, Any]) -> float:
    p = metrics.get("live_price")
    b = metrics.get("buy_price")
    s = metrics.get("stop_loss")
    if metrics.get("stop_breach"):
        return 0.0
    if p is None or b is None:
        return 0.5
    if p >= b:
        return 1.0
    if s is not None and p > s:
        return 0.4
    return 0.7


def compute_thesis_score(
    position: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> float:
    """Weighted composite thesis score in [0,1].

    The optional ``context`` may carry:
      - ``relative_strength_score`` ∈ [0,1]
      - ``catalyst_validity_score`` ∈ [0,1]
      - ``theme_quality_score`` ∈ [0,1]
      - ``hard_invalidation`` (bool) — if True, returns 0.0 directly.

    Missing context components default to 0.5 (neutral) — the function
    never fabricates evidence.
    """
    ctx = context or {}
    if ctx.get("hard_invalidation") is True or _truthy_yes(
        position.get("hard_invalidation_breached")
    ):
        return 0.0

    metrics = compute_position_metrics(position)
    price_structure = _price_structure_score(metrics)
    freshness = metrics.get("freshness_score")
    if freshness is None:
        freshness = 0.5
    rs = _safe_float(ctx.get("relative_strength_score"))
    if rs is None:
        rs = 0.5
    cat = _safe_float(ctx.get("catalyst_validity_score"))
    if cat is None:
        cat = 0.5
    theme = _safe_float(ctx.get("theme_quality_score"))
    if theme is None:
        theme = 0.5

    raw = (
        0.30 * price_structure
        + 0.20 * freshness
        + 0.20 * _clamp(rs, 0.0, 1.0)
        + 0.15 * _clamp(cat, 0.0, 1.0)
        + 0.15 * _clamp(theme, 0.0, 1.0)
    )
    return _clamp(raw, 0.0, 1.0)


def classify_thesis_status(
    score: float,
    *,
    hard_invalidation: bool = False,
    replaced_by_stronger_candidate: bool = False,
) -> str:
    """Bucket a thesis score into one of the five status labels."""
    if hard_invalidation:
        return THESIS_BROKEN
    if replaced_by_stronger_candidate:
        return THESIS_REPLACED
    if score < 0.35:
        return THESIS_BROKEN
    if score < 0.55:
        return THESIS_DECAYING
    if score < 0.75:
        return THESIS_UNCHANGED
    return THESIS_CONFIRMED


# ---------------------------------------------------------------------------
# Exit-status classification
# ---------------------------------------------------------------------------


def _is_phantom(position: dict[str, Any]) -> bool:
    state = str(
        position.get("trade_state")
        or position.get("status")
        or ""
    ).strip().upper()
    if state in {"CLOSED", "EXITED", "SOLD", "DO_NOT_MANAGE"}:
        return True
    if _truthy_yes(position.get("do_not_manage")):
        return True
    if _truthy_yes(position.get("phantom_row")):
        return True
    return False


def classify_exit_status(
    position: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return ``{"exit_status": ..., "reason_codes": [...], "metrics": {...}}``.

    Priority-ordered per the spec.  ``context`` may carry:

      - ``thesis_status``                            (precomputed)
      - ``thesis_score``                             (precomputed)
      - ``theme_hard_cap_exceeded``      (bool)
      - ``duplicate_economic_exposure``  (bool)
      - ``weakest_in_overcrowded_theme`` (bool)
      - ``hard_invalidation``            (bool)

    All inputs are passed in; nothing is fetched.
    """
    ctx = context or {}
    metrics = compute_position_metrics(position)
    reasons: list[str] = []

    # 1. DATA_BLOCKED
    if not metrics["data_ok"]:
        missing: list[str] = []
        if metrics["live_price"] is None:
            missing.append("live_price")
        if metrics["buy_price"] is None:
            missing.append("buy_price")
        if metrics["stop_loss"] is None:
            missing.append("stop_loss")
        if metrics["tp_price"] is None:
            missing.append("tp_price")
        if metrics["source_health"] in {"", "UNVERIFIED", "STATIC_FALLBACK", "MISSING"}:
            missing.append(f"source_health={metrics['source_health'] or 'MISSING'}")
        if not metrics["currency_ok"]:
            missing.append("currency_mismatch")
        reasons.append("data_blocked:" + ",".join(missing))
        return {
            "exit_status": EXIT_DATA_BLOCKED,
            "reason_codes": reasons,
            "metrics": metrics,
        }

    # 2. EXIT_NOW
    thesis_status = ctx.get("thesis_status")
    thesis_score = _safe_float(ctx.get("thesis_score"))
    hard_inv = bool(
        ctx.get("hard_invalidation")
        or _truthy_yes(position.get("hard_invalidation_breached"))
    )
    if metrics["stop_breach"]:
        reasons.append("stop_breach")
    if _is_phantom(position):
        reasons.append("phantom_or_do_not_manage_row")
    if thesis_status == THESIS_BROKEN or hard_inv:
        reasons.append("thesis_broken_or_hard_invalidation")
    if reasons:
        return {
            "exit_status": EXIT_NOW,
            "reason_codes": reasons,
            "metrics": metrics,
        }

    # 3. PARTIAL_TP_NOW
    if metrics["tp_due"]:
        return {
            "exit_status": EXIT_PARTIAL_TP_NOW,
            "reason_codes": ["live_price_at_or_above_tp", "partial_tp_not_logged"],
            "metrics": metrics,
        }

    # 4 + 5. Runner branches
    if metrics["partial_tp_logged"] and metrics["runner_active"]:
        runner_in_trouble = (
            metrics["trailing_breach"]
            or thesis_status in {THESIS_DECAYING, THESIS_BROKEN, THESIS_REPLACED}
        )
        if runner_in_trouble:
            why: list[str] = ["runner_active"]
            if metrics["trailing_breach"]:
                why.append("trailing_stop_breach")
            if thesis_status in {THESIS_DECAYING, THESIS_BROKEN, THESIS_REPLACED}:
                why.append(f"thesis={thesis_status}")
            return {
                "exit_status": EXIT_RUNNER_EXIT_REVIEW,
                "reason_codes": why,
                "metrics": metrics,
            }
        if thesis_status in {None, THESIS_CONFIRMED, THESIS_UNCHANGED}:
            return {
                "exit_status": EXIT_RUNNER_HOLD,
                "reason_codes": ["runner_active", f"thesis={thesis_status or 'unknown'}"],
                "metrics": metrics,
            }

    # 6. TRIM_REVIEW
    trim_reasons: list[str] = []
    if ctx.get("theme_hard_cap_exceeded"):
        trim_reasons.append("theme_hard_cap_exceeded")
    if ctx.get("duplicate_economic_exposure"):
        trim_reasons.append("duplicate_economic_exposure")
    if ctx.get("weakest_in_overcrowded_theme"):
        trim_reasons.append("weakest_in_overcrowded_theme")
    if trim_reasons:
        return {
            "exit_status": EXIT_TRIM_REVIEW,
            "reason_codes": trim_reasons,
            "metrics": metrics,
        }

    # 7. STALE_REVIEW
    if metrics["age_days"] is not None and metrics["expected_horizon_days"]:
        if metrics["age_days"] > metrics["expected_horizon_days"]:
            pnl = metrics["pnl_pct"] or 0.0
            fresh = metrics["freshness_score"] or 1.0
            if pnl <= 0.0 or fresh < 0.30:
                return {
                    "exit_status": EXIT_STALE_REVIEW,
                    "reason_codes": [
                        "past_expected_horizon",
                        f"pnl_pct={round(pnl, 4)}",
                        f"freshness={round(fresh, 4)}",
                    ],
                    "metrics": metrics,
                }

    # 8. HOLD_OK
    return {
        "exit_status": EXIT_HOLD_OK,
        "reason_codes": ["all_checks_passed"],
        "metrics": metrics,
    }


def classify_position(
    position: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run thesis + exit classification in one call.

    Returns a row matching the Section-3 schema (ticker / theme buckets /
    exit_status / thesis_status / metrics / reason codes / advisory
    flags).  Pure: ``position`` is not mutated.
    """
    ctx = dict(context or {})
    ticker = (
        position.get("normalized_ticker")
        or position.get("ticker")
        or position.get("symbol")
        or ""
    )
    metadata = {
        "country": position.get("country"),
        "leverage": position.get("leverage"),
        "sector": position.get("sector"),
    }
    themes = map_theme_buckets(ticker, metadata)
    exposure_key = normalize_economic_exposure(ticker)

    thesis_score = compute_thesis_score(position, ctx)
    hard_inv = bool(
        ctx.get("hard_invalidation")
        or _truthy_yes(position.get("hard_invalidation_breached"))
    )
    replaced = bool(ctx.get("replaced_by_stronger_candidate"))
    thesis_status = classify_thesis_status(
        thesis_score,
        hard_invalidation=hard_inv,
        replaced_by_stronger_candidate=replaced,
    )

    # Feed thesis status back into the exit classifier so runner branches
    # see it.
    ctx_with_thesis = dict(ctx)
    ctx_with_thesis.setdefault("thesis_status", thesis_status)
    ctx_with_thesis.setdefault("thesis_score", thesis_score)
    exit_result = classify_exit_status(position, ctx_with_thesis)
    metrics = exit_result["metrics"]

    return {
        "ticker": str(ticker),
        "economic_exposure_key": exposure_key,
        "theme_buckets": themes,
        "trade_state": str(
            position.get("trade_state") or position.get("status") or ""
        ),
        "buy_price": metrics["buy_price"],
        "live_price": metrics["live_price"],
        "stop_loss": metrics["stop_loss"],
        "tp_price": metrics["tp_price"],
        "partial_tp_logged": metrics["partial_tp_logged"],
        "booked_pct": metrics["booked_pct"],
        "ride_pct": metrics["ride_pct"],
        "age_days": metrics["age_days"],
        "expected_horizon_days": metrics["expected_horizon_days"],
        "leverage": metrics["leverage"],
        "pnl_pct": metrics["pnl_pct"],
        "leveraged_pnl_pct": metrics["leveraged_pnl_pct"],
        "distance_to_stop_pct": metrics["distance_to_stop_pct"],
        "distance_to_tp_pct": metrics["distance_to_tp_pct"],
        "freshness_score": metrics["freshness_score"],
        "thesis_score": thesis_score,
        "thesis_status": thesis_status,
        "exit_status": exit_result["exit_status"],
        "reason_codes": exit_result["reason_codes"],
        "human_action_required": exit_result["exit_status"] != EXIT_HOLD_OK,
        "advisory_only": True,
        "broker_api_called": False,
        "ai_execution_count": 0,
    }


__all__ = [
    # exit statuses
    "EXIT_DATA_BLOCKED",
    "EXIT_NOW",
    "EXIT_PARTIAL_TP_NOW",
    "EXIT_RUNNER_EXIT_REVIEW",
    "EXIT_RUNNER_HOLD",
    "EXIT_TRIM_REVIEW",
    "EXIT_STALE_REVIEW",
    "EXIT_HOLD_OK",
    "ALL_EXIT_STATUSES",
    # thesis statuses
    "THESIS_CONFIRMED",
    "THESIS_UNCHANGED",
    "THESIS_DECAYING",
    "THESIS_BROKEN",
    "THESIS_REPLACED",
    "ALL_THESIS_STATUSES",
    # functions
    "compute_position_metrics",
    "compute_thesis_score",
    "classify_thesis_status",
    "classify_exit_status",
    "classify_position",
]
