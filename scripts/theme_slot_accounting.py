"""Theme slot accounting — Juego de Posición pitch zones.

Capital Rotation Engine — positional-play layer.

Translates the football positional-play idea into portfolio mechanics:

  - Theme bucket  = pitch zone
  - Holding       = player occupying a zone
  - Overcrowding  = too many players in the same lane
  - Cap breach    = team shape lost
  - Runner        = half-substituted player (counts as fractional slot)
  - Replacement   = positional rotation (drop weaker, bring stronger)

Pure module
-----------
- No DB / filesystem / network / broker calls / AI execution.
- Importing has no side effects.
- All public functions are deterministic.
"""
from __future__ import annotations

from typing import Any, Iterable

try:
    from scripts.economic_exposure import (
        ALL_THEMES,
        THEME_CAPS,
        map_theme_buckets,
        normalize_economic_exposure,
    )
except ModuleNotFoundError:  # pragma: no cover — flat-layout fallback
    from economic_exposure import (  # type: ignore
        ALL_THEMES,
        THEME_CAPS,
        map_theme_buckets,
        normalize_economic_exposure,
    )

STATUS_UNDERUSED = "UNDERUSED"
STATUS_BALANCED = "BALANCED"
STATUS_NEAR_CAP = "NEAR_CAP"
STATUS_OVER_CAP = "OVER_CAP"

# Operator-facing action labels (advisory only).  These are *not* trade
# instructions — they describe what kind of buy/trim move would respect
# the team shape.
ACTION_ADD_OK = "ADD_OK"
ACTION_ADD_SMALL_ONLY = "ADD_SMALL_ONLY"
ACTION_REPLACE_REQUIRED = "REPLACE_REQUIRED"
ACTION_NO_NEW_HERE = "NO_NEW_HERE"

# Standard "full" position size used to compute small-position weight.
# Configurable per call so the operator can dial this for their book.
DEFAULT_STANDARD_POSITION_SIZE = 100.0


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


def _truthy_yes(value: Any) -> bool:
    if value is True or value in (1, "1"):
        return True
    if isinstance(value, str):
        return value.strip().upper() in {"YES", "TRUE", "Y", "T"}
    return False


def position_slot_weight(
    position: dict[str, Any],
    *,
    standard_position_size: float = DEFAULT_STANDARD_POSITION_SIZE,
) -> float:
    """How many "slot units" does this position consume?

    - Runner positions (partial TP logged, booked >= 70, ride <= 30)
      weigh ``ride_pct / 100`` (e.g. 30% ride = 0.30 slots).
    - Small fractional positions weigh ``money_allocated / standard``.
    - Full positions weigh 1.0.
    """
    partial = _truthy_yes(position.get("partial_tp_logged"))
    booked = _safe_float(position.get("booked_pct"))
    ride = _safe_float(position.get("ride_pct"))
    if partial and booked is not None and booked >= 70 and ride is not None and ride <= 30:
        return max(0.0, ride / 100.0)

    money = _safe_float(
        position.get("money_allocated")
        or position.get("notional")
        or position.get("position_value")
    )
    if money is not None and money > 0 and standard_position_size > 0:
        return max(0.0, min(1.0, money / standard_position_size))

    return 1.0


def position_strength_score(position: dict[str, Any]) -> float:
    """Internal proxy for which position is "weakest" in a theme.

    Operates on whatever signals are available:
      - explicit ``thesis_score``           (preferred)
      - else freshness × max(0, pnl_pct+1)  (heuristic)
      - else 0.5 neutral

    The score is bounded to ``[0,1]``; callers compare relatively.
    """
    score = _safe_float(position.get("thesis_score"))
    if score is not None:
        return max(0.0, min(1.0, score))
    pnl = _safe_float(position.get("pnl_pct"))
    fresh = _safe_float(position.get("freshness_score"))
    if pnl is not None and fresh is not None:
        return max(0.0, min(1.0, fresh * max(0.0, pnl + 1.0) * 0.5))
    return 0.5


def _theme_status(used: float, caps: dict[str, int]) -> str:
    warning = float(caps.get("warning_cap", 0) or 0)
    hard = float(caps.get("hard_cap", 0) or 0)
    if hard <= 0:
        return STATUS_BALANCED
    if used >= hard:
        return STATUS_OVER_CAP
    if used >= warning:
        return STATUS_NEAR_CAP
    if used >= hard * 0.5:
        return STATUS_BALANCED
    return STATUS_UNDERUSED


def _allowed_action(status: str) -> str:
    if status == STATUS_OVER_CAP:
        return ACTION_NO_NEW_HERE
    if status == STATUS_NEAR_CAP:
        return ACTION_REPLACE_REQUIRED
    if status == STATUS_BALANCED:
        return ACTION_ADD_SMALL_ONLY
    return ACTION_ADD_OK


def _ticker_label(position: dict[str, Any]) -> str:
    return str(
        position.get("normalized_ticker")
        or position.get("ticker")
        or position.get("symbol")
        or ""
    )


def compute_theme_slots(
    positions: Iterable[dict[str, Any]],
    *,
    standard_position_size: float = DEFAULT_STANDARD_POSITION_SIZE,
    theme_caps: dict[str, dict[str, int]] | None = None,
) -> list[dict[str, Any]]:
    """Aggregate positions into a per-theme summary.

    Returns one row per theme that has at least one holding *or* exists
    in the cap map.  Each row lists the holdings in that theme, the
    weakest-holding candidate(s), and the allowed action.

    A single position can occupy multiple themes — its slot weight is
    counted in *each* theme it occupies (positional play: a single
    player can occupy two zones at once).
    """
    caps_map = dict(theme_caps or THEME_CAPS)
    by_theme: dict[str, dict[str, Any]] = {}
    for theme in ALL_THEMES:
        by_theme[theme] = {
            "theme": theme,
            "used_weight": 0.0,
            "warning_cap": int(caps_map.get(theme, {}).get("warning_cap", 0) or 0),
            "hard_cap": int(caps_map.get(theme, {}).get("hard_cap", 0) or 0),
            "holdings": [],
        }

    for pos in positions or []:
        if not isinstance(pos, dict):
            continue
        ticker = _ticker_label(pos)
        themes = map_theme_buckets(
            ticker,
            {
                "country": pos.get("country"),
                "leverage": pos.get("leverage"),
                "sector": pos.get("sector"),
            },
        )
        weight = position_slot_weight(pos, standard_position_size=standard_position_size)
        strength = position_strength_score(pos)
        record = {
            "ticker": ticker,
            "economic_exposure_key": normalize_economic_exposure(ticker),
            "slot_weight": weight,
            "strength_score": strength,
        }
        for theme in themes:
            bucket = by_theme.setdefault(theme, {
                "theme": theme,
                "used_weight": 0.0,
                "warning_cap": int(caps_map.get(theme, {}).get("warning_cap", 0) or 0),
                "hard_cap": int(caps_map.get(theme, {}).get("hard_cap", 0) or 0),
                "holdings": [],
            })
            bucket["used_weight"] += weight
            bucket["holdings"].append(record)

    rows: list[dict[str, Any]] = []
    for theme, bucket in by_theme.items():
        used = float(bucket["used_weight"])
        hard = float(bucket["hard_cap"] or 0)
        utilization = (used / hard) if hard > 0 else 0.0
        status = _theme_status(used, bucket)
        # Weakest holding candidates: the lowest-strength holding(s) that
        # the operator could rotate out to make room for a better entry.
        holdings_sorted = sorted(
            bucket["holdings"], key=lambda h: h["strength_score"]
        )
        weakest = [
            h["ticker"]
            for h in holdings_sorted[: max(1, min(2, len(holdings_sorted)))]
        ] if holdings_sorted else []
        rows.append(
            {
                "theme": theme,
                "used_weight": round(used, 4),
                "warning_cap": int(bucket["warning_cap"]),
                "hard_cap": int(bucket["hard_cap"]),
                "utilization": round(utilization, 4),
                "status": status,
                "holdings": [h["ticker"] for h in bucket["holdings"]],
                "holding_count": len(bucket["holdings"]),
                "weakest_holding_candidates": weakest,
                "allowed_action": _allowed_action(status),
            }
        )
    # Stable order: themes from ALL_THEMES first, then extras (none expected).
    order_index = {t: i for i, t in enumerate(ALL_THEMES)}
    rows.sort(key=lambda r: order_index.get(r["theme"], 1_000))
    return rows


def theme_slot_summary(
    positions: Iterable[dict[str, Any]],
    *,
    standard_position_size: float = DEFAULT_STANDARD_POSITION_SIZE,
    theme_caps: dict[str, dict[str, int]] | None = None,
) -> dict[str, Any]:
    """Full theme-slot summary: per-theme rows + aggregate counters."""
    rows = compute_theme_slots(
        positions,
        standard_position_size=standard_position_size,
        theme_caps=theme_caps,
    )
    over_cap = [r for r in rows if r["status"] == STATUS_OVER_CAP]
    near_cap = [r for r in rows if r["status"] == STATUS_NEAR_CAP]
    return {
        "themes": rows,
        "over_cap_themes": [r["theme"] for r in over_cap],
        "near_cap_themes": [r["theme"] for r in near_cap],
        "any_hard_cap_exceeded": bool(over_cap),
        "near_cap_count": len(near_cap),
        "over_cap_count": len(over_cap),
        "advisory_only": True,
        "broker_api_called": False,
        "ai_execution_count": 0,
    }


def position_is_weakest_in_overcrowded_theme(
    ticker: Any,
    theme_rows: list[dict[str, Any]],
) -> bool:
    """True if any over/near-cap theme lists this ticker as weakest."""
    target = str(ticker or "").strip()
    if not target:
        return False
    for row in theme_rows or []:
        if row.get("status") not in {STATUS_OVER_CAP, STATUS_NEAR_CAP}:
            continue
        weakest = [str(t) for t in row.get("weakest_holding_candidates") or []]
        if target in weakest:
            return True
        # Also match by normalized ticker shape.
        norm_target = normalize_economic_exposure(target)
        for w in weakest:
            if normalize_economic_exposure(w) == norm_target:
                return True
    return False


__all__ = [
    "STATUS_UNDERUSED",
    "STATUS_BALANCED",
    "STATUS_NEAR_CAP",
    "STATUS_OVER_CAP",
    "ACTION_ADD_OK",
    "ACTION_ADD_SMALL_ONLY",
    "ACTION_REPLACE_REQUIRED",
    "ACTION_NO_NEW_HERE",
    "DEFAULT_STANDARD_POSITION_SIZE",
    "position_slot_weight",
    "position_strength_score",
    "compute_theme_slots",
    "theme_slot_summary",
    "position_is_weakest_in_overcrowded_theme",
]
