"""Objective 8 — minimal capital-rotation / capacity guard (pure, advisory-only).

A deterministic survival-first position-sizing + capacity check.  It is NOT a
portfolio optimiser and it NEVER executes: it returns sizing *metadata* and a
capacity verdict so a human can size their own manual trade conservatively.

Sizing math:

    DownsideRiskPct = (entry - hard_stop) / entry      (long)
                    = (hard_stop - entry) / entry       (short)
    If hard_stop is missing -> DownsideRiskPct unknown, sizing BLOCKED.

    RiskBudget = Capital · BaseRiskPct
               · ConfidenceMultiplier · FreshnessMultiplier
               · MoltbookMultiplier · RegimeMultiplier
        ConfidenceMultiplier = clip((p_adj - 0.5)/0.25, 0, 1)
        FreshnessMultiplier  = clip(FreshnessScore / F_min, 0, 1)
        MoltbookMultiplier   = 1 - MoltbookPenalty
        RegimeMultiplier     = 1 if regime_ok else 0.5

    PositionNotional = min(RiskBudget / DownsideRiskPct, Capital·MaxPositionPct)
    CashRequired     = PositionNotional / Leverage

    Country exposure cap:  (existing + PositionNotional)/Capital <= CountryCap
        CountryCap_India = 0.50 ;  CountryCap_Other = 0.25

    PortfolioCapacityOK = I(DownsideRiskPct known) · I(LeverageValid)
                        · I(CashAvailable >= CashRequired)
                        · I(PositionNotional <= MaxPositionNotional)
                        · I(CountryCap not breached)

Conservative Year-1 defaults: 0.5% capital-at-risk per idea, 10% max single
position, 50%/25% India/other country caps.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.leverage_policy import INDIA_MAX_LEVERAGE, is_india_instrument
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]
    from leverage_policy import INDIA_MAX_LEVERAGE, is_india_instrument  # type: ignore[no-redef]

BASE_RISK_PCT: float = 0.005       # 0.5% capital at risk per advisory idea
MAX_POSITION_PCT: float = 0.10     # 10% max single position notional
COUNTRY_CAP_INDIA: float = 0.50
COUNTRY_CAP_OTHER: float = 0.25
FRESHNESS_FLOOR: float = 0.50      # F_min

# Advisory classes (no execution wording).
ADVISORY_CANDIDATE = "ADVISORY_CANDIDATE_FOR_HUMAN_REVIEW"
WAIT = "WAIT"
BLOCKED_BY_PORTFOLIO_CAPACITY = "BLOCKED_BY_PORTFOLIO_CAPACITY"


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


NEW_INDIA_ADD_BLOCKED = "NEW_INDIA_ADD_BLOCKED_UNRESOLVED_RISK"


def new_india_add_allowed(
    *,
    ticker: str | None = None,
    country: str | None = None,
    existing_india_risk_unresolved: bool = False,
    existing_india_leverage: float = 1.0,
    existing_india_position_count: int = 0,
    live_price_visibility_ok: bool = True,
    live_risk_visibility_ok: bool = True,
) -> dict[str, Any]:
    """Hard binary gate for opening a NEW India candidate. Advisory, never executes.

    ``new_india_add_allowed`` is ``False`` (a hard block, not a soft downgrade)
    when, for an Indian instrument, ANY of the following holds:

    * existing India risk is unresolved, OR
    * existing India exposure is at the 4x leverage ceiling AND live price OR
      live risk visibility is degraded.

    This gate ONLY governs NEW India adds. It deliberately carries no power over
    the review/management of an *existing* India holding — the returned
    ``existing_position_review_unaffected`` flag makes that contract explicit. A
    non-India instrument is out of scope and is always allowed by this gate.
    """
    stamps = advisory_safety_stamps()
    is_india = is_india_instrument(ticker, country)
    try:
        lev = float(existing_india_leverage)
    except (TypeError, ValueError):
        lev = 1.0

    reasons: list[str] = []
    at_leverage_ceiling = lev >= INDIA_MAX_LEVERAGE
    visibility_degraded = not (live_price_visibility_ok and live_risk_visibility_ok)

    if is_india:
        if existing_india_risk_unresolved:
            reasons.append(
                "existing India risk is unresolved; no new India add permitted"
            )
        if at_leverage_ceiling and visibility_degraded:
            reasons.append(
                f"existing India exposure at {lev:g}x ceiling "
                f"(>= {INDIA_MAX_LEVERAGE:g}x) with degraded live price/risk "
                "visibility; no new India add permitted"
            )

    allowed = not (is_india and reasons)

    return {
        "ticker": (ticker or "").strip(),
        "is_india_instrument": is_india,
        "new_india_add_allowed": allowed,
        "applies_to": "NEW_INDIA_CANDIDATE_ONLY",
        "existing_position_review_unaffected": True,
        "existing_india_position_count": int(existing_india_position_count or 0),
        "existing_india_leverage": lev,
        "live_price_visibility_ok": bool(live_price_visibility_ok),
        "live_risk_visibility_ok": bool(live_risk_visibility_ok),
        "advisory_class": NEW_INDIA_ADD_BLOCKED if not allowed else ADVISORY_CANDIDATE,
        "blocking_reasons": reasons,
        # Advisory-only invariants — present whether allowed or blocked.
        "advisory_status": stamps.get("advisory_status"),
        "execution_gate": stamps["execution_gate"],
        "broker_api_called": stamps["broker_api_called"],
        "ai_execution_count": stamps["ai_execution_count"],
        "human_execution_required": True,
        "executes_trade": False,
    }


def compute_downside_risk_pct(
    entry_price: float | None,
    hard_stop_price: float | None,
    side: str = "BUY",
) -> float | None:
    """Fractional downside to the hard stop, or None if not computable."""
    if entry_price is None or hard_stop_price is None:
        return None
    if entry_price <= 0:
        return None
    if str(side).upper() == "SELL":
        risk = (hard_stop_price - entry_price) / entry_price
    else:
        risk = (entry_price - hard_stop_price) / entry_price
    if risk <= 0:
        return None
    return risk


def evaluate_capacity(
    *,
    ticker: str,
    country: str | None = None,
    capital: float,
    cash_available: float,
    entry_price: float | None,
    hard_stop_price: float | None,
    leverage: float = 1.0,
    leverage_valid: bool = True,
    side: str = "BUY",
    p_adj: float = 0.5,
    freshness_score: float = 1.0,
    moltbook_penalty: float = 0.0,
    regime_ok: bool = True,
    existing_country_exposure: float = 0.0,
) -> dict[str, Any]:
    """Return position sizing + a capacity verdict.  Never executes."""
    stamps = advisory_safety_stamps()
    reasons: list[str] = []

    downside = compute_downside_risk_pct(entry_price, hard_stop_price, side)
    is_india = is_india_instrument(ticker, country)
    country_cap = COUNTRY_CAP_INDIA if is_india else COUNTRY_CAP_OTHER
    max_notional = max(0.0, capital) * MAX_POSITION_PCT

    base: dict[str, Any] = {
        "ticker": (ticker or "").strip(),
        "is_india_instrument": is_india,
        "downside_risk_pct": downside,
        "country_cap": country_cap,
        "max_position_notional": round(max_notional, 6),
        # Advisory-only invariants — present on every verdict.
        "advisory_status": stamps.get("advisory_status"),
        "execution_gate": stamps["execution_gate"],
        "broker_api_called": stamps["broker_api_called"],
        "ai_execution_count": stamps["ai_execution_count"],
        "human_execution_required": True,
        "executes_trade": False,
    }

    # Hard blocks: missing stop or invalid leverage -> no size, WAIT.
    if downside is None:
        reasons.append("hard_stop_price missing/invalid; position size not allowed")
        base.update({
            "position_size_allowed": False,
            "portfolio_capacity_ok": False,
            "position_notional": 0.0,
            "cash_required": None,
            "risk_budget": 0.0,
            "advisory_class": WAIT,
            "blocking_reasons": reasons,
        })
        return base
    if not leverage_valid:
        reasons.append("leverage policy invalid; capacity blocked")
        base.update({
            "position_size_allowed": False,
            "portfolio_capacity_ok": False,
            "position_notional": 0.0,
            "cash_required": None,
            "risk_budget": 0.0,
            "advisory_class": BLOCKED_BY_PORTFOLIO_CAPACITY,
            "blocking_reasons": reasons,
        })
        return base

    conf_mult = _clip((p_adj - 0.5) / 0.25, 0.0, 1.0)
    fresh_mult = _clip(freshness_score / FRESHNESS_FLOOR, 0.0, 1.0)
    molt_mult = max(0.0, 1.0 - float(moltbook_penalty))
    regime_mult = 1.0 if regime_ok else 0.5

    risk_budget = (
        max(0.0, capital) * BASE_RISK_PCT
        * conf_mult * fresh_mult * molt_mult * regime_mult
    )
    raw_notional = risk_budget / downside if downside > 0 else 0.0
    position_notional = min(raw_notional, max_notional)
    lev = leverage if leverage and leverage > 0 else 1.0
    cash_required = position_notional / lev

    projected_country_exposure = existing_country_exposure + position_notional
    country_cap_ok = (
        capital > 0 and (projected_country_exposure / capital) <= country_cap
    )
    cash_ok = cash_available >= cash_required
    notional_ok = position_notional <= max_notional + 1e-9

    if not cash_ok:
        reasons.append(
            f"cash_available {cash_available:g} < cash_required {cash_required:g}"
        )
    if not country_cap_ok:
        reasons.append(
            f"country exposure {projected_country_exposure:g}/{capital:g} "
            f"exceeds cap {country_cap:g}"
        )

    capacity_ok = bool(cash_ok and notional_ok and country_cap_ok)
    advisory_class = ADVISORY_CANDIDATE if capacity_ok else BLOCKED_BY_PORTFOLIO_CAPACITY

    base.update({
        "position_size_allowed": True,
        "risk_budget": round(risk_budget, 6),
        "confidence_multiplier": round(conf_mult, 6),
        "freshness_multiplier": round(fresh_mult, 6),
        "moltbook_multiplier": round(molt_mult, 6),
        "regime_multiplier": regime_mult,
        "position_notional": round(position_notional, 6),
        "cash_required": round(cash_required, 6),
        "projected_country_exposure": round(projected_country_exposure, 6),
        "country_cap_ok": country_cap_ok,
        "cash_ok": cash_ok,
        "portfolio_capacity_ok": capacity_ok,
        "advisory_class": advisory_class,
        "blocking_reasons": reasons,
    })
    return base


__all__ = [
    "BASE_RISK_PCT",
    "MAX_POSITION_PCT",
    "COUNTRY_CAP_INDIA",
    "COUNTRY_CAP_OTHER",
    "FRESHNESS_FLOOR",
    "ADVISORY_CANDIDATE",
    "WAIT",
    "BLOCKED_BY_PORTFOLIO_CAPACITY",
    "NEW_INDIA_ADD_BLOCKED",
    "compute_downside_risk_pct",
    "new_india_add_allowed",
    "evaluate_capacity",
]
