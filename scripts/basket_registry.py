"""Thematic basket registry — customer-facing taxonomy.

This module replaces "here are today's three tickers" with "here are
the thematic baskets the product researches, and which baskets each
ticker belongs to."  It is the central piece that lets a normal retail
user understand the product without needing the founder's brain.

Contract — pure module
----------------------
- No DB, no filesystem, no network, no broker calls, no AI execution.
- Importing this module has no side effects.
- All baskets are educational research baskets, not trade
  instructions.  Every basket record carries explicit
  ``advisory_only`` / ``human_decision_required`` / ``no_execution``
  flags.
- Ticker mapping is deterministic and case-insensitive.
- Unknown tickers degrade gracefully to a clearly-marked
  ``unclassified_research_required`` record — never silently mapped to
  a random basket.
"""
from __future__ import annotations

from typing import Any

VALID_RISK_LEVELS: tuple[str, ...] = (
    "Low",
    "Medium",
    "Medium/High",
    "High",
    "Extreme",
)

# Phrases that must never appear in basket copy.  Mirrors
# ``customer_language.FORBIDDEN_CUSTOMER_PHRASES`` and is enforced by
# ``tests/test_basket_registry.py``.
FORBIDDEN_BASKET_PHRASES: tuple[str, ...] = (
    "buy now",
    "sell now",
    "guaranteed returns",
    "guaranteed return",
    "copy trade",
    "auto trade",
    "auto execute",
    "ai executes",
    "ai decides",
    "profit guaranteed",
    "risk-free",
    "risk free",
    "sure shot",
    "blame the ai",
    "place order",
    "execute order",
    "automatic trade",
)

_ADVISORY_DISCLAIMER = (
    "This basket is educational research and decision support only. "
    "It is not financial advice, not a promise of returns, and not an "
    "instruction to trade. Human decision-making is required."
)


def _basket(
    *,
    basket_id: str,
    basket_name: str,
    plain_english_thesis: str,
    customer_description: str,
    example_tickers: tuple[str, ...],
    risk_level: str,
    min_weight: float,
    max_weight: float,
    max_drawdown_trigger: str,
    rebalance_rule: str,
    what_would_break_thesis: str,
    customer_status: str = "Research View",
) -> dict[str, Any]:
    """Construct a basket dict with the full safety/compliance shape."""
    return {
        "basket_id": basket_id,
        "basket_name": basket_name,
        "plain_english_thesis": plain_english_thesis,
        "customer_description": customer_description,
        "example_tickers": list(example_tickers),
        "risk_level": risk_level,
        "default_model_weight_range": f"{int(min_weight)}–{int(max_weight)}%",
        "min_weight": float(min_weight),
        "max_weight": float(max_weight),
        "max_drawdown_trigger": max_drawdown_trigger,
        "rebalance_rule": rebalance_rule,
        "what_would_break_thesis": what_would_break_thesis,
        "customer_status": customer_status,
        "advisory_disclaimer": _ADVISORY_DISCLAIMER,
        "human_decision_required": True,
        "advisory_only": True,
        "no_execution": True,
    }


# ---------------------------------------------------------------------------
# Canonical basket registry.
# ---------------------------------------------------------------------------
_BASKETS: list[dict[str, Any]] = [
    _basket(
        basket_id="defense_sovereignty",
        basket_name="Defense Sovereignty Basket",
        plain_english_thesis=(
            "European, NATO, and allied defense spending may remain "
            "structurally elevated because of geopolitical pressure, "
            "rearmament cycles, domestic production priorities, and "
            "security policy."
        ),
        customer_description=(
            "Companies exposed to defense procurement, rearmament demand, "
            "and security policy across Europe and allied nations."
        ),
        example_tickers=("RHM.DE", "LMT", "RTX", "NOC", "GD", "LHX"),
        risk_level="Medium/High",
        min_weight=10,
        max_weight=20,
        max_drawdown_trigger="-8% to -10%",
        rebalance_rule="Monthly or after major geopolitical/procurement shock.",
        what_would_break_thesis=(
            "Peace settlement, defense budget cuts, procurement delays, "
            "valuation excess, order slowdown, regulatory issues, or "
            "major geopolitical reversal."
        ),
    ),
    _basket(
        basket_id="energy_shock",
        basket_name="Energy Shock Basket",
        plain_english_thesis=(
            "Oil, gas, LNG, energy security, supply disruptions, OPEC "
            "decisions, and geopolitical stress may create repricing in "
            "energy assets."
        ),
        customer_description=(
            "Integrated energy and oil & gas companies exposed to "
            "supply shocks and energy security repricing."
        ),
        example_tickers=("XOM", "CVX", "SHEL", "TTE", "BP"),
        risk_level="High",
        min_weight=5,
        max_weight=15,
        max_drawdown_trigger="-7% to -10%",
        rebalance_rule="Event-driven plus monthly review.",
        what_would_break_thesis=(
            "Oil/gas price collapse, demand shock, oversupply, "
            "regulatory pressure, policy intervention, or thesis-"
            "reversing geopolitical de-escalation."
        ),
    ),
    _basket(
        basket_id="ai_infrastructure",
        basket_name="AI Infrastructure Basket",
        plain_english_thesis=(
            "AI adoption requires chips, fabs, data centers, networking, "
            "memory, cloud infrastructure, and electrical power capacity."
        ),
        customer_description=(
            "Companies that build the silicon, fabs, and cloud "
            "infrastructure that AI adoption depends on."
        ),
        example_tickers=("NVDA", "AMD", "TSM", "ASML", "MSFT", "GOOGL", "AMZN"),
        risk_level="Medium/High",
        min_weight=15,
        max_weight=25,
        max_drawdown_trigger="-10% to -12%",
        rebalance_rule="Monthly, with valuation risk review.",
        what_would_break_thesis=(
            "AI capex slowdown, margin compression, export controls, "
            "supply chain disruption, valuation reset, or cloud demand "
            "disappointment."
        ),
    ),
    _basket(
        basket_id="commodity_repricing",
        basket_name="Commodity Repricing Basket",
        plain_english_thesis=(
            "Metals, mining, industrial demand, supply constraints, and "
            "global capex cycles may reprice commodity producers."
        ),
        customer_description=(
            "Mining and commodity producers exposed to industrial demand "
            "cycles and supply-side repricing."
        ),
        example_tickers=("VALE", "BHP", "RIO", "FCX", "SCCO"),
        risk_level="High",
        min_weight=5,
        max_weight=15,
        max_drawdown_trigger="-8% to -12%",
        rebalance_rule="Monthly or after macro/China/USD shock.",
        what_would_break_thesis=(
            "China demand weakness, USD surge, commodity price collapse, "
            "supply glut, regulatory shock, or capex cycle deterioration."
        ),
    ),
    _basket(
        basket_id="shipping_dislocation",
        basket_name="Shipping Dislocation Basket",
        plain_english_thesis=(
            "Freight rates, Red Sea risk, port bottlenecks, sanctions, "
            "war risk, insurance costs, and global trade rerouting may "
            "create volatility in shipping companies."
        ),
        customer_description=(
            "Container, tanker, and dry bulk shipping companies exposed "
            "to freight-rate volatility and trade-route disruption."
        ),
        example_tickers=("ZIM", "MAERSK-B.CO", "HLAG.DE", "DAC", "SBLK"),
        risk_level="Extreme",
        min_weight=0,
        max_weight=10,
        max_drawdown_trigger="-10%",
        rebalance_rule="Event-driven only; avoid oversized exposure.",
        what_would_break_thesis=(
            "Freight rate collapse, route normalization, oversupply, "
            "demand slowdown, geopolitical de-escalation, or "
            "company-specific balance sheet stress."
        ),
    ),
    _basket(
        basket_id="india_domestic_compounding",
        basket_name="India Domestic Compounding Basket",
        plain_english_thesis=(
            "Indian domestic demand, telecom, banking, infrastructure, "
            "consumption, manufacturing, and digital growth may support "
            "long-term compounding."
        ),
        customer_description=(
            "Large Indian companies positioned for long-term domestic "
            "demand, telecom, banking, and infrastructure growth."
        ),
        example_tickers=(
            "NSE:BHARTIARTL",
            "NSE:RELIANCE",
            "NSE:HDFCBANK",
            "NSE:ICICIBANK",
            "NSE:LT",
            "NSE:TCS",
        ),
        risk_level="Medium",
        min_weight=15,
        max_weight=30,
        max_drawdown_trigger="-8% to -10%",
        rebalance_rule="Monthly or earnings-cycle review.",
        what_would_break_thesis=(
            "Earnings deterioration, valuation excess, INR shock, policy "
            "shock, credit stress, or domestic demand slowdown."
        ),
    ),
    _basket(
        basket_id="cash_risk_off",
        basket_name="Cash / Risk-Off Basket",
        plain_english_thesis=(
            "This basket is not a return-seeking equity basket. It "
            "represents dry powder, caution, capital preservation, and "
            "reduced exposure during chaotic or unclear market regimes."
        ),
        customer_description=(
            "Cash, ultra-short Treasuries, and defensive hedges used to "
            "preserve capital during chaotic or unclear regimes."
        ),
        example_tickers=("CASH", "SGOV", "BIL", "SHV", "GLD"),
        risk_level="Low",
        min_weight=10,
        max_weight=40,
        max_drawdown_trigger="N/A",
        rebalance_rule=(
            "Increase during DIABLO/chaos regimes, decrease during "
            "confirmed constructive regimes."
        ),
        what_would_break_thesis=(
            "Clear improvement in market regime, reduced chaos risk, "
            "improved breadth, stronger confirmation across baskets."
        ),
    ),
]

# Explicit override map for tickers that legitimately appear in more
# than one basket's example list, or that need a primary mapping
# different from "the first basket that lists them."  GLD is in the
# Cash / Risk-Off example list as a defensive hedge — when a user looks
# up GLD, that is the basket we map them to.
_PRIMARY_TICKER_OVERRIDES: dict[str, str] = {
    "GLD": "cash_risk_off",
    "CASH": "cash_risk_off",
}


def _normalize_ticker(ticker: Any) -> str:
    """Normalise a ticker for case-insensitive lookup.

    Trims whitespace, upper-cases.  Does NOT strip exchange prefixes
    (``NSE:BHARTIARTL``) — those are part of the canonical identifier.
    Returns an empty string for ``None`` or empty input.
    """
    if ticker is None:
        return ""
    try:
        return str(ticker).strip().upper()
    except Exception:  # pragma: no cover — defensive
        return ""


def list_baskets() -> list[dict]:
    """Return all baskets as a list of fresh dicts."""
    return [dict(b) for b in _BASKETS]


def get_basket_by_id(basket_id: Any) -> dict | None:
    """Look up a basket by its canonical id.  Returns ``None`` if absent."""
    key = "" if basket_id is None else str(basket_id).strip().lower()
    if not key:
        return None
    for basket in _BASKETS:
        if basket["basket_id"] == key:
            return dict(basket)
    return None


def find_baskets_for_ticker(ticker: Any) -> list[dict]:
    """Return every basket whose example tickers include ``ticker``.

    Case-insensitive.  Returns an empty list for unknown tickers (the
    caller can then choose to wrap that in
    :func:`get_unclassified_ticker_response`).
    """
    key = _normalize_ticker(ticker)
    if not key:
        return []
    out: list[dict] = []
    for basket in _BASKETS:
        for t in basket["example_tickers"]:
            if t.upper() == key:
                out.append(dict(basket))
                break
    return out


def get_unclassified_ticker_response(ticker: Any) -> dict:
    """Build the canonical "unknown ticker" response.

    The response is intentionally explicit: it is not silently mapped
    to any basket, it carries advisory-only / human-decision-required /
    no-execution stamps, and it tells the customer the ticker needs
    manual research review.
    """
    key = _normalize_ticker(ticker)
    return {
        "ticker": key,
        "basket_id": "unclassified_research_required",
        "basket_name": "Unclassified / Research Required",
        "customer_explanation": (
            f"{key or 'This ticker'} is not yet mapped to a customer-facing "
            "basket and requires manual research review."
        ),
        "advisory_only": True,
        "human_decision_required": True,
        "no_execution": True,
        "advisory_disclaimer": _ADVISORY_DISCLAIMER,
    }


def explain_ticker_basket_mapping(ticker: Any) -> dict:
    """Return a customer-facing "why is this ticker here?" explanation.

    Picks the primary basket via :data:`_PRIMARY_TICKER_OVERRIDES`
    first, then falls back to the first basket that lists the ticker.
    Unknown tickers go through :func:`get_unclassified_ticker_response`.
    """
    key = _normalize_ticker(ticker)
    if not key:
        return get_unclassified_ticker_response(ticker)

    primary_id = _PRIMARY_TICKER_OVERRIDES.get(key)
    matches = find_baskets_for_ticker(key)
    if not matches:
        return get_unclassified_ticker_response(key)

    if primary_id is not None:
        primary = next(
            (m for m in matches if m["basket_id"] == primary_id), matches[0]
        )
    else:
        primary = matches[0]

    return {
        "ticker": key,
        "basket_id": primary["basket_id"],
        "basket_name": primary["basket_name"],
        "customer_explanation": (
            f"{key} belongs to the {primary['basket_name']} because "
            f"the basket holds "
            f"{primary['customer_description'].lower()}"
        ),
        "risk_level": primary["risk_level"],
        "all_basket_ids": [m["basket_id"] for m in matches],
        "advisory_only": True,
        "human_decision_required": True,
        "no_execution": True,
        "advisory_disclaimer": _ADVISORY_DISCLAIMER,
    }


def validate_basket_registry() -> dict:
    """Validate the in-memory registry.

    Pure check, no I/O.  Returns a structured result so the API and
    tests can both consume it.  ``ok`` is True iff there are zero
    errors.
    """
    errors: list[str] = []
    ids_seen: set[str] = set()
    required_fields = (
        "basket_id",
        "basket_name",
        "plain_english_thesis",
        "customer_description",
        "example_tickers",
        "risk_level",
        "default_model_weight_range",
        "min_weight",
        "max_weight",
        "max_drawdown_trigger",
        "rebalance_rule",
        "what_would_break_thesis",
        "customer_status",
        "advisory_disclaimer",
        "human_decision_required",
        "advisory_only",
        "no_execution",
    )
    for basket in _BASKETS:
        bid = basket.get("basket_id", "")
        if not bid:
            errors.append("basket missing basket_id")
            continue
        if bid in ids_seen:
            errors.append(f"duplicate basket_id: {bid}")
        ids_seen.add(bid)
        for field in required_fields:
            if field not in basket:
                errors.append(f"basket {bid} missing field: {field}")
        if basket.get("risk_level") not in VALID_RISK_LEVELS:
            errors.append(
                f"basket {bid} has invalid risk_level: {basket.get('risk_level')!r}"
            )
        if not basket.get("example_tickers"):
            errors.append(f"basket {bid} has no example tickers")
        if basket.get("advisory_only") is not True:
            errors.append(f"basket {bid} missing advisory_only flag")
        if basket.get("human_decision_required") is not True:
            errors.append(f"basket {bid} missing human_decision_required flag")
        if basket.get("no_execution") is not True:
            errors.append(f"basket {bid} missing no_execution flag")
        try:
            mn = float(basket.get("min_weight", -1))
            mx = float(basket.get("max_weight", -1))
            if mn < 0 or mx <= 0 or mn > mx:
                errors.append(
                    f"basket {bid} has invalid weight bounds: {mn}–{mx}"
                )
        except (TypeError, ValueError):
            errors.append(f"basket {bid} has non-numeric weight bounds")

        haystack = " ".join(
            str(basket.get(field, ""))
            for field in (
                "plain_english_thesis",
                "customer_description",
                "rebalance_rule",
                "what_would_break_thesis",
                "advisory_disclaimer",
            )
        ).lower()
        for phrase in FORBIDDEN_BASKET_PHRASES:
            if phrase in haystack:
                errors.append(
                    f"basket {bid} contains forbidden phrase: {phrase!r}"
                )
    return {
        "ok": not errors,
        "basket_count": len(_BASKETS),
        "errors": errors,
    }


__all__ = [
    "VALID_RISK_LEVELS",
    "FORBIDDEN_BASKET_PHRASES",
    "list_baskets",
    "get_basket_by_id",
    "find_baskets_for_ticker",
    "explain_ticker_basket_mapping",
    "get_unclassified_ticker_response",
    "validate_basket_registry",
]
