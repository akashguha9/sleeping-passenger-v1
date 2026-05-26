"""Buy Admission Board — candidate classification.

Capital Rotation Engine — buy-side admission layer.

For every prospective new entry, compute a deterministic
``candidate_admission_score`` and assign one of the eight admission
classes from Section 9:

  - ``ADDITIVE_OK``
  - ``ADD_SMALL_ONLY``
  - ``REPLACE_WEAKER_HOLDING``
  - ``DIVERSIFY_OK``
  - ``DUPLICATE_EXPOSURE``
  - ``BLOCKED_BY_THEME_CAP``
  - ``BLOCKED_BY_PORTFOLIO_REGIME``
  - ``WATCH_ONLY``

Pure module
-----------
- No DB / filesystem / network / broker calls / AI execution.
- Importing has no side effects.
- Outputs include the advisory-only invariants.
"""
from __future__ import annotations

from typing import Any, Iterable

try:
    from scripts.economic_exposure import (
        map_theme_buckets,
        normalize_economic_exposure,
    )
    from scripts.portfolio_capacity import (
        REGIME_BUY_ALLOWED,
        REGIME_BUY_BLOCKED,
        REGIME_BUY_LIMITED,
    )
    from scripts.theme_slot_accounting import (
        STATUS_NEAR_CAP,
        STATUS_OVER_CAP,
    )
except ModuleNotFoundError:  # pragma: no cover — flat-layout fallback
    from economic_exposure import (  # type: ignore
        map_theme_buckets,
        normalize_economic_exposure,
    )
    from portfolio_capacity import (  # type: ignore
        REGIME_BUY_ALLOWED,
        REGIME_BUY_BLOCKED,
        REGIME_BUY_LIMITED,
    )
    from theme_slot_accounting import (  # type: ignore
        STATUS_NEAR_CAP,
        STATUS_OVER_CAP,
    )


ADM_ADDITIVE_OK = "ADDITIVE_OK"
ADM_ADD_SMALL_ONLY = "ADD_SMALL_ONLY"
ADM_REPLACE_WEAKER_HOLDING = "REPLACE_WEAKER_HOLDING"
ADM_DIVERSIFY_OK = "DIVERSIFY_OK"
ADM_DUPLICATE_EXPOSURE = "DUPLICATE_EXPOSURE"
ADM_BLOCKED_BY_THEME_CAP = "BLOCKED_BY_THEME_CAP"
ADM_BLOCKED_BY_PORTFOLIO_REGIME = "BLOCKED_BY_PORTFOLIO_REGIME"
ADM_WATCH_ONLY = "WATCH_ONLY"

ALL_ADMISSIONS: tuple[str, ...] = (
    ADM_ADDITIVE_OK,
    ADM_ADD_SMALL_ONLY,
    ADM_REPLACE_WEAKER_HOLDING,
    ADM_DIVERSIFY_OK,
    ADM_DUPLICATE_EXPOSURE,
    ADM_BLOCKED_BY_THEME_CAP,
    ADM_BLOCKED_BY_PORTFOLIO_REGIME,
    ADM_WATCH_ONLY,
)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _safe_float(value: Any, default: float = 0.5) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _candidate_themes(candidate: dict[str, Any]) -> list[str]:
    ticker = candidate.get("ticker") or candidate.get("symbol")
    md = {
        "country": candidate.get("country"),
        "leverage": candidate.get("leverage"),
        "sector": candidate.get("sector"),
    }
    return map_theme_buckets(ticker, md)


def _theme_row_for(theme: str, theme_rows: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    for row in theme_rows or []:
        if row.get("theme") == theme:
            return row
    return None


def _weakest_holding_in_theme(
    theme: str,
    theme_rows: Iterable[dict[str, Any]],
    exit_rows: Iterable[dict[str, Any]],
) -> tuple[str | None, float]:
    """Return ``(ticker, strength)`` of the weakest holding in ``theme``.

    Falls back to ``(None, 1.0)`` when no holdings present.
    """
    row = _theme_row_for(theme, theme_rows)
    if not row:
        return None, 1.0
    holdings = list(row.get("holdings") or [])
    if not holdings:
        return None, 1.0
    by_ticker = {r.get("ticker"): r for r in (exit_rows or [])}
    weakest: tuple[str, float] | None = None
    for t in holdings:
        r = by_ticker.get(t)
        if r is None:
            score = 0.5
        else:
            score = _safe_float(r.get("thesis_score"), 0.5)
        if weakest is None or score < weakest[1]:
            weakest = (t, score)
    return weakest or (None, 1.0)


def compute_candidate_admission_score(
    candidate: dict[str, Any],
    *,
    portfolio_regime: str,
    theme_rows: Iterable[dict[str, Any]],
    exit_rows: Iterable[dict[str, Any]],
    held_exposures: Iterable[str],
) -> dict[str, Any]:
    """Compute the Section-9 composite + the per-component breakdown."""
    candidate_score = _safe_float(candidate.get("candidate_score"), 0.5)
    execution_readiness = _safe_float(candidate.get("execution_readiness_score"), 0.5)
    why_today = _safe_float(candidate.get("why_today_score"), 0.5)

    themes = _candidate_themes(candidate)
    theme_room_components: list[float] = []
    near_or_over_cap = False
    diversification_components: list[float] = []
    for theme in themes:
        row = _theme_row_for(theme, theme_rows)
        if row is None:
            theme_room_components.append(0.5)
            continue
        util = float(row.get("utilization") or 0.0)
        theme_room_components.append(_clamp(1.0 - util, 0.0, 1.0))
        if row.get("status") in {STATUS_NEAR_CAP, STATUS_OVER_CAP}:
            near_or_over_cap = True
        if util < 0.5:
            diversification_components.append(0.8)
        else:
            diversification_components.append(0.3)
    theme_room_score = (
        sum(theme_room_components) / len(theme_room_components)
        if theme_room_components
        else 0.5
    )
    diversification_score = (
        sum(diversification_components) / len(diversification_components)
        if diversification_components
        else 0.5
    )

    # Relative superiority vs the weakest holding in any overlapping theme.
    rel_sup_components: list[float] = []
    weakest_target: str | None = None
    for theme in themes:
        target, target_score = _weakest_holding_in_theme(
            theme, theme_rows, exit_rows
        )
        if target is not None:
            delta = candidate_score - target_score
            rel_sup_components.append(_clamp(0.5 + delta, 0.0, 1.0))
            if weakest_target is None:
                weakest_target = target
    relative_superiority = (
        sum(rel_sup_components) / len(rel_sup_components)
        if rel_sup_components
        else 0.5
    )

    exposure_key = normalize_economic_exposure(
        candidate.get("ticker") or candidate.get("symbol")
    )
    held = {str(e).strip().upper() for e in held_exposures or [] if e}
    overlap_dup = exposure_key.upper() in held

    overlap_penalty = 1.0 if overlap_dup else 0.0
    high_beta = bool(candidate.get("high_beta") or candidate.get("speculative"))
    high_beta_penalty = 0.5 if high_beta else 0.0

    if portfolio_regime == REGIME_BUY_BLOCKED:
        regime_penalty = 1.0
    elif portfolio_regime == REGIME_BUY_LIMITED:
        regime_penalty = 0.2
    else:
        regime_penalty = 0.0

    raw = (
        0.25 * candidate_score
        + 0.20 * execution_readiness
        + 0.20 * why_today
        + 0.15 * theme_room_score
        + 0.10 * diversification_score
        + 0.10 * relative_superiority
        - 0.20 * overlap_penalty
        - 0.20 * high_beta_penalty
        - 0.25 * regime_penalty
    )
    final = _clamp(raw, 0.0, 1.0)

    return {
        "candidate_admission_score": round(final, 4),
        "candidate_themes": themes,
        "components": {
            "candidate_score": round(candidate_score, 4),
            "execution_readiness_score": round(execution_readiness, 4),
            "why_today_score": round(why_today, 4),
            "theme_room_score": round(theme_room_score, 4),
            "diversification_score": round(diversification_score, 4),
            "relative_superiority_score": round(relative_superiority, 4),
            "overlap_penalty": round(overlap_penalty, 4),
            "high_beta_penalty": round(high_beta_penalty, 4),
            "regime_penalty": round(regime_penalty, 4),
        },
        "duplicate_exposure": overlap_dup,
        "near_or_over_cap_theme": near_or_over_cap,
        "weakest_replace_target": weakest_target,
        "exposure_key": exposure_key,
        "high_beta": high_beta,
    }


def classify_buy_admission(
    candidate: dict[str, Any],
    *,
    portfolio_regime: str,
    regime_max_size_per_entry: float,
    theme_rows: Iterable[dict[str, Any]],
    exit_rows: Iterable[dict[str, Any]],
    held_exposures: Iterable[str],
) -> dict[str, Any]:
    """Return the full Section-9 candidate row."""
    scored = compute_candidate_admission_score(
        candidate,
        portfolio_regime=portfolio_regime,
        theme_rows=theme_rows,
        exit_rows=exit_rows,
        held_exposures=held_exposures,
    )
    score = float(scored["candidate_admission_score"])
    themes = scored["candidate_themes"]
    duplicate = scored["duplicate_exposure"]
    near_cap = scored["near_or_over_cap_theme"]
    weakest_target = scored["weakest_replace_target"]
    why_today_score = float(scored["components"]["why_today_score"])

    # Find the theme rows for this candidate's themes to detect HARD cap.
    over_cap_in_themes = False
    for theme in themes:
        row = _theme_row_for(theme, theme_rows)
        if row and row.get("status") == STATUS_OVER_CAP:
            over_cap_in_themes = True
            break

    reasons: list[str] = []
    add_or_replace = "ADD"
    max_allowed_size = float(regime_max_size_per_entry)
    max_allowed_leverage = 1.0

    if portfolio_regime == REGIME_BUY_BLOCKED:
        admission = ADM_BLOCKED_BY_PORTFOLIO_REGIME
        reasons.append("portfolio_regime=BUY_BLOCKED")
        max_allowed_size = 0.0
    elif duplicate:
        admission = ADM_DUPLICATE_EXPOSURE
        reasons.append(f"duplicate_economic_exposure={scored['exposure_key']}")
        max_allowed_size = 0.0
    elif over_cap_in_themes and weakest_target:
        # Hard cap exceeded but a replacement target exists.
        if score >= 0.55:
            admission = ADM_REPLACE_WEAKER_HOLDING
            add_or_replace = "REPLACE"
            reasons.append("theme_hard_cap_with_replacement_target")
        else:
            admission = ADM_BLOCKED_BY_THEME_CAP
            reasons.append("theme_hard_cap_no_clear_advantage")
            max_allowed_size = 0.0
    elif over_cap_in_themes:
        admission = ADM_BLOCKED_BY_THEME_CAP
        reasons.append("theme_hard_cap_no_replacement_target")
        max_allowed_size = 0.0
    elif (
        portfolio_regime == REGIME_BUY_ALLOWED
        and score >= 0.75
        and not near_cap
        and why_today_score >= 0.60
    ):
        admission = ADM_ADDITIVE_OK
        reasons.append("regime_allowed_and_score_strong")
    elif (
        portfolio_regime == REGIME_BUY_ALLOWED
        and scored["components"]["diversification_score"] >= 0.7
        and score >= 0.55
    ):
        admission = ADM_DIVERSIFY_OK
        reasons.append("opens_underused_theme")
    elif portfolio_regime == REGIME_BUY_LIMITED and score >= 0.55:
        admission = ADM_ADD_SMALL_ONLY
        reasons.append("regime_limited_with_acceptable_score")
        max_allowed_size = min(max_allowed_size, 50.0)
    elif near_cap and score >= 0.65 and weakest_target:
        admission = ADM_REPLACE_WEAKER_HOLDING
        add_or_replace = "REPLACE"
        reasons.append("theme_near_cap_with_better_candidate")
    else:
        admission = ADM_WATCH_ONLY
        reasons.append("not_admission_ready")
        max_allowed_size = 0.0

    return {
        "ticker": str(candidate.get("ticker") or candidate.get("symbol") or ""),
        "economic_exposure_key": scored["exposure_key"],
        "theme_buckets": themes,
        "candidate_score": scored["components"]["candidate_score"],
        "execution_readiness_score": scored["components"]["execution_readiness_score"],
        "why_today_score": scored["components"]["why_today_score"],
        "theme_room_score": scored["components"]["theme_room_score"],
        "diversification_score": scored["components"]["diversification_score"],
        "relative_superiority_score": scored["components"]["relative_superiority_score"],
        "overlap_penalty": scored["components"]["overlap_penalty"],
        "high_beta_penalty": scored["components"]["high_beta_penalty"],
        "regime_penalty": scored["components"]["regime_penalty"],
        "candidate_admission_score": score,
        "buy_admission_class": admission,
        "add_or_replace_recommendation": add_or_replace,
        "replace_target_ticker": weakest_target if add_or_replace == "REPLACE" else None,
        "max_allowed_size": max_allowed_size,
        "max_allowed_leverage": max_allowed_leverage,
        "reason_codes": reasons,
        "advisory_only": True,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "human_execution_required": True,
        "execution_permission": "LOCKED",
    }


def build_buy_admission_board(
    candidates: Iterable[dict[str, Any]],
    *,
    portfolio_regime: str,
    regime_max_size_per_entry: float,
    theme_rows: Iterable[dict[str, Any]],
    exit_rows: Iterable[dict[str, Any]],
    held_exposures: Iterable[str],
) -> dict[str, Any]:
    rows = []
    counts: dict[str, int] = {a: 0 for a in ALL_ADMISSIONS}
    theme_rows_list = list(theme_rows or [])
    exit_rows_list = list(exit_rows or [])
    exposures_list = list(held_exposures or [])
    for cand in candidates or []:
        if not isinstance(cand, dict):
            continue
        row = classify_buy_admission(
            cand,
            portfolio_regime=portfolio_regime,
            regime_max_size_per_entry=regime_max_size_per_entry,
            theme_rows=theme_rows_list,
            exit_rows=exit_rows_list,
            held_exposures=exposures_list,
        )
        rows.append(row)
        counts[row["buy_admission_class"]] = (
            counts.get(row["buy_admission_class"], 0) + 1
        )
    return {
        "rows": rows,
        "counts": counts,
        "candidate_count": len(rows),
        "portfolio_regime": portfolio_regime,
        "advisory_only": True,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "human_execution_required": True,
        "execution_permission": "LOCKED",
    }


__all__ = [
    "ADM_ADDITIVE_OK",
    "ADM_ADD_SMALL_ONLY",
    "ADM_REPLACE_WEAKER_HOLDING",
    "ADM_DIVERSIFY_OK",
    "ADM_DUPLICATE_EXPOSURE",
    "ADM_BLOCKED_BY_THEME_CAP",
    "ADM_BLOCKED_BY_PORTFOLIO_REGIME",
    "ADM_WATCH_ONLY",
    "ALL_ADMISSIONS",
    "compute_candidate_admission_score",
    "classify_buy_admission",
    "build_buy_admission_board",
]
