"""Customer-facing model portfolio layer.

Wraps the basket registry into a default, advisory-only, educational
model portfolio.  The point is to stop the product from looking like
"three stock tips" and start looking like a coherent thematic research
allocation with weights, risk bands, invalidation rules, and rebalance
logic.

Contract — pure module
----------------------
- No DB, no filesystem, no network, no broker calls, no AI execution.
- Importing this module has no side effects.
- The model portfolio is decision support only.  It does not authorise
  a trade, place an order, or claim a guaranteed return.
- Validation is pure and deterministic: the same inputs always produce
  the same errors list.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.basket_registry import (
        FORBIDDEN_BASKET_PHRASES,
        get_basket_by_id,
        list_baskets,
    )
except ModuleNotFoundError:  # pragma: no cover — flat-layout fallback
    from basket_registry import (  # type: ignore
        FORBIDDEN_BASKET_PHRASES,
        get_basket_by_id,
        list_baskets,
    )

try:
    from scripts.customer_language import (
        CUSTOMER_LABEL_AVOID_EXIT_RISK,
        CUSTOMER_LABEL_ENTER_ADD,
        CUSTOMER_LABEL_HOLD_MANAGE,
        CUSTOMER_LABEL_STRONG_WATCH,
        CUSTOMER_LABEL_REVIEW,
        CUSTOMER_LABEL_WATCH,
        KNOWN_CUSTOMER_LABELS,
    )
except ModuleNotFoundError:  # pragma: no cover
    from customer_language import (  # type: ignore
        CUSTOMER_LABEL_AVOID_EXIT_RISK,
        CUSTOMER_LABEL_ENTER_ADD,
        CUSTOMER_LABEL_HOLD_MANAGE,
        CUSTOMER_LABEL_STRONG_WATCH,
        CUSTOMER_LABEL_REVIEW,
        CUSTOMER_LABEL_WATCH,
        KNOWN_CUSTOMER_LABELS,
    )


_MODEL_PORTFOLIO_ID = "sleeping_passenger_balanced_research_model"
_MODEL_PORTFOLIO_NAME = "Sleeping Passenger Balanced Research Model"

_MODEL_PORTFOLIO_DESCRIPTION = (
    "A customer-facing educational model portfolio that converts global "
    "market, geopolitical, narrative, and capital-flow signals into "
    "thematic baskets. This is decision support only and does not "
    "execute trades."
)

_RISK_PROFILE = "Moderate/High research model"

_REBALANCE_FREQUENCY = (
    "Monthly, plus event-driven review after major shock alerts."
)

_ADVISORY_DISCLAIMER = (
    "This product provides educational research and decision support "
    "only. It is not financial advice, not a promise of returns, and "
    "not an instruction to trade. Human decision-making is required."
)

# Allocation must sum to exactly 100.  Default basket-id -> (weight,
# customer_status) for the initial release model.  Customer status uses
# the *customer-facing* labels, never raw internal states.
_DEFAULT_ALLOCATION: list[dict[str, Any]] = [
    {
        "basket_id": "ai_infrastructure",
        "target_weight": 20,
        "current_action_label": CUSTOMER_LABEL_ENTER_ADD,
    },
    {
        "basket_id": "india_domestic_compounding",
        "target_weight": 20,
        "current_action_label": CUSTOMER_LABEL_HOLD_MANAGE,
    },
    {
        "basket_id": "defense_sovereignty",
        "target_weight": 15,
        "current_action_label": CUSTOMER_LABEL_ENTER_ADD,
    },
    {
        "basket_id": "energy_shock",
        "target_weight": 10,
        "current_action_label": CUSTOMER_LABEL_STRONG_WATCH,
    },
    {
        "basket_id": "commodity_repricing",
        "target_weight": 10,
        "current_action_label": CUSTOMER_LABEL_WATCH,
    },
    {
        "basket_id": "shipping_dislocation",
        "target_weight": 5,
        "current_action_label": CUSTOMER_LABEL_WATCH,
    },
    {
        "basket_id": "cash_risk_off",
        "target_weight": 20,
        "current_action_label": CUSTOMER_LABEL_HOLD_MANAGE,
    },
]

# Per-risk-level max weight (in %) that a single basket may carry in
# the default model.  ``High`` and ``Extreme`` baskets are bounded so
# the model never becomes a one-thesis bet.
_RISK_LEVEL_MAX_WEIGHT: dict[str, float] = {
    "Low": 50.0,
    "Medium": 35.0,
    "Medium/High": 25.0,
    "High": 15.0,
    "Extreme": 10.0,
}

_DRAWDOWN_RULES: dict[str, str] = {
    "review_trigger": "-10% model drawdown triggers review.",
    "defensive_trigger": "-15% model drawdown triggers defensive posture.",
    "thesis_audit_trigger": (
        "-20% model drawdown triggers full thesis audit / Moltbook review."
    ),
}


def _build_allocation_row(entry: dict[str, Any]) -> dict[str, Any]:
    """Build a full allocation row by joining basket metadata + weight."""
    basket = get_basket_by_id(entry["basket_id"]) or {}
    return {
        "basket_id": entry["basket_id"],
        "basket_name": basket.get("basket_name", entry["basket_id"]),
        "target_weight": float(entry["target_weight"]),
        "min_weight": float(basket.get("min_weight", 0.0)),
        "max_weight": float(basket.get("max_weight", 0.0)),
        "current_action_label": entry.get(
            "current_action_label", CUSTOMER_LABEL_REVIEW
        ),
        "risk_level": basket.get("risk_level", "Medium"),
        "thesis_summary": basket.get("plain_english_thesis", ""),
        "invalidation_summary": basket.get("what_would_break_thesis", ""),
        "rebalance_rule": basket.get("rebalance_rule", ""),
        "representative_tickers": list(basket.get("example_tickers", [])),
        "customer_status": basket.get("customer_status", "Research View"),
        "advisory_only": True,
        "human_decision_required": True,
        "no_execution": True,
    }


def get_default_model_portfolio() -> dict:
    """Build the canonical default model portfolio response."""
    allocation = [_build_allocation_row(e) for e in _DEFAULT_ALLOCATION]
    total = sum(row["target_weight"] for row in allocation)
    return {
        "model_portfolio_id": _MODEL_PORTFOLIO_ID,
        "model_portfolio_name": _MODEL_PORTFOLIO_NAME,
        "description": _MODEL_PORTFOLIO_DESCRIPTION,
        "risk_profile": _RISK_PROFILE,
        "rebalance_frequency": _REBALANCE_FREQUENCY,
        "drawdown_rules": dict(_DRAWDOWN_RULES),
        "total_target_weight": float(total),
        "allocation": allocation,
        "advisory_only": True,
        "human_decision_required": True,
        "human_execution_required": True,
        "no_execution": True,
        "execution_permission": "LOCKED",
        "advisory_disclaimer": _ADVISORY_DISCLAIMER,
    }


def get_model_portfolio_summary() -> dict:
    """Return only the header / summary metadata for the default model."""
    portfolio = get_default_model_portfolio()
    return {
        "model_portfolio_id": portfolio["model_portfolio_id"],
        "model_portfolio_name": portfolio["model_portfolio_name"],
        "description": portfolio["description"],
        "risk_profile": portfolio["risk_profile"],
        "rebalance_frequency": portfolio["rebalance_frequency"],
        "drawdown_rules": portfolio["drawdown_rules"],
        "total_target_weight": portfolio["total_target_weight"],
        "basket_count": len(portfolio["allocation"]),
        "advisory_only": True,
        "human_decision_required": True,
        "human_execution_required": True,
        "no_execution": True,
        "execution_permission": "LOCKED",
        "advisory_disclaimer": portfolio["advisory_disclaimer"],
    }


def get_portfolio_drawdown_rules() -> dict:
    """Return the drawdown rules table for the default model."""
    return dict(_DRAWDOWN_RULES)


def get_basket_allocation_table() -> list[dict]:
    """Return the basket allocation rows as a flat table for the UI."""
    return get_default_model_portfolio()["allocation"]


def validate_model_portfolio(portfolio: dict) -> dict:
    """Validate ``portfolio``'s shape, weights, risk bounds, and safety.

    Returns a structured result; ``ok`` is True iff there are zero
    errors.  Pure function — never raises.
    """
    errors: list[str] = []

    if not isinstance(portfolio, dict):
        return {"ok": False, "errors": ["portfolio must be a dict"]}

    allocation = portfolio.get("allocation")
    if not isinstance(allocation, list) or not allocation:
        return {"ok": False, "errors": ["portfolio.allocation must be a non-empty list"]}

    valid_basket_ids = {b["basket_id"] for b in list_baskets()}
    seen_ids: set[str] = set()
    total = 0.0
    has_cash = False
    for row in allocation:
        if not isinstance(row, dict):
            errors.append("allocation row must be a dict")
            continue
        bid = row.get("basket_id", "")
        if not bid:
            errors.append("allocation row missing basket_id")
            continue
        if bid in seen_ids:
            errors.append(f"duplicate basket in allocation: {bid}")
        seen_ids.add(bid)
        if bid not in valid_basket_ids:
            errors.append(f"unknown basket in allocation: {bid}")
        if bid == "cash_risk_off":
            has_cash = True
        try:
            w = float(row.get("target_weight", -1))
        except (TypeError, ValueError):
            errors.append(f"basket {bid} has non-numeric target_weight")
            continue
        if w < 0:
            errors.append(f"basket {bid} has negative target_weight")
            continue
        total += w

        basket = get_basket_by_id(bid)
        if basket is not None:
            risk = basket.get("risk_level", "Medium")
            cap = _RISK_LEVEL_MAX_WEIGHT.get(risk, 25.0)
            if w > cap:
                errors.append(
                    f"basket {bid} weight {w}% exceeds risk-level cap "
                    f"{cap}% for {risk}"
                )
            if not basket.get("plain_english_thesis"):
                errors.append(f"basket {bid} missing thesis")
            if not basket.get("what_would_break_thesis"):
                errors.append(f"basket {bid} missing invalidation logic")
            if not basket.get("rebalance_rule"):
                errors.append(f"basket {bid} missing rebalance rule")
            if not basket.get("advisory_disclaimer"):
                errors.append(f"basket {bid} missing advisory disclaimer")

        label = row.get("current_action_label", "")
        if label and label not in KNOWN_CUSTOMER_LABELS:
            errors.append(
                f"basket {bid} uses non-customer action label: {label!r}"
            )
        if label == CUSTOMER_LABEL_AVOID_EXIT_RISK and w > 0:
            errors.append(
                f"basket {bid} flagged Avoid/Exit Risk but allocated {w}%"
            )

    if abs(total - 100.0) > 1e-6:
        errors.append(f"allocation weights sum to {total}, expected 100")

    if not has_cash:
        errors.append("portfolio missing cash_risk_off basket")

    if portfolio.get("advisory_only") is not True:
        errors.append("portfolio missing advisory_only flag")
    if portfolio.get("human_decision_required") is not True:
        errors.append("portfolio missing human_decision_required flag")
    if portfolio.get("human_execution_required") is not True:
        errors.append("portfolio missing human_execution_required flag")
    if portfolio.get("no_execution") is not True:
        errors.append("portfolio missing no_execution flag")
    if portfolio.get("execution_permission") != "LOCKED":
        errors.append("portfolio missing execution_permission=LOCKED")

    haystack = " ".join(
        str(portfolio.get(field, ""))
        for field in ("description", "risk_profile", "advisory_disclaimer")
    ).lower()
    for phrase in FORBIDDEN_BASKET_PHRASES:
        if phrase in haystack:
            errors.append(f"portfolio contains forbidden phrase: {phrase!r}")

    return {
        "ok": not errors,
        "total_weight": total,
        "basket_count": len(seen_ids),
        "errors": errors,
    }


__all__ = [
    "get_default_model_portfolio",
    "get_model_portfolio_summary",
    "get_portfolio_drawdown_rules",
    "get_basket_allocation_table",
    "validate_model_portfolio",
]
